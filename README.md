# 🚀 Glider: The Professional Local Scraping Framework

**Glider** is a high-performance, configuration-driven web scraping framework designed for the modern web. It bridges the gap between simple Python scripts and enterprise-grade extraction tools.

Built on **Python 3.9+**, it leverages **AsyncIO**, **Playwright**, and **curl_cffi** to provide a hybrid scraping engine that is fast, stealthy, and scalable — all driven by plain JSON configuration files, no coding required.

---

## ✨ Key Features

### 🛡️ Stealth & Anti-Detection
* **Hybrid Engine:** Choose between `curl_cffi` (speed + TLS fingerprint spoofing) or Playwright (full real-browser execution) per config.
* **Browser Stealth:** Integrates `playwright-stealth` to mask automation signals (WebDriver flags, permissions, etc.).
* **Identity Rotation:**
  * **TLS Fingerprints:** Rotates JA3 signatures (Chrome, Edge, Safari) to bypass Cloudflare and similar protections.
  * **User-Agents:** Rotates HTTP `User-Agent` headers per request via `fake-useragent`.
  * **Proxy Rotation:** Built-in round-robin proxy cycling with per-request switching.

### 🔐 Authentication & API Support
* **OAuth 2.0 Password Flow:** Automatic token acquisition and refresh with expiry tracking; tokens refreshed 60 s before expiry.
* **Bearer Token Injection:** Static bearer tokens loaded from config and injected into every request header.
* **JSON API Scraping:** Native support for REST APIs using JSONPath selectors.
* **Cookie Persistence:** Load and inject session cookies from a JSON file into both curl_cffi and Playwright sessions.
* **Proxy-Safe Authentication:** Auth requests respect the proxy pool to prevent IP leaks.

### 🔗 Recursive Data Linking
* **Follow Links Automatically:** Extract nested data by following extracted URLs to child pages.
* **Parent-Child Tracking:** Automatically injects `_source_url` and `_parent_url` into every child record.
* **Rate-Limited Recursion:** Child page requests obey the same global rate limiter as parent pages.
* **Depth Control:** Configurable `max_nested_urls` cap prevents runaway recursion.
* **Checkpoint Integration:** Nested URLs are checkpointed and de-duplicated just like top-level URLs.

### 🎮 Advanced Browser Interactions
* **7 Interaction Types:** `click`, `fill`, `scroll`, `wait`, `press`, `hover`, `key` — composable into sequences.
* **Smart Waits:** Wait for specific CSS selectors to appear before scraping.
* **Retry Logic:** Each interaction automatically retried once before failing gracefully.
* **Context Rotation:** Browser context recycled every 50 requests to prevent memory leaks.

### 📊 Observability & Reliability
* **Live Dashboard:** Real-time terminal UI (Rich) showing elapsed time, pages, failures, blocks, total entries, and entries/sec.
* **Checkpointing:** SQLite-backed state manager. Interrupt a 50 k-page scrape and resume exactly where you left off.
* **Crash-Proof Streaming Writes:** Data streamed line-by-line to `temp_stream.jsonl` before final export. Zero data loss on crash.
* **Micro-Batching:** Pending records flushed every 10 items; remaining records flushed on shutdown.
* **Ethical Compliance:** Built-in `robots.txt` parser respects site policies when enabled.
* **Debug Snapshots:** Failed pages auto-saved to `debug/` as HTML for post-mortem inspection.
* **Rotating Logs:** `loguru`-powered structured logs with 5 MB rotation and 7-day retention.

### ⚡ Performance
* **Fully Async:** Built on `asyncio` with no blocking I/O on the hot path.
* **Parallel List Mode:** Scrape thousands of independent URLs concurrently; concurrency level is configurable.
* **Memory-Efficient Deduplication:** Pure-Python Bloom filter (persistable to disk) with configurable capacity and error rate. Negligible memory cost regardless of dataset size.
* **Streaming Export:** JSON and CSV written in two streaming passes — no full dataset loaded into memory.
* **HTML Parsing:** Uses `lxml` with `cssselect` for both CSS and XPath selectors.

