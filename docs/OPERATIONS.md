# Operations Guide

This document covers the operator-facing behavior introduced in the production-readiness release: run isolation, resume, output artifacts, network policy, retry behavior, credential scoping, and failure semantics.

## CLI

```
glider validate CONFIG [--format text|json]
glider preview  CONFIG [--url URL] [--format text|json]
glider scrape   CONFIG [--dry-run] [--url URL] [--limit N] [--output-dir DIR]
                       [--run-id ID] [--resume ID] [--log-level LEVEL]
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success (including dry-run and empty-but-intended runs) |
| 1 | Runtime failure / preview or dry-run failure / run-context errors |
| 2 | Invalid input: config invalid, file missing, malformed JSON, bad `--format` |
| 4 | Run completed but ≥1 page failed (partial failure; artifacts preserved) |
| 130 | Interrupted (Ctrl+C); artifacts preserved for resume |

## Run directories

Every `scrape` creates an isolated run directory:

```
<output-dir>/<config-slug>/runs/<run_id>/
├── manifest.json        # run metadata + config digest + summary
├── stream.jsonl         # raw extracted records (one batch per line)
├── checkpoint.sqlite    # crawl-item state (kinds: root/pagination/nested)
├── dedupe.bloom         # Bloom acceleration layer
├── failures.jsonl       # one JSON line per failed page
├── report.json          # final operator report
├── exports/
│   ├── output.json      # extracted records as JSON array
│   └── output.csv       # flattened CSV
└── debug/               # bounded failed-page HTML snapshots
```

`<output-dir>` defaults to `data/` and is controlled with `--output-dir`.

## Resume

- `--resume <run_id>` continues an existing run **only if the config digest matches** the run's `manifest.json`. A mismatched config is refused (exit 1).
- `--run-id <id>` is for manual pinning on a fresh run; colliding with an existing run raises an error.
- Resume only re-queues resumable work: `in_progress`/`failed` items of the matching kind (pagination/root/nested). Completed work is never re-fetched; nested child results are re-attached from `checkpoint.sqlite`.
- Use the same `--output-dir` when resuming.

## Retry policy

Configured via the `retry` block:

| Field | Default | Meaning |
|---|---|---|
| `max_attempts` | 3 | Total attempts per request |
| `base_delay_seconds` | 1.0 | Exponential backoff base |
| `max_delay_seconds` | 30.0 | Backoff ceiling |
| `retry_statuses` | 408, 425, 429, 500, 502, 503, 504 | Statuses considered transient |
| `retry_after_cap_seconds` | 300.0 | Cap for honoring `Retry-After` |

- Network failures and timeouts are retried.
- HTTP status is retried only if it is in `retry_statuses`.
- Parse, robots, auth, policy, and validation failures are **never** retried.
- 429 with a `Retry-After` header waits up to the cap; after exhausting attempts it is reported as a `rate_limit` error.

## URL policy

Configured via the `url_policy` block:

| Field | Default | Meaning |
|---|---|---|
| `allowed_domains` | `[]` | Exact domains, or `*.domain` wildcards |
| `allow_subdomains` | false | Match subdomains for exact entries |
| `allow_external_urls` | false | Permit cross-origin links |
| `allowed_schemes` | `["http", "https"]` | Only http/https |
| `block_private_networks` | true | Reject localhost/private/loopback/link-local IPs |
| `resolve_dns` | true | Pre-flight DNS: reject hostnames resolving to private IPs |
| `max_redirects` | 5 | Redirect hop cap |

Defaults are deny-by-default: same-origin traversal only, private networks blocked, TLS verification on.

## Credential scoping

- Sensitive headers (`Authorization`, `Cookie`, `x-api-key`, etc.) are sent **only to their configured origin**; they are stripped on cross-origin requests.
- Bearer tokens are injected only same-origin.
- Browser cookies are scoped to `base_url`; domain-less cookies are refused.
- The manifest stores a redacted copy of the config (digest still hashes the raw config).
- `interaction_failure_policy=fail` makes a failed browser action a resumable page failure; `warn` keeps the compatibility behavior.
- `robots_failure_policy=allow|deny` controls whether an unavailable or malformed robots file permits crawling. Robots origin state is bounded by `robots_max_origins`.

## Failure semantics

- Every failed page is appended to `failures.jsonl` (url, category, message, timestamp) and kept in a bounded in-memory ring for the final report.
- Failed items (`status='failed'`) are resumable on the next run.
- A run with failures exits 4; `manifest.json` records `failed_count` and the report lists a capped preview of failed URLs.
- Debug snapshots are bounded by `debug_snapshots` (`max_files`, `max_bytes_per_file`, `max_total_bytes`).
- With `fail_parent_on_nested_error=true`, any required child failure keeps the parent resumable; with `false`, successful child data may be emitted with a partial-nested warning.
