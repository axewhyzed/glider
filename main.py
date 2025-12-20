import sys
import typer
import json
import csv
import asyncio
import aiofiles
from datetime import datetime
from pathlib import Path
from loguru import logger
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from engine.utils import flatten_dict

app = typer.Typer()

def setup_logging():
    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
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
    logger.success(f"JSON saved to: {json_path}")

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
            # FIX: Collect ALL keys from ALL items (superset) to prevent missing columns
            all_keys = set()
            for item in flat_items:
                all_keys.update(item.keys())
            
            # Sort keys for consistent column order
            fieldnames = sorted(list(all_keys))
            
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(flat_items)
            logger.success(f"CSV saved to:  {csv_path} (Source: '{best_key}')")
    else:
        logger.warning("Skipping CSV: No suitable list of objects found in output.")

@app.command()
def scrape(config_path: str):
    setup_logging()
    path = Path(config_path)
    
    if not path.exists():
        logger.critical(f"Config file not found: {config_path}")
        return

    try:
        with open(path, 'r') as f:
            raw_data = json.load(f)
        config = ScraperConfig(**raw_data)
        logger.info(f"Loaded config: {config.name}")
    except Exception as e:
        logger.exception(f"Schema Validation Error: {e}")
        return

    # FIX: Incremental Writer
    temp_file = Path("data") / "temp_stream.jsonl"
    temp_file.parent.mkdir(exist_ok=True)

    async def incremental_writer(data_chunk: dict):
        """Callback to write data line-by-line as it arrives."""
        async with aiofiles.open(temp_file, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(data_chunk, ensure_ascii=False) + "\n")

    # Pass callback to engine
    engine = ScraperEngine(config, output_callback=incremental_writer)
    
    try:
        # Clean previous temp file
        if temp_file.exists():
            temp_file.unlink()

        result = asyncio.run(engine.run())
        save_to_file(result, config.name)
        
        # Cleanup temp file on success
        if temp_file.exists():
            temp_file.unlink()
            
    except KeyboardInterrupt:
        logger.warning("Scrape interrupted by user. Partial data in 'data/temp_stream.jsonl'")
    except Exception as e:
        logger.exception(f"Fatal Error: {e}")

if __name__ == "__main__":
    app()