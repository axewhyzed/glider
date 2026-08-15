# Benchmarks and usage validation

Glider's benchmark is deterministic and local so changes can be compared
without depending on public-site availability, remote throttling, or network
conditions. It exercises the real HTTP transport, URL policy, HTML resolver,
list-mode workers, batching, and output callback.

Run it with:

```powershell
venv\Scripts\python.exe -m benchmarks.local --pages 100 --concurrency 10 --repeats 3
```

The default JSON output contains separate measurements for list extraction,
HTML pagination, JSON extraction, and nested-link extraction. Each scenario
reports elapsed time, records, requests, failed pages, batches, and requests
per second for each repetition. Nested extraction also reports the number of
child records, because its root result contains one catalog record. Record
results with the Python
version, OS, dependency versions, page count, and concurrency; compare like
with like. The fixture server is intentionally loopback-only and uses a local
policy exception in its benchmark configuration.

Measure one path when investigating a regression:

```powershell
venv\Scripts\python.exe -m benchmarks.local --scenario pagination --pages 100 --concurrency 10 --repeats 3
```

The end-to-end fixture tests run in the normal suite:

```powershell
venv\Scripts\python.exe -m pytest tests/test_local_usage.py -q
```

These tests cover HTML pagination, JSON API extraction, nested links, and list
processing through an actual local HTTP server. They complement unit tests and
optional public-site smoke tests; they do not replace target-specific
validation before production use.

## Scenario matrix

| Scenario | Fixture path | Primary measurement |
| --- | --- | --- |
| `list` | independent HTML item pages | concurrent list throughput |
| `pagination` | linked HTML pages | sequential pagination and extraction |
| `json` | independent JSON API items | JSON resolver throughput |
| `nested` | catalog plus child pages | link discovery and child extraction |

The benchmark uses `127.0.0.1` only and explicitly opts out of the normal
private-network block in its test configuration. It never contacts a public
site.

## Suggested comparison matrix

Start with `pages=1000` and compare concurrency `1`, `5`, `10`, and `25`.
Measure at least three repeats after one warm-up run. Watch both throughput and
memory: increasing concurrency should not be accepted as an improvement if it
causes unstable failure rates or excessive memory growth.
