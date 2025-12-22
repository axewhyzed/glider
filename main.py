import sys
import os
import typer
import json
import csv
import asyncio
import aiofiles
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Dict, Any
from dataclasses import dataclass, field
from typing import Literal, Optional

# Rich UI Imports
from rich.live import Live
from rich.table import Table
from rich.console import Console

from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from engine.utils import flatten_dict

app = typer.Typer()
console = Console()

@dataclass
class StatsEvent:
    """Type-safe event for stats updates."""
    event_type: Literal["page_success", "page_error", "page_skipped", "blocked", "entries_added"]
    count: int = 1
    metadata: Optional[Dict[str, Any]] = None

class ScrapeStats:
    """Enhanced stats tracker with RPS calculation."""
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.blocked = 0
        self.entries_extracted = 0
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        self.rps_samples = []  # Rolling window for RPS calculation

    def update(self, event: StatsEvent):
        """Process stats events."""
        if event.event_type == "page_success":
            self.success += event.count
        elif event.event_type == "page_error":
            self.failed += event.count
        elif event.event_type == "page_skipped":
            self.skipped += event.count
        elif event.event_type == "blocked":
            self.blocked += event.count
        elif event.event_type == "entries_added":
            self.entries_extracted += event.count
            self._update_rps(event.count)
    
    def _update_rps(self, new_entries: int):
        """Calculate rolling RPS (requests per second)."""
        now = datetime.now()
        elapsed = (now - self.last_update).total_seconds()
        if elapsed > 0:
            rps = new_entries / elapsed
            self.rps_samples.append(rps)
            # Keep last 10 samples for smoothed average
            if len(self.rps_samples) > 10:
                self.rps_samples.pop(0)
        self.last_update = now
    
    @property
    def avg_rps(self) -> float:
        """Get average RPS from recent samples."""
        return sum(self.rps_samples) / len(self.rps_samples) if self.rps_samples else 0.0

def generate_dashboard(stats: ScrapeStats, config_name: str) -> Table:
    """Enhanced dashboard with RPS and entry count."""
    elapsed = datetime.now() - stats.start_time
    table = Table(title=f"🚀 Glider Scraper: {config_name}")
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Value", style="magenta", width=20)
    
    table.add_row("⏱️  Elapsed Time", str(elapsed).split('.')[0])
    table.add_row("✅ Successful Pages", str(stats.success))
    table.add_row("❌ Failed Pages", f"[red]{stats.failed}[/red]")
    table.add_row("⏭️  Skipped (Checkpoint)", str(stats.skipped))
    table.add_row("🚫 Blocked (Robots)", f"[yellow]{stats.blocked}[/yellow]")
    table.add_row("📊 Total Entries", f"[bold green]{stats.entries_extracted}[/bold green]")
    table.add_row("⚡ Avg Entries/sec", f"{stats.avg_rps:.2f}")
    
    return table

def setup_logging():
    logger.remove()
    # Only log to file to keep dashboard clean
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    logger.add(
        log_dir / "glider.log",
        rotation="5 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {module}:{function}:{line} - {message}"
    )

def save_to_file(data: dict, config_name: str):
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = config_name.replace(" ", "_").lower()
    base_filename = f"{safe_name}_{timestamp}"

    # 1. Save Full JSON
    json_path = output_dir / f"{base_filename}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # 2. Save CSV (Robust Selection)
    # Find the longest list to assume it's the main data table
    best_key = None
    max_len = 0
    for key, value in data.items():
        if isinstance(value, list) and len(value) > max_len:
            if len(value) > 0 and isinstance(value[0], dict):
                best_key = key
                max_len = len(value)
    
    if best_key:
        csv_path = output_dir / f"{base_filename}.csv"
        raw_items = data[best_key]
        flat_items = [flatten_dict(item) for item in raw_items]
        
        if flat_items:
            # Collect ALL keys from ALL items to handle heterogeneous data
            all_keys = set()
            for item in flat_items:
                all_keys.update(item.keys())
            fieldnames = sorted(list(all_keys))
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flat_items)
            console.print(f"   [green]CSV saved to {csv_path}[/green]")

async def main_async(config: ScraperConfig):
    """Async entry point to run scraper and UI concurrently."""
    stats = ScrapeStats()
    temp_file = Path("data") / "temp_stream.jsonl"
    temp_file.parent.mkdir(exist_ok=True)
    if temp_file.exists(): temp_file.unlink()

    async def incremental_writer(data_chunk: dict):
        """Crash-safe incremental writer with fsync."""
        async with aiofiles.open(temp_file, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(data_chunk, ensure_ascii=False) + "\n")
            await f.flush()  # Flush Python buffer
            # Force OS to write to disk for crash safety
            os.fsync(f.fileno())

    def stats_updater(event: StatsEvent):
        """Update stats with event."""
        stats.update(event)

    engine = ScraperEngine(
        config, 
        output_callback=incremental_writer,
        stats_callback=stats_updater
    )
    
    # Run UI and Scraper concurrently
    with Live(generate_dashboard(stats, config.name), refresh_per_second=4) as live:
        
        async def ui_updater():
            while True:
                live.update(generate_dashboard(stats, config.name))
                await asyncio.sleep(0.5)

        # Create the UI task
        ui_task = asyncio.create_task(ui_updater())
        
        try:
            # Run the engine (this blocks until scraping is done)
            result = await engine.run()
        finally:
            # Stop the UI
            ui_task.cancel()
            try:
                await ui_task
            except asyncio.CancelledError:
                pass

    return result, temp_file

@app.command()
def scrape(config_path: str):
    setup_logging()
    path = Path(config_path)
    
    if not path.exists():
        console.print(f"[bold red]Config file not found: {config_path}[/bold red]")
        return

    try:
        with open(path, 'r') as f:
            raw_data = json.load(f)
        config = ScraperConfig(**raw_data)
    except Exception as e:
        logger.exception(f"Schema Validation Error: {e}")
        console.print(f"[bold red]Schema Validation Error:[/bold red] {e}")
        return

    try:
        # Run the async main loop
        result, temp_file = asyncio.run(main_async(config))
        
        save_to_file(result, config.name)
        
        if temp_file.exists(): 
            temp_file.unlink()
        
        console.print(f"[bold green]Scrape Completed Successfully![/bold green]")
            
    except KeyboardInterrupt:
        console.print("[bold yellow]Scrape interrupted. Partial data saved in data/temp_stream.jsonl[/bold yellow]")
    except Exception as e:
        logger.exception(f"Fatal Error: {e}")
        console.print(f"[bold red]Fatal Error:[/bold red] Check logs for details.")

if __name__ == "__main__":
    app()
