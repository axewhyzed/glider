"""Preview and final report builders (P8.4/P8.6)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from engine.network import FetchResult
from engine.schemas import ScraperConfig


@dataclass
class PreviewDiagnostics:
    field_matches: Dict[str, Any] = field(default_factory=dict)
    samples: Dict[str, list] = field(default_factory=dict)
    pagination_match: Any = None
    pagination_next: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    nested_fetched: int = 0


def build_preview_report(
    fetch: FetchResult,
    data: Dict[str, Any],
    config: ScraperConfig,
    diagnostics: PreviewDiagnostics,
) -> Dict[str, Any]:
    """Assemble the preview/dry-run report (P8.4)."""
    pagination = None
    if config.pagination:
        pagination = {
            "configured": True,
            "selector": {"type": config.pagination.selector.type.value,
                         "value": config.pagination.selector.value},
            "matched": diagnostics.pagination_match is not None,
            "next_value": diagnostics.pagination_match,
            "next_url": diagnostics.pagination_next,
        }
    else:
        pagination = {
            "configured": False,
            "selector": None,
            "matched": False,
            "next_value": None,
            "next_url": None,
        }
    fields_report = []
    for field in config.fields:
        fields_report.append({
            "name": field.name,
            "selector_count": len(field.selectors),
            "matched": diagnostics.field_matches.get(field.name, 0) > 0,
            "match_count": diagnostics.field_matches.get(field.name, 0),
            "is_list": field.is_list,
            "sample": diagnostics.samples.get(field.name, [])[:3],
            "transformers": [t.name.value for t in field.transformers],
        })
    return {
        "requested_url": fetch.requested_url,
        "final_url": fetch.final_url,
        "status_code": fetch.status_code,
        "elapsed_ms": round(fetch.elapsed_ms, 2),
        "mode": config.mode.value,
        "response_type": config.response_type,
        "pagination": pagination,
        "fields": fields_report,
        "sample_record": data,
        "record_count": len(data) if isinstance(data, list) else (1 if data else 0),
        "nested_fetched": diagnostics.nested_fetched,
        "warnings": diagnostics.warnings,
    }


def build_final_report(
    stats: Any,
    context: Any,
    config: ScraperConfig,
    metrics_snapshot: Dict[str, Any],
    resume_command: str,
) -> Dict[str, Any]:
    """Assemble the end-of-run report (P8.6)."""
    from pathlib import Path

    artifact_sizes = {}
    for name, path in {
        "stream.jsonl": context.stream_path,
        "output.json": context.export_directory / "output.json",
        "output.csv": context.export_directory / "output.csv",
    }.items():
        p = Path(path)
        artifact_sizes[name] = p.stat().st_size if p.exists() else 0

    failed_preview = [entry.get("url", "") for entry in list(stats.failures_ring or [])[:5]]
    return {
        "run_id": context.run_id,
        "config_name": config.name,
        "state": "completed",
        "pages": {
            "success": getattr(stats, "success", 0),
            "failed": getattr(stats, "failed", 0),
            "skipped": getattr(stats, "skipped", 0),
            "blocked": getattr(stats, "blocked", 0),
            "total": getattr(stats, "success", 0) + getattr(stats, "failed", 0),
        },
        "records": {
            "extracted": getattr(stats, "entries_extracted", 0),
            "deduplicated": metrics_snapshot.get("duplicates_detected", 0),
        },
        "domains": metrics_snapshot.get("domains", {}),
        "latency_ms": metrics_snapshot.get("latency_ms", {}),
        "error_categories": _aggregate_categories(metrics_snapshot.get("domains", {})),
        "outputs": {},
        "failed_urls_preview": failed_preview,
        "artifact_sizes_bytes": artifact_sizes,
        "resume_command": resume_command,
    }


def _aggregate_categories(domains: Dict[str, Any]) -> Dict[str, int]:
    agg: Dict[str, int] = {}
    for dc in domains.values():
        for category, count in dc.get("by_category", {}).items():
            agg[category] = agg.get(category, 0) + count
    return agg


def build_resume_command(
    argv: List[str], run_id: str, config_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    """Build an executable, shell-safe resume command."""
    import sys
    import shlex
    script = argv[0] if argv else "main.py"
    # Console-script invocations already point at the executable; Python
    # scripts need the interpreter prefix.
    command = [sys.executable, script] if script.lower().endswith((".py", ".pyw")) else [script]
    command += ["scrape"]
    if config_path:
        command.append(config_path)
    command += ["--resume", run_id]
    if output_dir:
        command += ["--output-dir", output_dir]
    return " ".join(shlex.quote(str(part)) for part in command)
