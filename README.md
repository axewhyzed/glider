# 🚀 Glider: The Stealthy, Async Scraping Engine

**Glider** is a high-performance, configuration-driven web scraping framework designed for the modern web. It bridges the gap between simple scripts and enterprise-grade extraction tools.

Built on **Python 3.11+**, it leverages **AsyncIO**, **Playwright**, and **Curl_CFFI** to provide a hybrid scraping engine that is fast, stealthy, and scalable.

---

## ✨ Key Features

### 🛡️ **Stealth & Anti-Detection**
* **Hybrid Engine:** Dynamically switches between `curl_cffi` (TLS fingerprint spoofing) and `Playwright` (real browser).
* **Browser Stealth:** Integrates `playwright-stealth` to mask automation signals (WebDriver flags, permissions, etc.).
* **Impersonation:** Rotates between real browser fingerprints (Chrome 110/120, Safari, Edge) to evade TLS blocking.

### ⚡ **Performance & Scalability**
* **Fully Async:** Built on `asyncio` for non-blocking execution.
* **Parallel List Mode:** Scrape thousands of URLs concurrently with semaphore-controlled throttling.
* **Smart Rate Limiting:** Token-bucket rate limiting prevents IP bans while maximizing throughput.
* **Lazy Parsing:** Uses `selectolax` (fast CSS) by default and lazy-loads `lxml` (XPath) only when needed to save memory.

### 🔧 **Robust & Reliable**
* **Resilience:** Automatic retries with exponential backoff for network failures and 5xx errors.
* **Thread-Safe:** Prevents data corruption during parallel execution using `asyncio.Lock`.
* **Cross-Platform:** Runs smoothly on Windows, macOS, and Linux (Docker-ready).

### 📊 **Data Intelligence**
* **Smart Export:** Automatically detects and flattens nested data for clean CSV/JSON exports.
* **Validation:** Ensures output data integrity before saving.
* **Deduplication:** Hash-based deduplication prevents duplicate records.

---

## 🛠️ Installation & Setup

Follow these steps to set up the environment from scratch.

### 1. Prerequisites
* Python 3.9 or higher
* Git

### 2. Clone the Repository
```bash
git clone https://github.com/axewhyzed/glider.git
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

### 5. Install Browsers

Glider uses Playwright for dynamic sites. You must install the browser binaries.

```bash
playwright install chromium

```

---

## 🚀 Quick Start

Glider is controlled entirely by JSON configuration files located in the `configs/` folder.

### Run a Scrape

To start the scraper, simply point it to a config file:

```bash
# Example: Scraping a static site (Books to Scrape)
python main.py configs/books_example.json

# Example: Scraping a dynamic site with JS (Quotes to Scrape)
python main.py configs/quotes_js.json

```

### Output

* **Logs:** Detailed execution logs are saved to `logs/glider.log`.
* **Data:** Extracted data is saved to `data/<config_name>_<timestamp>.json` and `.csv`.

---

## ⚙️ Configuration Guide

Create a new JSON file in `configs/` to scrape a new site.

### Key Configuration Fields

| Field | Description | Default |
| --- | --- | --- |
| `mode` | `pagination` (follow "Next" buttons) or `list` (parallel URLs). | `pagination` |
| `start_urls` | List of URLs to scrape in `list` mode. | `[]` |
| `base_url` | Starting URL for `pagination` mode. | Required |
| `concurrency` | Number of simultaneous requests (List Mode). | `2` |
| `rate_limit` | Max requests per second. | `5` |
| `use_playwright` | Set to `true` to use a real browser (JS rendering). | `false` |
| `min_delay` | Minimum sleep time (seconds) between requests. | `1` |

### Example Config (`configs/example.json`)

```json
{
  "name": "HackerNews Config",
  "base_url": "[https://news.ycombinator.com/](https://news.ycombinator.com/)",
  "mode": "pagination",
  "rate_limit": 2,
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

We use `pytest` to ensure core functionality works correctly.

```bash
# Run all tests
pytest

# Run with detailed output
pytest -v

```

### Updating Requirements

If you add new libraries to the project, update the dependency file with:

```bash
# Freeze current environment to requirements.txt
pip freeze > requirements.txt

```

---

## 📂 Project Structure

```text
glider/
├── configs/            # JSON configuration files
├── data/               # Exported data (JSON/CSV)
├── engine/             # Core logic
│   ├── resolver.py     # HTML Parsing (Selectolax/LXML)
│   ├── schemas.py      # Pydantic Models
│   ├── scraper.py      # Main Async Engine
│   └── utils.py        # Helpers & Transformers
├── logs/               # Execution logs
├── tests/              # Unit tests
├── main.py             # CLI Entry point
├── pytest.ini          # Test configuration
└── requirements.txt    # Project dependencies

```

---

## 📝 License

Distributed under the MIT License. See `LICENSE` for more information.