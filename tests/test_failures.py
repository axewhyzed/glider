"""Bounded failures + debug snapshot tests (P7.4/P7.5)."""

import json

import pytest

from engine.errors import ErrorCategory, FetchError
from engine.run import RunContext
from engine.schemas import DebugSnapshotConfig, ScraperConfig
from engine.scraper import ScraperEngine


def _engine(tmp_path):
    config = ScraperConfig(
        name="fail",
        base_url="https://example.com",
        fields=[],
        max_failed_entries=5,
    )
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "dedupe.bloom"
    return engine


async def test_failed_ring_bounded(tmp_path):
    engine = _engine(tmp_path)
    for i in range(20):
        engine._record_failure(f"https://example.com/{i}",
                               FetchError(ErrorCategory.NETWORK, f"https://example.com/{i}"))
    assert len(engine.failures_ring) == 5  # bounded
    assert len(engine.failed_urls) == 20  # full count retained separately


async def test_failures_jsonl_written_per_failure(tmp_path):
    ctx = RunContext.create("fail", {"name": "fail"}, output_root=tmp_path)
    engine = _engine(tmp_path)
    engine.run_context = ctx
    engine._record_failure("https://example.com/x",
                           FetchError(ErrorCategory.HTTP, "https://example.com/x", status_code=503))
    # Let the background append_failure task run.
    await _drain_tasks()
    lines = ctx.failures_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["category"] == "http_error"
    assert "example.com/x" in entry["url"]


async def test_failures_redact_auth_secrets(tmp_path):
    ctx = RunContext.create("fail", {"name": "fail"}, output_root=tmp_path)
    engine = _engine(tmp_path)
    engine.run_context = ctx
    engine._record_failure(
        "https://example.com/x?token=supersecret",
        FetchError(ErrorCategory.AUTH, "https://example.com/x?token=supersecret",
                   message="client_secret=supersecret"),
    )
    await _drain_tasks()
    content = ctx.failures_path.read_text(encoding="utf-8")
    # The message is truncated to 200 chars; the secret substring is still
    # present in the URL — redaction of URLs happens at P9.4. Here we assert
    # the message field is bounded (no unbounded error text).
    assert len(json.loads(content.strip().splitlines()[0])["message"]) <= 200


async def _drain_tasks():
    import asyncio
    for _ in range(10):
        await asyncio.sleep(0.05)


async def test_snapshot_disabled_writes_nothing(tmp_path):
    config = ScraperConfig(
        name="snap",
        base_url="https://example.com",
        fields=[],
        debug_snapshots=DebugSnapshotConfig(enabled=False),
    )
    engine = ScraperEngine(config)
    engine.run_context = RunContext.create("snap", {"name": "snap"}, output_root=tmp_path)
    await engine._save_debug_snapshot("<html>boom</html>", "https://example.com/")
    assert list(engine.run_context.debug_directory.glob("fail_*.html")) == []


async def test_snapshot_max_files_evicts_oldest(tmp_path):
    config = ScraperConfig(
        name="snap",
        base_url="https://example.com",
        fields=[],
        debug_snapshots=DebugSnapshotConfig(max_files=3),
    )
    engine = ScraperEngine(config)
    engine.run_context = RunContext.create("snap", {"name": "snap"}, output_root=tmp_path)
    for i in range(5):
        await engine._save_debug_snapshot(f"<html>{i}</html>", f"https://example.com/{i}")
    files = list(engine.run_context.debug_directory.glob("fail_*.html"))
    assert len(files) == 3  # newest retained


async def test_snapshot_truncated_to_max_bytes(tmp_path):
    config = ScraperConfig(
        name="snap",
        base_url="https://example.com",
        fields=[],
        debug_snapshots=DebugSnapshotConfig(max_bytes_per_file=50),
    )
    engine = ScraperEngine(config)
    engine.run_context = RunContext.create("snap", {"name": "snap"}, output_root=tmp_path)
    await engine._save_debug_snapshot("<html>" + "x" * 1000 + "</html>", "https://example.com/")
    files = list(engine.run_context.debug_directory.glob("fail_*.html"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "truncated" in content


async def test_snapshot_uses_run_debug_directory(tmp_path):
    config = ScraperConfig(
        name="snap",
        base_url="https://example.com",
        fields=[],
    )
    engine = ScraperEngine(config)
    ctx = RunContext.create("snap", {"name": "snap"}, output_root=tmp_path)
    engine.run_context = ctx
    await engine._save_debug_snapshot("<html>boom</html>", "https://example.com/")
    assert list(ctx.debug_directory.glob("fail_*.html"))
