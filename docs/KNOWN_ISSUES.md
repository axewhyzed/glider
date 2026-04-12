# Known Issues & Limitations

This document lists confirmed bugs, design limitations, and not-yet-implemented features in the current release (v2.7.1).  It is intended to give users a transparent picture of what works, what needs workarounds, and what is planned.

---

## 🐛 Confirmed Bugs

### B1 — Mutable Default Argument in `_run_list_mode`

**File:** `engine/scraper.py`  
**Severity:** Low (cosmetic / Python anti-pattern)

`_run_list_mode` uses `incomplete_urls: List[str] = []` as a default argument.  In Python, mutable default arguments are shared across all calls that don't pass the argument explicitly.  While this does not cause observable incorrect behaviour in the current call sites, it is a code correctness issue.

**Workaround:** None needed; the list is only read, never mutated in-place at the default value.

---

### B2 — Final Partial Batch Not Counted in Dashboard Stats

**File:** `engine/scraper.py`  
**Severity:** Low (cosmetic)

The live dashboard "Total Entries" counter is updated via the `entries_added` stats event.  This event is only fired when a full batch of 10 items is flushed.  The remaining items in the last partial batch (flushed by `_flush_remaining_batches` at shutdown) do not trigger the stats event.

**Effect:** The dashboard may show a count up to 9 items lower than the actual number of records written to disk.  The exported JSON and CSV files always contain the correct, complete count.

**Workaround:** Compare the final exported file's record count with the dashboard figure to get the true count.

---

### B3 — Unreachable Code in `HtmlResolver._select_elements`

**File:** `engine/resolver.py` (line 135)  
**Severity:** Negligible (dead code)

A `return []` statement after the try/except block is unreachable because both branches inside the block (`css`, `xpath`) already `return`.  This is dead code and has no runtime effect.

---

### B4 — `.json` Suffix Appended to All Child URLs in JSON Mode

**File:** `engine/scraper.py`  
**Severity:** Medium (affects non-Reddit JSON APIs using `follow_url`)

When `response_type` is `"json"` and `follow_url` is `true`, the engine appends `.json` to any child URL that does not already end with `.json`.  This is a Reddit-specific convention (Reddit JSON API endpoints end in `.json`) that was hardcoded into the general engine.

**Effect:** For non-Reddit JSON APIs using recursive link following, child URLs will have `.json` incorrectly appended, likely resulting in 404 errors.

**Workaround:** For non-Reddit APIs, extract full absolute URLs as child link values (the code skips the `.json` appending if the URL already ends in `.json`) or ensure the API returns absolute API-format URLs in its link fields.

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
# Line ~45 in ScraperEngine.__init__
self.seen_hashes = BloomFilter(capacity=1_000_000, error_rate=0.001)
```

---

### L4 — Batch Size Not Configurable via JSON Config

The micro-batch flush size (default 10 records per write) is hardcoded.  It can be changed at runtime via `engine.batch_size = N` after creating the engine instance, but this requires modifying `main.py`.

---

### L5 — `debug_mode` Config Field Is Reserved

The `debug_mode: bool` field is defined in the config schema and accepted without error, but it does not currently change any runtime behaviour.  It is reserved for a future feature (e.g. per-selector verbose tracing).

---

### L6 — Browser Interactions Silently Ignored Without Playwright

If `interactions` are defined in a config but `use_playwright` is `false`, the interactions are silently ignored.  No warning is emitted.

**Workaround:** Always set `"use_playwright": true` when defining `interactions`.

---

### L7 — `wait_for_selector` Timeout Silently Exceeded

If `wait_for_selector` is set and the element does not appear within 5 seconds, Playwright continues scraping without the element (graceful degradation).  No warning is logged, so there is no indication that the wait timed out.

---

### L8 — Playwright Only Supports HTTP Proxies

Playwright is launched with `--proxy-server=<proxy>` which only supports HTTP proxies.  SOCKS5 proxies in the `proxies` list will be used for `curl_cffi` requests but Playwright will silently ignore them or fail.

---

### L9 — `selectolax` Package Listed as Dependency but Unused

`selectolax` appears in `requirements.txt` but is not imported or used anywhere in the codebase.  HTML parsing uses `lxml` with `cssselect` for both CSS and XPath selectors.

**Effect:** Negligible — the package is installed but not loaded.  No runtime impact.

---

### L10 — No Per-Domain Rate Limiting

The rate limiter is global across all workers and URLs.  There is no way to apply different rate limits to different domains.

---

### L11 — No Proxy Health Checking

Dead or slow proxies remain in the rotation pool indefinitely.  There is no mechanism to detect and remove failed proxies from the cycle.

---

### L12 — No Redirect Limit Control

`curl_cffi` follows redirects by default.  There is no config option to disable redirect following or cap the number of redirects.

---

### L13 — No POST / Form Auth

Login flows that require submitting a username/password form (not OAuth 2.0) are not supported.  
**Workaround:** Use Playwright with `fill` + `click` interactions to simulate the login form, combined with a `cookies_file` to persist the session for subsequent runs.

---

### L14 — `response_type: "json"` + `use_playwright: true` May Not Parse Correctly

Playwright's `page.content()` returns the full rendered HTML page (including `<html>`, `<head>`, `<body>` wrappers), not the raw JSON body.  When using both settings together, `JsonResolver` will receive HTML-wrapped JSON and may fail to parse it correctly.  
**Workaround:** Do not use `use_playwright: true` with `response_type: "json"`.  Use `curl_cffi` (the default) for JSON API scraping.

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
| Upgrade guide for v2.7 | `UPGRADE_GUIDE.md` currently only covers v2.5 → v2.6. |
