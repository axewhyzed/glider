# Known Issues & Limitations

This document lists confirmed design limitations and not-yet-implemented features in the current release (v2.9). Resolved bugs from earlier releases have been removed.

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

### L3 — Bloom Filter Capacity Configurable via JSON Config (Resolved)

The Bloom filter capacity and error rate are now configurable via the `dedup` config block (`dedup.capacity`, `dedup.error_rate`, `dedup.exact_capacity`). Defaults preserve prior behavior (100 000 items, 0.1% error rate).

---

### L4 — Batch Size Not Configurable via JSON Config

The micro-batch flush size (default 10 records per write) is hardcoded.  It can be changed at runtime via `engine.batch_size = N` after creating the engine instance, but this requires modifying `main.py`.

---

### L5 — `debug_mode` Config Field

The `debug_mode: bool` field forces DEBUG logging and raises the debug-snapshot cap. Per-selector verbose tracing is not implemented.

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

### L9 — Redirect Limit Control (Resolved)

Redirects are followed manually with per-hop policy validation; the maximum hop count is configurable via `url_policy.max_redirects` (default 5). A redirect hop that violates URL policy aborts the chain.

---

### L10 — `response_type: "json"` + `use_playwright: true` May Not Parse Correctly

Playwright's `page.content()` returns the full rendered HTML page (including `<html>`, `<head>`, `<body>` wrappers), not the raw JSON body.  When using both settings together, `JsonResolver` will receive HTML-wrapped JSON and may fail to parse it correctly.  
**Workaround:** Do not use `use_playwright: true` with `response_type: "json"`.  Use `curl_cffi` (the default) for JSON API scraping.

---

### L11 — CSV Nested List Fields Are Pipe-Joined Strings

When a field value is a list (e.g. `tags: ["python", "news"]`), the CSV export converts it to a pipe-separated string (`python | news`).  The JSON export preserves the original list structure.  
**Workaround:** Use the JSON output format when downstream processing needs list values.

---

### L12 — DNS Rebinding Residual Risk

Application-level DNS/IP checks (private-network blocking, `resolve_dns` pre-flight, browser request interception) cannot fully prevent a DNS rebinding attack where a resolver returns a public IP at validation time and a private IP at request time. Non-browser mode mitigates via hop-level policy checks (documented residual risk); browser mode adds request-interception abort of private-IP navigation.

---

## 📋 Unimplemented / Planned Features

| Feature | Notes |
|---|---|
| POST request support | Required for REST APIs that use POST for queries. |
| Per-domain rate limiting | Apply different `rate_limit` values per host. |
| Proxy health monitoring | Remove dead proxies from rotation automatically. |
| Sitemap.xml crawling | Discover URLs from a site's sitemap instead of pagination. |
| Configurable batch size | Set `batch_size` via the JSON config. |
| `debug_mode` implementation | Verbose selector tracing and intermediate value logging. |
| Multiple output formats | Parquet, SQLite, NDJSON as export targets. |
| CAPTCHA handling integration | Hook for external CAPTCHA-solving services. |
| CSV nested list expansion | Expand list fields into multiple rows instead of pipe-joining. |

*Implemented in the production-readiness release:* `--output-dir`, `--limit`, `--dry-run` (with `--url`), `validate`/`preview`/`scrape` CLI subcommands, configurable Bloom filter (`dedup.capacity`/`error_rate`), and intentional exit codes (0/1/2/4/130).
