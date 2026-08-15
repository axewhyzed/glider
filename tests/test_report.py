"""Report builder tests (P8.4/P8.6)."""

import json

from engine.network import FetchResult
from engine.report import (
    PreviewDiagnostics,
    build_final_report,
    build_preview_report,
    build_resume_command,
)
from engine.run import RunContext
from engine.schemas import ScraperConfig


class _Stats:
    success = 10
    failed = 2
    skipped = 1
    blocked = 0
    entries_extracted = 50
    failures_ring = [{"url": "https://example.com/f1"},
                     {"url": "https://example.com/f2"}] * 5


def test_preview_report_field_counts():
    config = ScraperConfig(name="p", base_url="https://example.com", fields=[
        {"name": "books", "selector": "div.book", "is_list": True},
    ], pagination={"selector": "li.next a", "max_pages": 3})
    fetch = FetchResult(content="<html></html>", requested_url="https://example.com/",
                        final_url="https://example.com/", status_code=200)
    diag = PreviewDiagnostics(
        field_matches={"books": 3},
        samples={"books": ["a", "b", "c"]},
        pagination_match="/page/2",
        pagination_next="https://example.com/page/2",
    )
    report = build_preview_report(fetch, {"books": [{"t": "x"}]}, config, diag)
    assert report["fields"][0]["match_count"] == 3
    assert report["pagination"]["matched"] is True
    assert report["pagination"]["next_url"] == "https://example.com/page/2"
    json.dumps(report)  # serializable


def test_preview_report_zero_match_field():
    config = ScraperConfig(name="p", base_url="https://example.com", fields=[
        {"name": "missing", "selector": ".nonexistent"},
    ])
    fetch = FetchResult(content="<html></html>", requested_url="https://example.com/",
                        final_url="https://example.com/", status_code=200)
    diag = PreviewDiagnostics(field_matches={"missing": 0}, samples={})
    report = build_preview_report(fetch, {"missing": None}, config, diag)
    assert report["fields"][0]["matched"] is False
    assert report["fields"][0]["match_count"] == 0


def test_preview_report_pagination_no_match():
    config = ScraperConfig(name="p", base_url="https://example.com", fields=[])
    fetch = FetchResult(content="", requested_url="u", final_url="u", status_code=200)
    diag = PreviewDiagnostics(pagination_match=None, pagination_next=None)
    report = build_preview_report(fetch, {}, config, diag)
    assert report["pagination"]["matched"] is False
    assert report["pagination"]["next_url"] is None


def test_final_report_shape(tmp_path):
    config = ScraperConfig(name="r", base_url="https://example.com", fields=[])
    ctx = RunContext.create("r", {"name": "r"}, output_root=tmp_path)
    report = build_final_report(
        _Stats(),
        ctx,
        config,
        {
            "domains": {"https://example.com": {
                "requests": 12, "success": 10, "failed": 2, "blocked": 0,
                "by_category": {"success": 10, "http_error": 2},
                "latency_ms": {"p50": 10, "p95": 20},
            }},
            "duplicates_detected": 3,
            "latency_ms": {"p50": 10, "p95": 20, "max": 50, "samples": 12},
        },
        "resume cmd",
    )
    assert report["pages"]["success"] == 10
    assert report["records"]["deduplicated"] == 3
    assert "https://example.com" in report["domains"]
    assert report["error_categories"]["http_error"] == 2
    assert len(report["failed_urls_preview"]) == 5  # capped
    json.dumps(report)


def test_resume_command_contains_run_id():
    cmd = build_resume_command(["main.py", "config.json"], "run-123")
    assert "run-123" in cmd
    assert "--resume" in cmd
