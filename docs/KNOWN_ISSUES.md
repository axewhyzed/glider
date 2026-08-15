# Known Issues & Limitations

This document lists intentional limitations in Glider v3.0.0. Resolved v3 transport, checkpoint, security, and export bugs are not listed here.

## Design limitations

### L1 - Pagination mode is sequential

Pagination mode fetches one page at a time to preserve cursor order. Concurrency applies to list-mode work.

### L2 - Playwright proxy protocol

Playwright supports HTTP proxy configuration. SOCKS5 proxies remain available to the curl transport but are not portable to browser mode.

### L3 - Browser JSON is navigation-scoped

For `response_type: "json"` with Playwright, Glider captures the raw navigation response body. JSON returned only by a later XHR/fetch interaction requires an interaction-specific integration.

### L4 - Proxy health is run-scoped

Proxy circuit health is tracked in memory for the current run. Independent runs intentionally start with a fresh health state.

### L5 - CSV list fields are pipe-joined

CSV export represents list values as pipe-separated strings. JSON output preserves list structure.

### L6 - DNS rebinding residual risk

Application-level DNS/IP checks and browser request interception substantially reduce SSRF risk, but cannot guarantee protection against a resolver that changes answers between validation and connection. Use an egress firewall for hostile environments.

### L7 - Multi-step API workflows

Single-request GET/POST API scraping is supported. Chained API workflows requiring stateful authentication or custom request sequencing need explicit application integration.

## Implemented v3 capabilities

- Safe GET and POST requests with JSON/form bodies.
- Per-attempt global and optional per-domain rate limiting.
- Run-scoped proxy circuit breaking with cooldown and half-open recovery.
- Bounded sitemap and sitemap-index discovery.
- Raw browser navigation-response capture for JSON APIs.
- Origin-scoped sensitive headers and per-request browser SSRF interception.
- Durable exact deduplication for resumed runs.

Other intentionally unimplemented extensions include Parquet/SQLite output, CAPTCHA-solving services, and CSV list expansion.
