# 🚀 Glider: The Professional Local Scraping Framework

**Glider** is a high-performance, configuration-driven web scraping framework designed for the modern web. It bridges the gap between simple Python scripts and enterprise-grade extraction tools.

Built on **Python 3.11+**, it leverages **AsyncIO**, **Playwright**, and **Curl_CFFI** to provide a hybrid scraping engine that is fast, stealthy, and scalable.

---

## ✨ Key Features

### 🛡️ **Stealth & Anti-Detection**
* **Hybrid Engine:** Dynamically switches between `curl_cffi` (for speed/TLS fingerprint spoofing) and `Playwright` (for real browser execution).
* **Browser Stealth:** Integrates `playwright-stealth` to mask automation signals (WebDriver flags, permissions, etc.).
* **Identity Rotation:**
    * **TLS Fingerprints:** Rotates JA3 signatures (Chrome, Edge, Safari) to bypass Cloudflare.
    * **User-Agents:** Rotates HTTP headers per session to match the browser profile.

### 🎮 **Advanced Browser Interactions (v2.5)**
* **Automated UI Actions:** Define sequences to Click, Scroll, Type, or Wait before scraping (e.g., clicking "Load More", filling search bars).
* **Smart Waits:** Handles dynamic AJAX loading seamlessly.

### 📊 **Observability & Reliability**
* **Live Dashboard:** Real-time terminal UI showing RPS, success/failure counts, and blocks.
* **Checkpointing:** Automatically saves state to SQLite. Interrupt a 50k page scrape and resume exactly where you left off.
* **Crash-Proof Writes:** Streams data to disk (`temp_stream.jsonl`) line-by-line. Zero data loss guarantee.
* **Ethical Compliance:** Built-in `robots.txt` parser to respect site policies.

### ⚡ **Performance**
* **Fully Async:** Built on `asyncio` for non-blocking I/O.
* **Parallel List Mode:** Scrape thousands of URLs concurrently with semaphore-controlled throttling.
* **Lazy Parsing:** Uses `selectolax` (fast CSS) by default and lazy-loads `lxml` (XPath) only when needed to save memory.

---

## 🛠️ Installation & Setup

Follow these steps to set up the environment from scratch.

### 1. Prerequisites
* Python 3.9 or higher
* Git

### 2. Clone the Repository
```bash
git clone [https://github.com/axewhyzed/glider.git](https://github.com/axewhyzed/glider.git)
cd glider

```

### 3. Initialize Virtual Environment

It is highly recommended to use a virtual environment to manage dependencies.

**Windows:**

```powershell
python -m venv venv
.\venv\Scripts\activate

```

**macOS / Linux:**

```bash
python3 -m venv venv
source venv/bin/activate

```

### 4. Install Dependencies

Install all required Python packages.

```bash
pip install -r requirements.txt

```

> **⚠️ Important Note on Encoding:**
> Ensure your `requirements.txt` file is saved with **UTF-8 encoding**. If you encounter installation errors on Windows regarding "charmap" or "encoding", verify the file format.

> **ℹ️ Note on Windows Dependencies:**
> The `requirements.txt` includes `win32-setctime`. This is installed **conditionally** only on Windows systems (via `; sys_platform == "win32"`). Linux/macOS users can install without issues.

### 5. Install Browsers

Glider uses Playwright for dynamic sites. You must install the browser binaries.

```bash
playwright install chromium

```

---

## 🚀 Quick Start

Glider is controlled entirely by JSON configuration files located in the `configs/` folder.

### Run a Scrape

To start the scraper, simply point the CLI to a config file:

```bash
# Example: Scraping a static site (Books to Scrape)
python main.py configs/books_example.json

# Example: Scraping a dynamic site with JS (Quotes to Scrape)
python main.py configs/quotes_js.json

```

### Output

* **Console:** Live Dashboard showing real-time stats.
* **Logs:** Detailed execution logs are saved to `logs/glider.log`.
* **Data:** Extracted data is saved to `data/<config_name>_<timestamp>.json` and `.csv`.

