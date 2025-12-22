import sys
import os
import typer
import json
import asyncio
import aiofiles
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Optional

from rich.live import Live
from rich.table import Table
from rich.console import Console

from engine.schemas import ScraperConfig, StatsEvent
from engine.scraper import ScraperEngine
from engine.export import convert_to_json, convert_to_csv

app = typer.Typer()
console = Console()

class ScrapeStats:
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.blocked = 0
        self.entries_extracted = 0
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        self.rps_samples = []

    def update(self, event: StatsEvent):
        if event.event_type == "page_success": self.success += event.count
        elif event.event_type == "page_error": self.failed += event.count
        elif event.event_type == "page_skipped": self.skipped += event.count
        elif event.event_type == "blocked": self.blocked += event.count
        elif event.event_type == "entries_added":
            self.entries_extracted += event.count
            self._update_rps(event.count)
    
    def _update_rps(self, new_entries: int):
        now = datetime.now()
        elapsed = (now - self.last_update).total_seconds()
        if elapsed > 0:
            rps = new_entries / elapsed
            self.rps_samples.append(rps)
            if len(self.rps_samples) > 10: self.rps_samples.pop(0)
        self.last_update = now
    
    @property
    def avg_rps(self) -> float:
        return sum(self.rps_samples) / len(self.rps_samples) if self.rps_samples else 0.0

def generate_dashboard(stats: ScrapeStats, config_name: str) -> Table:
    elapsed = datetime.now() - stats.start_time
    table = Table(title=f"🚀 Glider Scraper: {config_name}")
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="magenta", width=20)
    
    table.add_row("⏱️  Elapsed Time", str(elapsed).split('.')[0])
    table.add_row("✅ Successful Pages", str(stats.success))
    table.add_row("❌ Failed Pages", f"[red]{stats.failed}[/red]")
    table.add_row("⏭️  Skipped", str(stats.skipped))
    table.add_row("🚫 Blocked", f"[yellow]{stats.blocked}[/yellow]")
    table.add_row("📊 Total Entries", f"[bold green]{stats.entries_extracted}[/bold green]")
    table.add_row("⚡ Avg Entries/sec", f"{stats.avg_rps:.2f}")
    return table

def setup_logging():
    logger.remove()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / "glider.log",
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module} - {message}"
    )

async def main_async(config: ScraperConfig):
    stats = ScrapeStats()
    temp_file = Path("data") / "temp_stream.jsonl"
    temp_file.parent.mkdir(exist_ok=True)
    
    # Ensure fresh start for temp file if needed, 
    # though appending allows resume if logic supports it. 
    # Here we clear for safety unless resume logic is strictly defined.
    if temp_file.exists(): 
        temp_file.unlink()

    async def incremental_writer(data_chunk: dict):
        async with aiofiles.open(temp_file, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(data_chunk, ensure_ascii=False) + "\n")
            await f.flush()

    engine = ScraperEngine(
        config, 
        output_callback=incremental_writer,
        stats_callback=stats.update
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
            
    return temp_file

@app.command()
def scrape(config_path: str):
    setup_logging()
    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config not found: {config_path}[/red]")
        return

    try:
        with open(path, 'r') as f:
            config = ScraperConfig(**json.load(f))
    except Exception as e:
        console.print(f"[red]Invalid Config: {e}[/red]")
        return

    try:
        temp_file = asyncio.run(main_async(config))
        
        # Post-process using streaming export (Fixed Memory Issue)
        if temp_file.exists() and temp_file.stat().st_size > 0:
            console.print("[cyan]📦 Finalizing data export...[/cyan]")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"{config.name.replace(' ', '_').lower()}_{timestamp}"
            
            output_dir = Path("data")
            convert_to_json(temp_file, output_dir / f"{base_filename}.json")
            convert_to_csv(temp_file, output_dir / f"{base_filename}.csv")
            
            temp_file.unlink() # Cleanup
            console.print("[green]✨ Done![/green]")
        else:
            console.print("[yellow]⚠️ No data was extracted.[/yellow]")

    except KeyboardInterrupt:
        console.print("[yellow]⚠️ Interrupted. Attempting to save captured data...[/yellow]")
        temp_file = Path("data") / "temp_stream.jsonl"
        if temp_file.exists():
             convert_to_json(temp_file, Path("data") / "interrupted_data.json")
    except Exception as e:
        logger.exception(f"Fatal: {e}")
        console.print("[red]Fatal Error. Check logs.[/red]")

if __name__ == "__main__":
    app()