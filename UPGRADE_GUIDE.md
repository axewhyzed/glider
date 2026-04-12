# Upgrade Guide

---

## v2.7 → v2.8 (April 2026)

### Breaking Changes

**None.** All existing configs are fully backward-compatible.

---

### Required: Update Dependencies

```bash
pip install -r requirements.txt
```

`selectolax` has been removed from `requirements.txt` (it was listed but never used).  If you had it installed it will remain installed but is no longer needed.

---

### New Config Field: `append_json_suffix`

If you use `follow_url` with Reddit's JSON API, add `"append_json_suffix": true` to your config to restore the `.json` URL appending that was previously hardcoded:

```json
{
  "response_type": "json",
  "append_json_suffix": true,
  "fields": [
    {
      "name": "links",
      "selectors": [{"type": "json", "value": "data.children[*].data.permalink"}],
      "is_list": true,
      "follow_url": true,
      "nested_fields": [...]
    }
  ]
}
```

For all **non-Reddit** JSON APIs, leave `append_json_suffix` at its default (`false`).

---

### Dashboard Changes

The `📊 Total Entries` metric has been renamed to `📊 Total Records` and now counts **individual items** rather than page fetches.  For example, if each page contains 25 products, scraping 10 pages now reports 250 records instead of 10.

---

### What Was Fixed in v2.8

See [CHANGELOG.md](../CHANGELOG.md) for the full list.  Summary:

| # | Issue | Impact |
|---|---|---|
| 1 | JSON API pagination stopped after page 1 with shorthand selector | **HIGH** — data loss |
| 2 | Final batch not counted in dashboard | HIGH — incorrect stats |
| 3 | Pagination failures not shown in dashboard | HIGH — silent errors |
| 4 | `blocked` stat not fired in pagination mode | MEDIUM — incorrect stats |
| 5 | Non-serializable values crashed `_merge_data` | MEDIUM — data loss |
| 6 | `.json` suffix forced on all JSON follow_url | MEDIUM — wrong URLs for non-Reddit APIs |
| 7–14 | Various low-severity fixes | LOW — cosmetic / robustness |

---

## v2.5 → v2.6

## Quick Start

```bash
# 1. Update dependencies
pip install -r requirements.txt

# 2. Test with existing config (no changes needed)
python main.py configs/books_example.json

# 3. Observe new dashboard metrics
# You'll now see:
# - 📊 Total Entries (not just page count)
# - ⚡ Avg Entries/sec (extraction rate)
```

---

## New Features You Should Use

### 1. Enable Checkpointing for Large Scrapes

**Before** (v2.5): Crashes meant starting over from scratch

**After** (v2.6): Automatic resume from last successful URL

#### Update Your Config:
```json
{
  "name": "My Large Scrape",
  "use_checkpointing": true,
  "base_url": "https://example.com"
}
```

#### How It Works:
```bash
# First run - processes 500 URLs, crashes at URL #347
python main.py configs/large_scrape.json
# Ctrl+C at any point

# Second run - automatically skips first 347 URLs
python main.py configs/large_scrape.json
# Starts from URL #348
```

---

### 2. Monitor Extraction Performance

**New Dashboard Metrics** (automatically enabled):

```
🚀 Glider Scraper: My Project
┌──────────────────────────┬────────────────────┐
│ Metric                    │ Value              │
├──────────────────────────┼────────────────────┤
│ ⏱️  Elapsed Time         │ 00:03:42           │
│ ✅ Successful Pages      │ 23                 │
│ ❌ Failed Pages          │ 1                  │
│ 📊 Total Records        │ 4,892              │
│ ⚡ Avg Records/sec       │ 22.03              │
└──────────────────────────┴────────────────────┘
```

---

### 3. Recover from Crashes

**Scenario**: Network drops mid-scrape

#### What Happens Now:
```bash
# Scraping 10,000 products...
python main.py configs/products.json

# Network dies at product #7,234 — NO DATA LOSS!
# Restart scraper with checkpointing enabled:
python main.py configs/products.json
# Automatically resumes from product #7,235
```

---

## Performance Tuning

### Adjust Batch Size (Advanced)

Default: 10 items per write

```python
# In main.py, modify engine initialization:
engine = ScraperEngine(config, ...)
engine.batch_size = 50  # Larger batches = fewer writes
```

### Increase Bloom Filter Capacity

Default: 100 000 items

```python
# In engine/scraper.py ScraperEngine.__init__:
self.seen_hashes = BloomFilter(capacity=1_000_000, error_rate=0.001)
```

---

## FAQ

### Q: Do I need to update my configs?
**A**: No for v2.5 → v2.6.  For v2.7 → v2.8, add `"append_json_suffix": true` only if you use Reddit-style `follow_url` with a JSON response type.

### Q: What's the false positive rate for the Bloom filter?
**A**: 0.1% — meaning 1 in 1000 unique items might be incorrectly flagged as a duplicate.

### Q: How do I report bugs?
**A**: Open an issue on GitHub with the config file, `logs/glider.log`, and a description of expected vs actual behaviour.

