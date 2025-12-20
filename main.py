import sys
import typer
import json
import csv
import asyncio
import aiofiles
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Dict, Any

# Rich UI Imports
from rich.live import Live
from rich.table import Table
from rich.console import Console

from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from engine.utils import flatten_dict

app = typer.Typer()
console = Console()

class ScrapeStats:
    """Tracks scraping metrics for the dashboard."""
    def __init__(self):
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.blocked = 0
        self.start_time = datetime.now()

    def update(self, status: str):
        if status == "success":
            self.success += 1
        elif status == "error":
            self.failed += 1
        elif status == "skipped":
            self.skipped += 1
        elif status == "blocked":
            self.blocked += 1

def generate_dashboard(stats: ScrapeStats, config_name: str) -> Table:
    """Generates the statistics table."""
    elapsed = datetime.now() - stats.start_time
    table = Table(title=f"🚀 Glider Scraper: {config_name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("Elapsed Time", str(elapsed).split('.')[0])
    table.add_row("Successful Pages", str(stats.success))
    table.add_row("Failed Pages", f"[red]{stats.failed}[/red]")
    table.add_row("Skipped (Checkpointed)", str(stats.skipped))
    table.add_row("Blocked (Robots.txt)", f"[yellow]{stats.blocked}[/yellow]")
    
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
            # Fix: Collect ALL keys from ALL items to handle heterogeneous data
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
        async with aiofiles.open(temp_file, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(data_chunk, ensure_ascii=False) + "\n")

    def stats_updater(status: str):
        stats.update(status)

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