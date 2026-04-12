# Known Issues & Limitations

This document lists confirmed design limitations and not-yet-implemented features in the current release (v2.8).  Resolved bugs from earlier releases have been removed.

---

## ⚠️ Design Limitations

### L1 — HTTP GET Only

Only HTTP GET requests are supported.  POST-based pagination, form submission, and webhook-style APIs are not implemented.  
**Workaround:** Use Playwright interactions (`fill`, `click`) to simulate form submissions on HTML pages.

---

### L2 — Pagination Mode is Sequential

In `pagination` mode, pages are always fetched one at a time regardless of the `concurrency` setting.  Concurrency only applies to `list` mode.  
**Reasoning:** Sequential pagination preserves page order and is required for correct cursor-based pagination.

---

### L3 — Bloom Filter Capacity Not Configurable via JSON Config

The Bloom filter capacity (default 100 000 items) and error rate (default 0.1%) are hardcoded in `engine/scraper.py`.  They cannot be changed from the JSON config file.

**Workaround:** Edit `engine/scraper.py` directly:
```python
# In ScraperEngine.__init__
self.seen_hashes = BloomFilter(capacity=1_000_000, error_rate=0.001)
```

---

### L4 — Batch Size Not Configurable via JSON Config

The micro-batch flush size (default 10 records per write) is hardcoded.  It can be changed at runtime via `engine.batch_size = N` after creating the engine instance, but this requires modifying `main.py`.

---

### L5 — `debug_mode` Config Field Is Reserved

The `debug_mode: bool` field is defined in the config schema and accepted without error, but it does not currently change any runtime behaviour.  It is reserved for a future feature (per-selector verbose tracing).

---

### L6 — Playwright Only Supports HTTP Proxies

Playwright is launched with `--proxy-server=<proxy>` which only supports HTTP proxies.  SOCKS5 proxies in the `proxies` list will be used for `curl_cffi` requests but will silently fail in Playwright.

---

### L7 — No Per-Domain Rate Limiting

The rate limiter is global across all workers and URLs.  There is no way to apply different rate limits to different domains.

---

### L8 — No Proxy Health Checking

Dead or slow proxies remain in the rotation pool indefinitely.  There is no mechanism to detect and remove failed proxies from the cycle.

---

### L9 — No Redirect Limit Control

`curl_cffi` follows redirects by default.  There is no config option to disable redirect following or cap the number of redirects.

---

### L10 — `response_type: "json"` + `use_playwright: true` May Not Parse Correctly

Playwright's `page.content()` returns the full rendered HTML page (including `<html>`, `<head>`, `<body>` wrappers), not the raw JSON body.  When using both settings together, `JsonResolver` will receive HTML-wrapped JSON and may fail to parse it correctly.  
**Workaround:** Do not use `use_playwright: true` with `response_type: "json"`.  Use `curl_cffi` (the default) for JSON API scraping.

---

### L11 — CSV Nested List Fields Are Pipe-Joined Strings

When a field value is a list (e.g. `tags: ["python", "news"]`), the CSV export converts it to a pipe-separated string (`python | news`).  The JSON export preserves the original list structure.  
**Workaround:** Use the JSON output format when downstream processing needs list values.

---

## 📋 Unimplemented / Planned Features

| Feature | Notes |
|---|---|
| `--output-dir` CLI flag | Currently always writes to `data/`. |
| `--max-items` / `--limit` CLI flag | Stop after extracting N total records. |
| `--dry-run` CLI flag | Validate config and test selectors without persisting data. |
| `--validate` CLI flag | Check config syntax and report errors without scraping. |
| POST request support | Required for REST APIs that use POST for queries. |
| Per-domain rate limiting | Apply different `rate_limit` values per host. |
| Proxy health monitoring | Remove dead proxies from rotation automatically. |
| Sitemap.xml crawling | Discover URLs from a site's sitemap instead of pagination. |
| Configurable Bloom filter | Set `capacity` and `error_rate` via the JSON config. |
| Configurable batch size | Set `batch_size` via the JSON config. |
| `debug_mode` implementation | Verbose selector tracing and intermediate value logging. |
| Multiple output formats | Parquet, SQLite, NDJSON as export targets. |
| CAPTCHA handling integration | Hook for external CAPTCHA-solving services. |
| CSV nested list expansion | Expand list fields into multiple rows instead of pipe-joining. |
