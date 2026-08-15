# Glider examples

These examples are intentionally small and are meant to be copied and edited.
They are configuration templates, not claims that the placeholder hosts are
available or that a target permits crawling.

Validate any example before running it:

```powershell
venv\Scripts\glider.exe validate examples\quickstart_list.json --format json
```

For a first run, copy a template, replace its example host and selectors, then
validate before scraping:

```powershell
Copy-Item examples\quickstart_list.json my_scraper.json
venv\Scripts\glider.exe validate my_scraper.json --format json
venv\Scripts\glider.exe scrape my_scraper.json --output-dir data
```

For a deterministic end-to-end run without external network access, use the
local fixture benchmark:

```powershell
venv\Scripts\python.exe -m benchmarks.local --pages 100 --concurrency 10 --repeats 3
```

The command runs list, pagination, JSON, and nested-link scenarios separately.
Use `--scenario list`, `pagination`, `json`, or `nested` to measure one path.

Examples included:

- `quickstart_list.json`: simple HTML list extraction.
- `api_post.json`: JSON API POST using a form or JSON body.
- `nested_links.json`: parent records with origin-scoped child pages.

Before using a real target, confirm its terms, robots policy, rate limits, and
authorization requirements. Keep credentials in environment-expanded values,
never in committed JSON.