---

## ⚙️ Configuration Guide

Create a new JSON file in `configs/` to scrape a new site.

### Key Configuration Fields

| Field | Description | Default |
| --- | --- | --- |
| `name` | Name of the project (used for filenames). | Required |
| `base_url` | Starting URL for `pagination` mode. | Required |
| `mode` | `pagination` (depth-first) or `list` (breadth-first). | `pagination` |
| `start_urls` | List of URLs to scrape in `list` mode. | `[]` |
| `concurrency` | Number of simultaneous requests (List Mode). | `2` |
| `rate_limit` | Max requests per second. | `5` |
| `use_playwright` | Set to `true` to use a real browser (JS rendering). | `false` |
| `proxies` | List of proxy URLs for rotation. | `[]` |

### Browser Interactions (New in v2.5)

For sites requiring user action before data appears, add the `interactions` list:

```json
"use_playwright": true,
"interactions": [
  { "type": "fill", "selector": "#search_bar", "value": "gaming laptops" },
  { "type": "click", "selector": "button.search-icon" },
  { "type": "wait", "duration": 2000 },
  { "type": "scroll" }
]

```

### Full Example Config (`configs/news.json`)

```json
{
  "name": "HackerNews Config",
  "base_url": "[https://news.ycombinator.com/](https://news.ycombinator.com/)",
  "mode": "pagination",
  "rate_limit": 2,
  "respect_robots_txt": true,
  "use_checkpointing": true,
  "fields": [
    {
      "name": "articles",
      "is_list": true,
      "selectors": [{"type": "css", "value": "tr.athing"}],
      "children": [
        {
          "name": "title",
          "selectors": [{"type": "css", "value": "span.titleline > a"}]
        },
        {
          "name": "rank",
          "selectors": [{"type": "css", "value": "span.rank"}],
          "transformers": [{"name": "to_int"}]
        }
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "a.moreLink"},
    "max_pages": 3
  }
}

```

---

## 🧪 Development & Testing

### Running Tests

We use `pytest` to ensure core functionality works correctly (parsing logic, transformers, etc.).

```bash
# Run all tests
pytest

# Run with detailed output
pytest -v

```

### Updating Requirements

If you add new libraries to the project during development, please update the dependency file to keep the environment reproducible.

```bash
# Freeze current environment to requirements.txt
pip freeze > requirements.txt

```

**Note:** After running `pip freeze`, manually verify that `win32-setctime` retains its conditional marker: `win32-setctime==1.1.0 ; sys_platform == "win32"`. Standard `pip freeze` might strip this.

---

## 📂 Project Structure

```text
glider/
├── configs/            # JSON configuration files (recipes)
├── data/               # Exported data & Checkpoint DB
├── engine/             # Core logic
│   ├── scraper.py      # Main Async Engine & Interaction Handler
│   ├── resolver.py     # Hybrid Parser (Selectolax/LXML)
│   ├── checkpoint.py   # SQLite State Manager
│   ├── schemas.py      # Pydantic Configuration Models
│   └── utils.py        # Helpers & Transformers
├── logs/               # Rotating Execution logs
├── tests/              # Unit tests
├── main.py             # CLI Entry point & Live Dashboard
├── pytest.ini          # Test configuration
└── requirements.txt    # Project dependencies

```

---

## ⚖️ Legal & Ethical Notice

**Disclaimer:** Web scraping may be subject to legal regulations (e.g., GDPR, CCPA, CFAA).

1. **Public Data Only:** This tool is designed for extracting publicly available data.
2. **Respect the Server:** Do not overload websites. Use the `rate_limit` and `min_delay` features.
3. **Robots.txt:** Use `"respect_robots_txt": true` to adhere to site policies automatically.

The authors require that this software be used in accordance with all applicable laws and website terms of service.

---

## 📝 License

Distributed under the MIT License.