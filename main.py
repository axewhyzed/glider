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
from rich.layout import Layout
from rich.panel import Panel
from rich.console import Console
from rich.table import Table

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

def create_layout() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3)
    )
    return layout

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
    # Console logs simplified for Dashboard compatibility
    logger.add(
        sys.stderr,
        format="<level>{message}</level>",
        level="INFO"
    )
    # Detailed File Logs
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
            all_keys = set()
            for item in flat_items:
                all_keys.update(item.keys())
            fieldnames = sorted(list(all_keys))
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flat_items)

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
        return

    # Initialize Stats & Temp File
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
    
    # Run with Rich Dashboard
    with Live(generate_dashboard(stats, config.name), refresh_per_second=4) as live:
        
        async def run_wrapper():
            while True:
                live.update(generate_dashboard(stats, config.name))
                await asyncio.sleep(0.5)
                # This loop runs until the main task cancels it

        try:
            # We run the updater in background and wait for engine
            # Note: A cleaner implementation would be integrating Live into the loop,
            # but this works for a simple dashboard.
            loop = asyncio.get_event_loop()
            
            # Since run() is blocking in the async sense (it awaits), 
            # we need to periodically update UI manually inside callbacks or use a wrapper.
            # Here, the stats_callback updates state, and Live auto-refreshes.
            
            result = asyncio.run(engine.run())
            
            save_to_file(result, config.name)
            if temp_file.exists(): temp_file.unlink()
            
            console.print(f"[bold green]Scrape Completed Successfully![/bold green]")
            
        except KeyboardInterrupt:
            console.print("[bold yellow]Scrape interrupted. Partial data saved.[/bold yellow]")
        except Exception as e:
            logger.exception(f"Fatal Error: {e}")

if __name__ == "__main__":
    app()