---

## 🛠️ Installation & Setup

### 1. Prerequisites
* Python 3.10 or higher
* Git

### 2. Clone the Repository
```bash
git clone https://github.com/axewhyzed/glider.git
cd glider
```

### 3. Create a Virtual Environment

```bash
# macOS / Linux
python3 -m venv venv
source venv/bin/activate

# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\activate
```

### 4. Install

```bash
# Core dependencies (installable package + console script)
pip install -e .

# Optional browser support (for "use_playwright": true)
pip install -e ".[browser]"

# Development dependencies (tests)
pip install -r requirements-dev.txt
```

### 5. Install Playwright Browsers

Required only if you plan to use `"use_playwright": true` in any config:

```bash
playwright install chromium
```

### Security defaults

- Same-origin traversal by default; cross-origin links require `url_policy.allow_external_urls`.
- Private/local network targets are blocked (`url_policy.block_private_networks`, `resolve_dns`).
- TLS verification is on; `browser.ignore_https_errors` is `false` by default.
- Sensitive headers and cookies are scoped to their origin and stripped cross-origin.
- The run manifest stores a redacted copy of the config.

---

## 🚀 Quick Start

Glider is controlled entirely by JSON configuration files. Several ready-to-run examples are in the `configs/` folder.

### Install

```bash
pip install -e .            # core
pip install -e ".[browser]" # optional: Playwright browser support
playwright install chromium # only if you use "use_playwright": true
```

### Run a Scrape

```bash
# Validate a config (no network, structured diagnostics)
glider validate configs/books_example.json

# Preview one page (dry extraction, writes nothing)
glider preview configs/hacker_news.json

# Run a full crawl in an isolated, resumable run directory
glider scrape configs/books_example.json
glider scrape configs/reddit.json --limit 3 --output-dir data
glider scrape configs/books_example.json --resume <run_id>
```

`python main.py <command> ...` works identically if you prefer not to install.

### What Gets Created

| Path | Description |
|---|---|
| `<output-dir>/<name>/runs/<run_id>/stream.jsonl` | Raw extracted records |
| `<output-dir>/<name>/runs/<run_id>/exports/output.json` | Records as a JSON array |
| `<output-dir>/<name>/runs/<run_id>/exports/output.csv` | Records as flat CSV |
| `<output-dir>/<name>/runs/<run_id>/manifest.json` | Run metadata + config digest + summary |
| `<output-dir>/<name>/runs/<run_id>/checkpoint.sqlite` | Resumable crawl state |
| `<output-dir>/<name>/runs/<run_id>/failures.jsonl` | Per-failure records |
| `<output-dir>/<name>/runs/<run_id>/report.json` | Final operator report |
| `logs/glider.log` | Structured execution log with rotation |

### Interrupting a Scrape

Press **Ctrl+C** at any time. Glider will:
1. Flush buffered records to the run's `stream.jsonl` and export partial output.
2. Close all browser contexts and HTTP sessions cleanly.
3. Mark the run `cancelled` in `manifest.json` (artifacts preserved for resume).
4. Print a resume command.

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md) for run directories, resume, retry policy, URL policy, and failure semantics.

---

## ⚙️ Configuration Reference

All scraper behaviour is controlled by a single JSON file. See [`docs/CONFIG_REFERENCE.md`](docs/CONFIG_REFERENCE.md) for the complete field-by-field reference.

