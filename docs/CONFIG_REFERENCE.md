# Complete Configuration Reference

This document covers every field that can appear in a Glider JSON configuration file.

---

## Top-Level Fields

### `name` — string · **Required**

Project identifier.  Used as a prefix for all output filenames, the checkpoint database, and the Bloom filter file.

```json
"name": "my_product_scraper"
```

Spaces are converted to underscores in filenames (e.g. `"My Scraper"` → `my_scraper_20250101_120000.json`).

---

### `base_url` — URL string

The starting URL for `pagination` mode.  Required when `mode` is `"pagination"`.

```json
"base_url": "https://example.com/products"
```

---

### `mode` — `"pagination"` | `"list"` · Default: `"pagination"`

Controls how URLs are discovered and processed.

| Value | Behaviour |
|---|---|
| `"pagination"` | Starts at `base_url`, follows the next-page selector repeatedly up to `pagination.max_pages`. Sequential (one page at a time). |
| `"list"` | Processes every URL in `start_urls` in parallel (up to `concurrency` workers). |

---

### `start_urls` — list of URL strings · Default: `[]`

List of URLs to scrape in `list` mode.  Ignored in `pagination` mode.

```json
"start_urls": [
  "https://example.com/page/1",
  "https://example.com/page/2"
]
```

---

### `response_type` — `"html"` | `"json"` · Default: `"html"`

Controls how the HTTP response body is parsed.

| Value | Parser used | Selector types available |
|---|---|---|
| `"html"` | lxml (via cssselect + XPath) | `css`, `xpath`, `regex` |
| `"json"` | jsonpath-ng | `json`, `regex` |

> **Note:** When using `response_type: "json"` with `use_playwright: true`, Playwright returns the full HTML page (including `<html>` wrapper) rather than raw JSON. This combination may not parse correctly for most APIs.

---

### `use_playwright` — bool · Default: `false`

Set to `true` to launch a headless Chromium browser (Playwright) instead of using `curl_cffi`.

Use when the target site:
* Requires JavaScript execution to render content.
* Uses dynamic AJAX loading.
* Detects and blocks non-browser clients.

> Requires `playwright install chromium` to be run once before use.

---

### `debug_mode` — bool · Default: `false`

**Reserved field.** Accepted in configs but does not currently change any runtime behaviour. Intended for future use (verbose selector tracing, etc.).

---

### `concurrency` — int ≥ 1 · Default: `2`

Maximum number of concurrent worker coroutines.  Applies only to `list` mode.  In `pagination` mode pages are always fetched sequentially.

---

### `rate_limit` — int ≥ 1 · Default: `5`

Maximum number of HTTP requests per second across all workers (enforced globally by an `aiolimiter` token-bucket).

---

### `request_timeout` — int · Default: `15`

