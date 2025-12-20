import sys
import typer
import json
import csv
import asyncio
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

def validate_data(data: dict, config: ScraperConfig):
    for field in config.fields:
        if field.name not in data:
            logger.warning(f"⚠️ Validation Warning: Missing field '{field.name}' in output.")

def save_to_file(data: dict, config: ScraperConfig):
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = config.name.replace(" ", "_").lower()
    base_filename = f"{safe_name}_{timestamp}"

    # Save JSON
    json_path = output_dir / f"{base_filename}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.success(f"JSON saved to: {json_path}")

    # Save CSV with flattening
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
            keys = flat_items[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(flat_items)
            logger.success(f"CSV saved to:  {csv_path} (Source: '{best_key}')")
    else:
        logger.warning("Skipping CSV: No suitable list found.")

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

    engine = ScraperEngine(config)
    try:
        result = asyncio.run(engine.run())
        validate_data(result, config)
        save_to_file(result, config)
    except KeyboardInterrupt:
        logger.warning("Scrape interrupted by user.")
    except Exception as e:
        logger.exception(f"Fatal Error: {e}")

if __name__ == "__main__":
    app()