### Core Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | **Required** | Project name; used for output filenames and checkpoint DB. |
| `base_url` | URL | Required for `pagination` mode | Starting URL. |
| `mode` | `"pagination"` \| `"list"` | `"pagination"` | `pagination`: follows next-page links sequentially. `list`: scrapes a fixed list of URLs in parallel. |
| `start_urls` | list of URLs | `[]` | Required when `mode` is `"list"`. |
| `response_type` | `"html"` \| `"json"` | `"html"` | Parse response as HTML or as a JSON API response. |
| `use_playwright` | bool | `false` | Use a real Chromium browser instead of curl_cffi. Required for JavaScript-heavy sites. |
| `concurrency` | int ≥ 1 | `2` | Max parallel workers. Applies to `list` mode only. |
| `rate_limit` | int ≥ 1 | `5` | Max requests per second (global, across all workers). |
| `request_timeout` | int | `15` | HTTP request timeout in seconds (curl_cffi mode). |
| `min_delay` | float | `1.0` | Minimum random delay (seconds) between pagination page fetches. |
| `max_delay` | float | `3.0` | Maximum random delay (seconds) between pagination page fetches. |
| `proxies` | list of strings | `null` | Proxy URLs cycled round-robin (e.g. `"http://user:pass@host:port"`). |
| `headers` | object | `null` | Custom HTTP headers added to every request. |
| `cookies_file` | string | `null` | Path to a JSON file containing cookies as `{"name": "value"}`. |
| `wait_for_selector` | string | `null` | CSS selector to wait for before capturing page content (Playwright only). |
| `use_checkpointing` | bool | `false` | Persist visited-URL state to SQLite for crash recovery and resume. |
| `respect_robots_txt` | bool | `false` | Fetch and obey `robots.txt` before scraping. |
| `append_json_suffix` | bool | `false` | When `follow_url` is used with a JSON API, append `.json` to child URLs that don't already end with it. Reddit-specific; leave `false` for all other APIs. |
| `max_nested_urls` | int 1–100 | `5` | Max child URLs followed per parent page when using `follow_url`. |
| `fields` | list | **Required** | Data extraction field definitions (see below). |
| `pagination` | object | `null` | Pagination configuration (see below). |
| `interactions` | list | `[]` | Browser interaction sequence (Playwright only). |
| `authentication` | object | `null` | OAuth 2.0 or bearer token configuration (see below). |
| `max_depth` | int 0–100 | `2` | Maximum nested-follow generations (`follow_url`). |
| `robots_ttl_seconds` | float | `3600.0` | Per-origin robots.txt cache TTL. |
| `url_policy` | object | see below | URL/SSRF policy: `allowed_domains`, `allow_subdomains`, `allow_external_urls`, `allowed_schemes`, `block_private_networks`, `resolve_dns`, `max_redirects`. |
| `retry` | object | see below | Retry policy: `max_attempts`, `base_delay_seconds`, `max_delay_seconds`, `retry_statuses`, `retry_after_cap_seconds`. |
| `browser` | object | see below | Browser safety: `ignore_https_errors`, `context_max_requests`, `proxy_rotation`. |
| `dedup` | object | see below | Dedup policy: `mode` (`none`/`url`/`fields`/`exact_hash`), `capacity`, `error_rate`, `fields`, `exact_capacity`. |
| `validation` | object | see below | Extraction validation: `min_records_per_page`, `required_fields`, `fail_on_empty`. |
| `debug_snapshots` | object | see below | Bounded snapshots: `enabled`, `max_files`, `max_bytes_per_file`, `max_total_bytes`. |

### Fields

Each entry in `fields` describes one piece of data to extract:

```json
{
  "name": "price",
  "selectors": [{"type": "css", "value": "span.price"}],
  "attribute": "data-price",
  "is_list": false,
  "transformers": [{"name": "to_float"}],
  "children": [],
  "follow_url": false,
  "nested_fields": []
}
```

