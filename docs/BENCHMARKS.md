# Benchmarks and usage validation

Glider's benchmark is deterministic and local so changes can be compared
without depending on public-site availability, remote throttling, or network
conditions. It exercises the real HTTP transport, URL policy, HTML resolver,
list-mode workers, batching, and output callback.

Run it with:

```powershell
venv\Scripts\python.exe -m benchmarks.local --pages 100 --concurrency 10 --repeats 3
```

The JSON output reports elapsed time, records, failed pages, batches, and
requests per second for each repetition. Record results with the Python
version, OS, dependency versions, page count, and concurrency; compare like
with like. The fixture server is intentionally loopback-only and uses a local
policy exception in its benchmark configuration.

The end-to-end fixture tests run in the normal suite:

```powershell
venv\Scripts\python.exe -m pytest tests/test_local_usage.py -q
```

These tests cover HTML pagination, JSON API extraction, nested links, and list
processing through an actual local HTTP server. They complement unit tests and
optional public-site smoke tests; they do not replace target-specific
validation before production use.

## Suggested benchmark matrix

Start with `pages=1000` and compare concurrency `1`, `5`, `10`, and `25`.
Measure at least three repeats after one warm-up run. Watch both throughput and
memory: increasing concurrency should not be accepted as an improvement if it
causes unstable failure rates or excessive memory growth.