HTTP request timeout in seconds when using `curl_cffi`.  Does not affect Playwright (Playwright's navigation timeout is fixed at 30 s).

---

### `min_delay` — float · Default: `1.0`

Minimum random delay in seconds inserted between page fetches in `pagination` mode.  Set to `0` to disable.

---

### `max_delay` — float · Default: `3.0`

Maximum random delay in seconds inserted between page fetches in `pagination` mode.  Must be ≥ `min_delay`.

---

### `proxies` — list of strings | null · Default: `null`

List of proxy URLs to cycle through round-robin style.  Each entry is a full proxy URL:

```json
"proxies": [
  "http://user:pass@10.0.0.1:8080",
  "socks5://127.0.0.1:9050"
]
```

Both HTTP and SOCKS5 proxies are supported (via `curl_cffi`).  Playwright mode only accepts HTTP proxies (passed as `--proxy-server` launch argument).

---

### `headers` — object | null · Default: `null`

Custom HTTP headers merged into every request.  A randomly-rotated `User-Agent` is always appended after these; to pin a specific user-agent include it here.

```json
"headers": {
  "User-Agent": "MyBot/1.0 (contact@example.com)",
  "Accept-Language": "en-US"
}
```

---

### `cookies_file` — string | null · Default: `null`

Path to a JSON file containing session cookies as a flat key-value object:

```json
{
  "session_id": "abc123",
  "csrf_token": "xyz789"
}
```

Cookies are loaded at startup and injected into both `curl_cffi` sessions and Playwright browser contexts.

---

### `wait_for_selector` — string | null · Default: `null`

CSS selector that must be present on the page before content is captured.  Playwright only.  If the selector does not appear within 5 seconds, scraping continues anyway (graceful degradation).

```json
"wait_for_selector": "div.product-list"
```

---

### `use_checkpointing` — bool · Default: `false`

When `true`, visited URLs are persisted to a SQLite database (`data/<name>.db`) so that interrupted scrapes can be resumed automatically on the next run.

> Recommended for any scrape involving more than ~100 pages.

---

### `respect_robots_txt` — bool · Default: `false`

When `true`, Glider fetches `robots.txt` from the root of `base_url` at startup and skips any URL disallowed for `*`.

---

### `max_nested_urls` — int 1–100 · Default: `5`

Maximum number of child URLs to follow per parent page when a field has `follow_url: true`.  Acts as a safety cap against unexpectedly large link lists.

---

### `interactions` — list | null · Default: `[]`

Sequence of browser actions to perform before capturing page content.  Playwright only; silently ignored in `curl_cffi` mode.

See the [Interactions section](#interactions-detail) below.

---

### `authentication` — object | null · Default: `null`

OAuth 2.0 or static bearer token configuration.  See the [Authentication section](#authentication-detail) below.

---

### `fields` — list · **Required**

List of `DataField` objects defining what data to extract.  See the [Fields section](#fields-detail) below.

---

### `pagination` — object | null · Default: `null`

Pagination configuration.  See the [Pagination section](#pagination-detail) below.

---

## Fields Detail

### DataField object

```json
{
  "name": "price",
  "selector": "span.price",
  "selectors": [
    {"type": "css", "value": "span.price"},
    {"type": "xpath", "value": "//span[contains(@class,'price')]"}
  ],
  "attribute": "data-price",
  "is_list": false,
  "transformers": ["strip", {"name": "to_float"}],
  "children": [],
  "follow_url": false,
  "nested_fields": []
}
```

#### `name` — string · **Required**

Key used in the output JSON/CSV for this field.

#### `selector` — string (shorthand)

A plain CSS selector string.  Equivalent to `"selectors": [{"type": "css", "value": "<selector>"}]`.  Merged into `selectors` automatically at validation time.

#### `selectors` — list of Selector objects

Ordered list of selectors tried in sequence.  The first selector that returns at least one match is used; subsequent selectors are skipped.

**Selector object:**

```json
{"type": "css",   "value": "div.price"}
{"type": "xpath", "value": "//div[@class='price']"}
{"type": "json",  "value": "data.price"}
{"type": "regex", "value": "Price: ([\\d.]+)"}
```

| Type | Context | Description |
|---|---|---|
| `css` | HTML | CSS selector via lxml + cssselect. |
| `xpath` | HTML | XPath 1.0 expression via lxml. |
| `json` | JSON | JSONPath expression via jsonpath-ng. |
| `regex` | Both | Python `re` pattern applied to the **raw response string**. Returns all non-overlapping matches (deduplicated, order-preserved). |

#### `attribute` — string | null · Default: `null`

When set, extract the named HTML attribute from the matched element instead of its text content.  The value is lowercased and stripped automatically.

```json
"attribute": "href"      // Extracts href from <a> tags
"attribute": "src"       // Extracts src from <img> tags
"attribute": "data-id"   // Extracts custom data attribute
```

When `null` (default), `.text_content()` is used, which returns all descendant text joined together.

#### `is_list` — bool · Default: `false`

When `false`: return only the first match.  
When `true`: return all matches as a JSON array.

#### `transformers` — list · Default: `[]`

Pipeline of transformations applied to the extracted value.  See [`docs/TRANSFORMERS.md`](TRANSFORMERS.md).

#### `children` — list of DataField | null · Default: `null`

Nested sub-fields extracted from each element matched by this field's selectors.  The parent field acts as a "container" selector; each matched element becomes the context for child resolution.

Children are typically paired with `is_list: true` to produce an array of objects:

```json
{
  "name": "products",
  "selector": "div.product",
  "is_list": true,
  "children": [
    {"name": "title", "selector": "h3"},
    {"name": "price", "selector": "span.price", "transformers": ["to_float"]}
  ]
}
```

#### `follow_url` — bool · Default: `false`

When `true`, the extracted value(s) are treated as URLs.  Glider fetches each URL and extracts `nested_fields` from the child page.

Requires `nested_fields` to be defined.  Uses the same rate limiter and proxy pool as the parent scrape.

#### `nested_fields` — list of DataField | null · Default: `null`

Field definitions applied to each child page when `follow_url: true`.  Each child record automatically includes `_source_url` and `_parent_url` metadata.

---

## Pagination Detail

```json
"pagination": {
  "selector": {"type": "css", "value": "li.next a"},
  "max_pages": 10,
  "query_param": "after"
}
```

### `selector` — Selector object · **Required**

Selects the element containing the next-page link or cursor.

* **HTML mode:** The element's `href` attribute is extracted and resolved as a URL.
* **JSON mode:** The JSONPath expression's matched value is used as a cursor token appended to the current URL as `?<query_param>=<value>`.

### `max_pages` — int ≥ 1 · Default: `5`

Maximum number of pages to process, including the first page.

### `query_param` — string · Default: `"after"`

Query string parameter name used for JSON API cursor pagination.  Ignored in HTML mode.

---

## Authentication Detail

### OAuth 2.0 Password Flow

```json
"authentication": {
  "type": "oauth_password",
  "token_url": "https://api.example.com/oauth/token",
  "client_id": "${CLIENT_ID}",
  "client_secret": "${CLIENT_SECRET}",
  "username": "${USERNAME}",
  "password": "${PASSWORD}",
  "scope": "read write"
}
```

The engine acquires a token before the first request and automatically refreshes it 60 seconds before expiry.  The `Authorization: Bearer <token>` header is injected into every request.

### Static Bearer Token

```json
"authentication": {
  "type": "bearer",
  "client_secret": "${MY_API_TOKEN}"
}
```

The token is loaded once and treated as non-expiring.

---

## Interactions Detail

All interactions execute sequentially in order.  Each interaction is retried once on failure before continuing.

```json
"interactions": [
  {"type": "fill",   "selector": "#q",        "value": "search term"},
  {"type": "click",  "selector": "button[type=submit]"},
  {"type": "wait",   "duration": 2000},
  {"type": "scroll"},
  {"type": "hover",  "selector": "div.dropdown"},
  {"type": "press",  "selector": "input.query", "value": "Enter"},
  {"type": "key",    "value": "Escape"}
]
```

| Type | Fields | Description |
|---|---|---|
| `click` | `selector` | Click the first matching element. |
| `fill` | `selector`, `value` | Clear and type `value` into the input. |
| `scroll` | — | `window.scrollTo(0, document.body.scrollHeight)`. |
| `wait` | `duration` (ms) | Pause for `duration` milliseconds. |
| `hover` | `selector` | Move mouse pointer over the element. |
| `press` | `selector`, `value` | Press the named key while the element has focus. |
| `key` | `value` | Dispatch a global keyboard event (e.g. `"Escape"`, `"Tab"`, `"ArrowDown"`). |

---

## Environment Variable Expansion

Any string value in the config may reference environment variables:

```json
"client_secret": "${MY_SECRET}"    // ${VAR_NAME} syntax
"password":      "$MY_PASSWORD"    // $VAR_NAME syntax (no braces)
```

If the variable is not set, the literal placeholder string is left unchanged (no error is raised).

---

## Full Example

```json
{
  "name": "example_scraper",
  "base_url": "https://example.com/products",
  "mode": "pagination",
  "response_type": "html",
  "use_playwright": false,
  "concurrency": 4,
  "rate_limit": 5,
  "request_timeout": 20,
  "min_delay": 0.5,
  "max_delay": 2.0,
  "use_checkpointing": true,
  "respect_robots_txt": true,
  "max_nested_urls": 10,
  "proxies": ["http://proxy1:8080", "http://proxy2:8080"],
  "headers": {"Accept-Language": "en-US"},
  "cookies_file": "session.json",
  "fields": [
    {
      "name": "products",
      "selector": "div.product",
      "is_list": true,
      "children": [
        {"name": "title",  "selector": "h2"},
        {"name": "price",  "selector": "span.price", "transformers": ["strip", "to_float"]},
        {"name": "image",  "selector": "img", "attribute": "src"},
        {
          "name": "detail_url",
          "selector": "a.details",
          "attribute": "href",
          "follow_url": true,
          "nested_fields": [
            {"name": "description", "selector": "div.description"},
            {"name": "sku", "selector": "span.sku", "transformers": [{"name": "regex", "args": ["SKU-(\\w+)"]}]}
          ]
        }
      ]
    }
  ],
  "pagination": {
    "selector": {"type": "css", "value": "a.next-page"},
    "max_pages": 20
  }
}
```