| Key | Description |
|---|---|
| `name` | Output key name. |
| `selector` | Shorthand for a single CSS selector string (converted to `selectors` automatically). |
| `selectors` | List of selector objects tried in order; first that returns results wins. |
| `selectors[].type` | `"css"`, `"xpath"`, `"json"` (JSONPath), or `"regex"`. |
| `selectors[].value` | The selector expression. |
| `attribute` | HTML attribute to extract instead of text content (e.g. `"href"`, `"src"`, `"data-id"`). Case-insensitive. |
| `is_list` | If `true`, collect all matches as an array instead of the first match only. |
| `transformers` | Ordered list of transformers applied to the extracted value. See [Transformers](#transformers). |
| `children` | Nested sub-fields extracted from each matched element (for structured list extraction). |
| `follow_url` | If `true`, treat the extracted value(s) as URLs and fetch them, extracting `nested_fields` from each. |
| `nested_fields` | Field definitions applied to each followed child page. Required when `follow_url: true`. |

### Selectors at a glance

| Type | Syntax example | Notes |
|---|---|---|
| `css` | `"div.product h3 a"` | Standard CSS selectors via lxml+cssselect. |
| `xpath` | `"//span[@class='price']"` | Full XPath 1.0 via lxml. |
| `json` | `"data.children[*].data.title"` | JSONPath via jsonpath-ng. Used with `response_type: "json"`. |
| `regex` | `"Order #(\\d+)"` | Applied to the raw response string; returns first capture group or full match. |

### Transformers

| Name | Args | Description |
|---|---|---|
| `strip` | — | Strips leading/trailing whitespace. |
| `to_float` | optional `[thousands_sep, decimal_sep]` | Converts to float. Strips currency symbols. Pass `[".", ","]` for European `"1.234,56"` format. |
| `to_int` | — | Extracts the first contiguous digit group and converts to int. |
| `regex` | `[pattern]` | Applies regex; returns capture group 1 or full match. Returns `null` on no match. |
| `replace` | `[old, new]` | String replacement. |

Transformers may be written as shorthand strings (`"strip"`) or full objects (`{"name": "to_float", "args": [...]}`):

```json
"transformers": ["strip", {"name": "to_float", "args": [".", ","]}]
```

See [`docs/TRANSFORMERS.md`](docs/TRANSFORMERS.md) for detailed examples.

### Pagination

```json
"pagination": {
  "selector": {"type": "css", "value": "li.next a"},
  "max_pages": 10,
  "query_param": "after"
}
```

| Field | Default | Description |
|---|---|---|
| `selector` | Required | Selector for the next-page element. For HTML: finds the element and extracts its `href`. For JSON APIs: extracts the cursor value. |
| `max_pages` | `5` | Maximum pages to traverse. |
| `query_param` | `"after"` | Query-string parameter name used when the next value is a cursor token (JSON API pagination only). |

### Authentication

**OAuth 2.0 Password Flow:**
```json
"authentication": {
  "type": "oauth_password",
  "token_url": "https://api.example.com/oauth/token",
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "username": "YOUR_USERNAME",
  "password": "YOUR_PASSWORD",
  "scope": "read"
}
```

**Static Bearer Token:**
```json
"authentication": {
  "type": "bearer",
  "client_secret": "YOUR_STATIC_TOKEN"
}
```

### Browser Interactions

Applies only when `use_playwright: true`. Interactions execute before page content is captured.

```json
"interactions": [
  {"type": "fill",   "selector": "#search",        "value": "laptops"},
  {"type": "click",  "selector": "button.search"},
  {"type": "wait",   "duration": 2000},
  {"type": "scroll"},
  {"type": "hover",  "selector": "div.menu"},
  {"type": "press",  "selector": "input.q",        "value": "Enter"},
  {"type": "key",    "value": "Escape"}
]
```

| Type | Required fields | Description |
|---|---|---|
| `click` | `selector` | Click an element. |
| `fill` | `selector`, `value` | Type text into an input field. |
| `scroll` | — | Scroll to the bottom of the page. |
| `wait` | `duration` (ms) | Pause for a fixed number of milliseconds. |
| `hover` | `selector` | Hover the mouse over an element. |
| `press` | `selector`, `value` (key name) | Press a key while focused on an element. |
| `key` | `value` (key name) | Press a keyboard key globally (e.g. `"Escape"`, `"Tab"`). |

### Environment Variable Expansion

Config values may reference environment variables using `${VAR_NAME}` or `$VAR_NAME` syntax. This is the recommended way to keep credentials out of config files:

```json
{
  "authentication": {
    "type": "oauth_password",
    "client_id": "${REDDIT_CLIENT_ID}",
    "client_secret": "${REDDIT_CLIENT_SECRET}",
    "username": "${REDDIT_USERNAME}",
    "password": "${REDDIT_PASSWORD}"
  }
}
```

---

## 📋 Example Configs

### Static HTML Pagination — Books to Scrape

```json
{
  "name": "books_scraper",
  "base_url": "http://books.toscrape.com",
  "mode": "pagination",
  "rate_limit": 10,
  "use_checkpointing": true,
  "fields": [
    {
      "name": "books",
      "selector": "article.product_pod",
      "is_list": true,
      "children": [
        {"name": "title",        "selector": "h3 a",                  "attribute": "title"},
        {"name": "price",        "selector": "p.price_color",         "transformers": ["strip", "to_float"]},
        {"name": "availability", "selector": "p.instock.availability", "transformers": ["strip"]}
      ]
    }
  ],
  "pagination": {"selector": "li.next a", "max_pages": 3}
}
```

### JavaScript Site — Quotes to Scrape (Playwright)

```json
{
  "name": "quotes_js",
  "base_url": "http://quotes.toscrape.com/js/",
  "mode": "pagination",
  "use_playwright": true,
  "wait_for_selector": "div.quote",
  "fields": [
    {
      "name": "quotes",
      "selector": "div.quote",
      "is_list": true,
      "children": [
        {"name": "text",   "selector": "span.text",      "transformers": ["strip"]},
        {"name": "author", "selector": "small.author"},
        {"name": "tags",   "selector": "div.tags a.tag",  "is_list": true}
      ]
    }
  ],
  "pagination": {"selector": "li.next a", "max_pages": 5}
}
```

### JSON API with OAuth — Reddit

```json
{
  "name": "reddit_api",
  "base_url": "https://oauth.reddit.com/r/python/hot",
  "mode": "pagination",
  "response_type": "json",
  "rate_limit": 1,
  "authentication": {
    "type": "oauth_password",
    "token_url": "https://www.reddit.com/api/v1/access_token",
    "client_id": "${REDDIT_CLIENT_ID}",
    "client_secret": "${REDDIT_CLIENT_SECRET}",
    "username": "${REDDIT_USERNAME}",
    "password": "${REDDIT_PASSWORD}"
  },
  "headers": {"User-Agent": "MyBot/1.0"},
  "fields": [
    {
      "name": "posts",
      "is_list": true,
      "selectors": [{"type": "json", "value": "data.children[*].data"}],
      "children": [
        {"name": "title",  "selectors": [{"type": "json", "value": "title"}]},
        {"name": "score",  "selectors": [{"type": "json", "value": "score"}]},
        {"name": "author", "selectors": [{"type": "json", "value": "author"}]},
        {"name": "url",    "selectors": [{"type": "json", "value": "permalink"}]}
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "json", "value": "data.after"},
    "max_pages": 5,
    "query_param": "after"
  }
}
```

### Recursive Link Following

```json
{
  "fields": [
    {
      "name": "post_links",
      "selectors": [{"type": "css", "value": "a.post-title"}],
      "attribute": "href",
      "is_list": true,
      "follow_url": true,
      "nested_fields": [
        {"name": "title",   "selectors": [{"type": "css", "value": "h1.post-title"}]},
        {"name": "content", "selectors": [{"type": "css", "value": "div.post-body"}]},
        {"name": "author",  "selectors": [{"type": "css", "value": "span.author"}]}
      ]
    }
  ]
}
```

Each child record automatically gets `_source_url` (the child page URL) and `_parent_url` (the page that linked to it).

See [`docs/EXAMPLES.md`](docs/EXAMPLES.md) for more complete recipes and [`docs/ATTRIBUTE_EXTRACTION.md`](docs/ATTRIBUTE_EXTRACTION.md) for attribute extraction patterns.

---

## 📂 Project Structure

```text
glider/
├── configs/                    # JSON configuration files (recipes)
│   ├── books_example.json      # Static HTML pagination example
│   ├── quotes_js.json          # Playwright JS-rendered example
│   ├── reddit.json             # Reddit OAuth API example (uses env vars)
│   ├── reddit_unauthenticated.json   # Public Reddit JSON API
│   ├── reddit_followlink.json  # Nested link-following example (append_json_suffix)
│   ├── hacker_news.json        # Hacker News HTML pagination example
│   └── attribute_extraction_example.json
├── data/                       # Output data, checkpoint DBs, bloom filters
├── docs/                       # Extended documentation
│   ├── ATTRIBUTE_EXTRACTION.md
│   ├── CONFIG_REFERENCE.md
│   ├── EXAMPLES.md
│   ├── KNOWN_ISSUES.md
│   └── TRANSFORMERS.md
├── engine/                     # Core library
│   ├── scraper.py              # Main async engine, OAuth handler, worker pool
│   ├── resolver.py             # HTML (lxml) and JSON (jsonpath-ng) parsers
│   ├── checkpoint.py           # SQLite-backed URL state manager
│   ├── schemas.py              # Pydantic v2 config models
│   ├── browser.py              # Playwright browser/context/page lifecycle
│   ├── bloom.py                # Pure-Python persistable Bloom filter
│   └── utils.py                # Transformer pipeline, config loader
├── logs/                       # Rotating execution logs (auto-created)
├── debug/                      # HTML snapshots of failed pages (auto-created)
├── tests/                      # Pytest unit tests (36 tests)
├── main.py                     # CLI entry point & live dashboard
├── CHANGELOG.md                # Detailed version history
├── UPGRADE_GUIDE.md            # Migration guides (v2.5 → v2.6, v2.7 → v2.8)
├── pytest.ini                  # Test configuration
└── requirements.txt            # Python dependencies
```

---

## 🆕 What's New

### v2.8.0 — Production Hardening (April 2026)

#### 🔥 All Remaining Bugs Fixed
* **JSON API pagination now works with shorthand selectors** (`"data.after"` shorthand no longer silently breaks pagination after page 1).
* **Dashboard "Total Records" counts individual items** — a page containing 50 books now shows 50 records, not 1.
* **`page_skipped` event now fires** when the Bloom filter deduplicates a page — the "Skipped" dashboard counter is now accurate.
* **Playwright navigation respects `request_timeout`** — the hardcoded 30-second timeout is replaced by the config value.
* **`wait_for_selector` timeout is now logged** as a warning instead of being silently swallowed.
* **`interactions` without `use_playwright: true` now warns** at startup instead of silently ignoring the config.
* **Interrupted scrapes clean up `temp_stream.jsonl`** after saving partial output.
* **`follow_url` + JSON mode no longer appends `.json` by default** — use the new `append_json_suffix: true` field for Reddit-style APIs.

#### 🆕 New Config Field
* **`append_json_suffix: bool`** (default `false`) — opt-in `.json` suffix appending for Reddit-style follow_url. Previously this was hardcoded to always-on.

#### 🗑️ Removed
* `selectolax` removed from `requirements.txt` (it was listed but never used).

See [`CHANGELOG.md`](CHANGELOG.md) for the complete fix list.

---

### v2.7.1 — Critical Stability Patch (December 2025)

#### 🔥 Critical Fixes
* **Browser Memory Leak Fixed:** Playwright browser contexts now properly closed after each page scrape, preventing unbounded memory growth in long-running jobs.
* **Worker Exception Handling:** Worker exceptions now logged with full stack traces instead of being silently swallowed.
* **Session Cleanup on Auth Failure:** HTTP sessions are properly closed when OAuth token acquisition fails.
* **Bloom Filter Persistence:** Bloom filter format updated to include item count header; legacy format still supported.

#### 🛡️ Security & Safety
* **Proxy Safety:** Auth requests route through the proxy pool to prevent IP leaks on token endpoints.
* **Recursion Safety:** `max_nested_urls` cap enforced to prevent excessive child-page fetching.

#### 🐛 Resolved in v2.7.1
* `Never` type annotation issues in error-handling code paths.
* Race condition in OAuth double-checked locking pattern.
* Cookies not being injected into Playwright contexts correctly.

### v2.7 — Major Feature Release (December 24, 2025)

* **OAuth 2.0 Password Flow** with automatic token refresh.
* **Bearer Token** static auth support.
* **Recursive Data Linking** (`follow_url` + `nested_fields`).
* **JSON API Scraping** with JSONPath selectors and cursor pagination.
* **Cookie file injection** for both curl_cffi and Playwright.
* **Regex selectors** on raw response content.
* **Debug snapshots** — failed pages saved to `debug/`.
* **Smart checkpoint recovery** — in-progress URLs re-queued on restart.

---

## 🧪 Development & Testing

### Running Tests

```bash
# Default suite (no browser, no live network)
venv\Scripts\python.exe -m pytest tests -q

# With Playwright browsers installed
venv\Scripts\python.exe -m pytest tests -m browser
```

The suite covers config schema validation, transformers, resolvers, network policy/SSRF, checkpoint resume, run isolation, recursion/cycles, dedup, output writer, metrics, redaction, CLI exit codes, and operational cancellation/flush.

### Adding Tests

Follow the existing patterns in `tests/`. Mark async tests with `@pytest.mark.asyncio`. Use `tmp_path` for any file I/O. Browser tests require the `browser` marker and `playwright install chromium`; network-dependent rows use the `network` marker (both excluded by default via `pytest.ini`).

### Updating Dependencies

Edit `pyproject.toml` (dependencies / optional-dependencies) for packaging, or the pinned `requirements.txt` / `requirements-dev.txt` for dev installs.

---

## ⚠️ Known Limitations

See [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) for a full list. Key limitations to be aware of:

* **GET only:** Only HTTP GET requests are supported. POST-based pagination or form submission is not implemented.
* **Pagination is sequential:** In `pagination` mode, pages are fetched one at a time regardless of the `concurrency` setting (which only affects `list` mode).
* **`debug_mode` config field is reserved:** The field is accepted in configs but does not yet change any behaviour.
* **`append_json_suffix` is Reddit-specific:** Set `"append_json_suffix": true` only for Reddit-style APIs where child URLs need `.json` appended. Leave `false` for all other JSON APIs.
* **Bloom filter capacity is not configurable via JSON config.** It is hardcoded at 100 000 items. To change it, edit `engine/scraper.py` directly (see [`UPGRADE_GUIDE.md`](UPGRADE_GUIDE.md)).
* **Browser interactions are silently ignored if `use_playwright` is `false`** (a startup warning is logged).
* **CSV nested list fields are pipe-joined strings.** Nested list data loses structure in CSV export; use the JSON output for list-valued fields.

---

## ⚖️ Legal & Ethical Notice

**Disclaimer:** Web scraping may be subject to legal regulations (e.g., GDPR, CCPA, CFAA).

1. **Public Data Only:** This tool is designed for publicly available data.
2. **Respect the Server:** Use `rate_limit` and `min_delay`/`max_delay` to avoid overloading servers.
3. **Robots.txt:** Set `"respect_robots_txt": true` to obey site policies automatically.
4. **API Terms of Service:** When using OAuth, ensure compliance with the API provider's terms.

The authors require that this software be used in accordance with all applicable laws and website terms of service.

---

## 📝 License

Distributed under the MIT License.