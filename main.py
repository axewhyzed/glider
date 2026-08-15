"""Glider command-line interface."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from loguru import logger
from rich.console import Console
from rich.live import Live
from rich.table import Table

from engine.export import convert_to_csv, convert_to_json
from engine.exitcodes import ExitCode
from engine.report import build_final_report, build_resume_command, build_preview_report, PreviewDiagnostics
from engine.redact import loguru_filter
from engine.run import RunContext
from engine.schemas import ScrapeMode, ScraperConfig, StatsEvent
from engine.scraper import ScraperEngine
from engine.utils import load_config
from engine.validation import ValidationResult, validate_config_file
from engine.writer import JsonlStreamWriter


app = typer.Typer(no_args_is_help=True)
console = Console()

# curl_cffi's async layer needs a selector event loop on Windows (the Proactor
# loop lacks add_reader); install the selector policy before any network work.
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass


class ScrapeStats:
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.blocked = 0
        self.entries_extracted = 0
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        self.rps_samples: list[float] = []

    def update(self, event: StatsEvent):
        if event.event_type == "page_success":
            self.success += event.count
        elif event.event_type in {"page_error", "http_error", "parse_error", "network_error"}:
            self.failed += event.count
        elif event.event_type == "page_skipped":
            self.skipped += event.count
        elif event.event_type in {"blocked", "robots_blocked", "url_policy_blocked"}:
            self.blocked += event.count
        elif event.event_type == "entries_added":
            self.entries_extracted += event.count
            self._update_rps(event.count)

    def _update_rps(self, new_entries: int):
        now = datetime.now()
        elapsed = (now - self.last_update).total_seconds()
        if elapsed > 0:
            self.rps_samples.append(new_entries / elapsed)
            if len(self.rps_samples) > 10:
                self.rps_samples.pop(0)
        self.last_update = now

    @property
    def avg_rps(self) -> float:
        return sum(self.rps_samples) / len(self.rps_samples) if self.rps_samples else 0.0


def generate_dashboard(stats: ScrapeStats, config_name: str) -> Table:
    elapsed = datetime.now() - stats.start_time
    table = Table(title=f"Glider Scraper: {config_name}")
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="magenta", width=20)
    table.add_row("Elapsed Time", str(elapsed).split(".")[0])
    table.add_row("Successful Pages", str(stats.success))
    table.add_row("Failed Pages", f"[red]{stats.failed}[/red]")
    table.add_row("Skipped", str(stats.skipped))
    table.add_row("Blocked", f"[yellow]{stats.blocked}[/yellow]")
    table.add_row("Total Records", f"[bold green]{stats.entries_extracted}[/bold green]")
    table.add_row("Avg Entries/sec", f"{stats.avg_rps:.2f}")
    return table


def setup_logging(log_dir: Path = Path("logs"), level: str = "INFO") -> None:
    logger.remove()
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "glider.log",
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module} - {message}",
        filter=loguru_filter,
    )


def _print_validation(result: ValidationResult, output_format: str) -> None:
    if output_format == "json":
        console.print(json.dumps(result.as_dict(), indent=2))
        return
    if result.valid:
        console.print("[green]Configuration is valid.[/green]")
    else:
        for issue in result.issues:
            style = "yellow" if issue.severity == "warning" else "red"
            console.print(f"[{style}]x {issue.path}: {issue.message}[/{style}]")


async def main_async(
    config: ScraperConfig,
    run_context: RunContext,
    limit: Optional[int] = None,
) -> ScrapeStats:
    stats = ScrapeStats()
    writer = JsonlStreamWriter(run_context.stream_path)

    engine = ScraperEngine(
        config,
        stats_callback=stats.update,
        run_context=run_context,
        limit=limit,
        stream_writer=writer,
    )

    with Live(generate_dashboard(stats, config.name), refresh_per_second=4) as live:
        async def ui_updater():
            while True:
                live.update(generate_dashboard(stats, config.name))
                await asyncio.sleep(0.5)

        ui_task = asyncio.create_task(ui_updater())
        try:
            await engine.run()
        finally:
            ui_task.cancel()
            try:
                await ui_task
            except asyncio.CancelledError:
                pass
    stats.metrics_snapshot = engine.metrics.snapshot()  # type: ignore[attr-defined]
    stats.failures_ring = engine.failures_ring  # type: ignore[attr-defined]
    return stats


def _atomic_export(stream: Path, output_dir: Path, field_order: list[str]) -> Dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_output = output_dir / "output.json"
    csv_output = output_dir / "output.csv"
    json_tmp = output_dir / "output.json.tmp"
    csv_tmp = output_dir / "output.csv.tmp"
    for temporary in (json_tmp, csv_tmp):
        temporary.unlink(missing_ok=True)
    convert_to_json(stream, json_tmp)
    convert_to_csv(stream, csv_tmp, field_order=field_order)
    os.replace(json_tmp, json_output)
    os.replace(csv_tmp, csv_output)
    return {"json": str(json_output), "csv": str(csv_output)}


async def _run_preview(config: ScraperConfig, url: Optional[str]) -> Dict[str, Any]:
    engine = ScraperEngine(config, dry_run=True)
    result, data = await engine.preview(url)
    diagnostics = PreviewDiagnostics(
        field_matches={f.name: 0 for f in config.fields},
        samples={},
        pagination_match=None,
        pagination_next=None,
        warnings=[],
    )
    return build_preview_report(result, data, config, diagnostics)


@app.command()
def validate(
    config_path: str,
    output_format: str = typer.Option("text", "--format", help="text or json"),
):
    """Validate JSON, schema, selector, semantic, and local-file rules."""
    if output_format not in {"text", "json"}:
        console.print("[red]--format must be text or json[/red]")
        raise typer.Exit(ExitCode.INVALID_INPUT)
    try:
        result = validate_config_file(config_path)
    except Exception as exc:
        console.print(f"[red]Validation failed unexpectedly: {exc}[/red]")
        raise typer.Exit(ExitCode.RUNTIME_ERROR)
    _print_validation(result, output_format)
    if not result.valid:
        raise typer.Exit(ExitCode.INVALID_INPUT)


@app.command()
def preview(
    config_path: str,
    url: Optional[str] = typer.Option(None, "--url"),
    output_format: str = typer.Option("text", "--format", help="text or json"),
):
    """Fetch and inspect one page without writing durable crawl artifacts."""
    if output_format not in {"text", "json"}:
        console.print("[red]--format must be text or json[/red]")
        raise typer.Exit(ExitCode.INVALID_INPUT)
    result = validate_config_file(config_path)
    if not result.valid or not result.config:
        _print_validation(result, "text")
        raise typer.Exit(ExitCode.INVALID_INPUT)
    setup_logging()
    try:
        report = asyncio.run(_run_preview(result.config, url))
    except Exception as exc:
        console.print(f"[red]Preview failed: {exc}[/red]")
        raise typer.Exit(ExitCode.RUNTIME_ERROR)
    if output_format == "json":
        console.print(json.dumps(report, indent=2, default=str))
    else:
        console.print(f"URL: {report['requested_url']}")
        console.print(f"Final URL: {report['final_url']}")
        console.print(f"HTTP: {report['status_code']} ({report['elapsed_ms']} ms)")
        console.print(json.dumps(report["sample_record"], indent=2, ensure_ascii=False, default=str))


@app.command()
def scrape(
    config_path: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    url: Optional[str] = typer.Option(None, "--url", help="Probe a specific URL in dry-run/preview mode"),
    limit: Optional[int] = typer.Option(None, "--limit", min=1),
    output_dir: Path = typer.Option(Path("data"), "--output-dir"),
    run_id: Optional[str] = typer.Option(None, "--run-id"),
    resume: Optional[str] = typer.Option(None, "--resume"),
    log_level: str = typer.Option("INFO", "--log-level", help="debug|info|warning|error"),
):
    """Run a crawl in an isolated, resumable run directory."""
    result = validate_config_file(config_path)
    if not result.valid or not result.config or not result.raw_config:
        _print_validation(result, "text")
        raise typer.Exit(ExitCode.INVALID_INPUT)
    config = result.config
    setup_logging(level=log_level)

    if dry_run:
        try:
            report = asyncio.run(_run_preview(config, url))
            console.print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        except Exception as exc:
            console.print(f"[red]Dry run failed: {exc}[/red]")
            raise typer.Exit(ExitCode.RUNTIME_ERROR)
        return

    selected_run_id = resume or run_id
    try:
        context = RunContext.create(
            config.name,
            result.raw_config,
            output_root=output_dir,
            run_id=selected_run_id,
            resume=resume is not None,
        )
        setup_logging(context.directory / "logs", level=log_level)
        stats = asyncio.run(main_async(config, context, limit=limit))
        _finalize_run(context, config, stats, config_path)
        console.print(f"[green]Run complete: {context.run_id}[/green]")
        console.print(f"Artifacts: {context.directory}")
        if stats.failed:
            raise typer.Exit(ExitCode.PARTIAL_FAILURE)
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted; the run artifacts were preserved for resume.[/yellow]")
        try:
            _finalize_run(context, config, None, config_path, cancelled=True)  # type: ignore[arg-type]
        except Exception:
            pass
        raise typer.Exit(ExitCode.INTERRUPTED)
    except typer.Exit:
        raise
    except Exception as exc:
        logger.exception("Fatal scrape error")
        console.print(f"[red]Scrape failed: {exc}[/red]")
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


def _finalize_run(context, config, stats, config_path, cancelled: bool = False):
    """Export partials, write the final report + manifest (P8.6/P9.5).

    Shared by the success and interrupt paths so an interrupted run also
    exports partial data and records an honest manifest state.
    """
    if context.stream_path.exists() and context.stream_path.stat().st_size > 0:
        outputs = _atomic_export(
            context.stream_path,
            context.export_directory,
            [field.name for field in config.fields],
        )
    else:
        outputs = {}
    metrics = {}
    failures_ring = []
    if stats is not None:
        metrics = stats.metrics_snapshot if hasattr(stats, "metrics_snapshot") else {}
        failures_ring = getattr(stats, "failures_ring", [])
    state = "cancelled" if cancelled else "completed"
    resume_cmd = build_resume_command([sys.argv[0], config_path], context.run_id)
    report = build_final_report(
        stats if stats is not None else _EmptyStats(),
        context,
        config,
        metrics,
        resume_cmd,
    )
    report["state"] = state
    context.update_manifest(
        state=state,
        finished_at=datetime.utcnow().isoformat() + "Z",
        pages={"success": getattr(stats, "success", 0), "failed": getattr(stats, "failed", 0)} if stats else {},
        records=getattr(stats, "entries_extracted", 0),
        outputs=outputs,
        summary=report,
        resume_command=resume_cmd,
    )
    (context.directory / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    console.print(f"[cyan]Report: {context.directory / 'report.json'}[/cyan]")
    console.print(f"[cyan]Resume: {resume_cmd}[/cyan]")


class _EmptyStats:
    """Fallback stats object for interrupted runs where live stats are unavailable."""

    success = 0
    failed = 0
    skipped = 0
    blocked = 0
    entries_extracted = 0
    failures_ring = []


def run():
    """Console-script entry point (P10.1)."""
    app()


if __name__ == "__main__":
    app()
