"""Observability tests (P9.1-P9.3)."""

import asyncio

from engine.metrics import Histogram, MetricsCollector, RequestSample
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine


def test_histogram_known_percentiles():
    h = Histogram()
    for ms in range(1, 101):
        h.record(float(ms))
    p50 = h.percentile(0.50)
    p95 = h.percentile(0.95)
    # Log-linear buckets: p50 lands in the 33-64ms bucket (interpolated ~50),
    # p95 in the 65-128ms bucket (interpolated ~119 vs true 95).
    assert 48 <= p50 <= 52
    assert 100 <= p95 <= 128
    assert h.count == 100


def test_histogram_empty_returns_none():
    h = Histogram()
    assert h.percentile(0.5) is None
    assert h.max() is None


def test_histogram_overflow_bucketed():
    h = Histogram()
    h.record(2 ** 17)  # beyond the last bucket
    assert h.overflow == 1
    assert h.max() == 2 ** 17


def test_metrics_records_success_sample():
    collector = MetricsCollector()
    collector.record(RequestSample("https://example.com", "root", 200, 12.5, 1, "success"))
    snap = collector.snapshot()
    assert snap["domains"]["https://example.com"]["requests"] == 1
    assert snap["domains"]["https://example.com"]["success"] == 1


def test_metrics_per_domain_isolation():
    collector = MetricsCollector()
    collector.record(RequestSample("https://a.com", "root", 200, 1, 1, "success"))
    collector.record(RequestSample("https://b.com", "root", 503, 2, 3, "http_error"))
    snap = collector.snapshot()
    assert snap["domains"]["https://a.com"]["failed"] == 0
    assert snap["domains"]["https://b.com"]["failed"] == 1
    assert snap["domains"]["https://b.com"]["by_category"]["http_error"] == 1


def test_metrics_duplicates_tracked():
    collector = MetricsCollector()
    collector.record_duplicate()
    collector.record_duplicate()
    assert collector.snapshot()["duplicates_detected"] == 2


def test_latency_fed_from_fetch_result(tmp_path):
    config = ScraperConfig(name="m", base_url="https://example.com", fields=[])
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "b.bloom"
    engine._record_sample("https://example.com", "root", 200, 37.5, 1, "success")
    snap = engine.metrics.snapshot()
    assert snap["latency_ms"]["samples"] == 1
    assert snap["latency_ms"]["max"] == 37.5
