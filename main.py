import typer
import json
from pathlib import Path
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from colorama import init, Fore

# Initialize colors
init(autoreset=True)

app = typer.Typer()

@app.command()
def scrape(config_path: str):
    """
    Run the Glider scraper using a JSON config file.
    """
    path = Path(config_path)
    
    # 1. Validate File Existence
    if not path.exists():
        print(Fore.RED + f"❌ Config file not found: {config_path}")
        return

    # 2. Load & Validate Schema (Strict Mode)
    try:
        with open(path, 'r') as f:
            raw_data = json.load(f)
        
        # This checks types, enums, and required fields instantly
        config = ScraperConfig(**raw_data)
        print(Fore.GREEN + f"✅ Configuration validated: {config.name}")
        
    except Exception as e:
        print(Fore.RED + f"❌ Schema Validation Error:\n{e}")
        return

    # 3. Run Engine
    engine = ScraperEngine(config)
    result = engine.run()
    
    # 4. Output Result
    print(Fore.CYAN + "\n--- Extracted Data ---")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    app()