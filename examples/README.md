# Glider examples

These examples are intentionally small and are meant to be copied and edited.
They are configuration templates, not claims that the placeholder hosts are
available or that a target permits crawling.

Validate any example before running it:

```powershell
venv\Scripts\glider.exe validate examples\quickstart_list.json --format json
```

For a deterministic end-to-end run without external network access, use the
local fixture benchmark:

```powershell
venv\Scripts\python.exe -m benchmarks.local --pages 100 --concurrency 10 --repeats 3
```

Examples included:

- `quickstart_list.json`: simple HTML list extraction.
- `api_post.json`: JSON API POST using a form or JSON body.
- `nested_links.json`: parent records with origin-scoped child pages.

Before using a real target, confirm its terms, robots policy, rate limits, and
authorization requirements. Keep credentials in environment-expanded values,
never in committed JSON.
