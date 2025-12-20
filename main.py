import sys
import typer
import json
import csv
from datetime import datetime
from pathlib import Path
from loguru import logger  # NEW: The Star
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine

app = typer.Typer()

def setup_logging():
    """
    Configures Loguru to write to console (colorful) and file (detailed).
    """
    # 1. Clear default handlers to avoid duplicate logs
    logger.remove()
    
    # 2. Add Console Handler (Clean & Colorful)
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )
    
    # 3. Add File Handler (Detailed with Rotation)
    # Rotates every 5 MB or every day. Retains logs for 1 week.
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

    # Save JSON
    json_path = output_dir / f"{base_filename}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.success(f"JSON saved to: {json_path}")

    # Save CSV
    list_key = None
    for key, value in data.items():
        if isinstance(value, list) and len(value) > 0:
            list_key = key
            break
    
    if list_key:
        csv_path = output_dir / f"{base_filename}.csv"
        items = data[list_key]
        if items and isinstance(items[0], dict):
            keys = items[0].keys()
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(items)
            logger.success(f"CSV saved to:  {csv_path}")
        else:
            logger.warning("Skipping CSV: List items are not dictionaries.")
    else:
        logger.warning("Skipping CSV: No list data found.")

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
        logger.info(f"Loaded config: {config.name} ({config.base_url})")
    except Exception as e:
        logger.exception(f"Schema Validation Error: {e}")
        return

    engine = ScraperEngine(config)
    result = engine.run()
    
    save_to_file(result, config.name)

if __name__ == "__main__":
    app()