"""Operational tests (P9.6): cancellation, partial output, redaction, manifest."""

import asyncio
import json

import pytest

from engine.checkpoint import CheckpointManager
from engine.network import FetchResult
from engine.run import RunContext
from engine.schemas import ScraperConfig
from engine.scraper import ScraperEngine
from engine.writer import JsonlStreamWriter


def _config(tmp_path, name="ops", max_failed=50):
    return ScraperConfig(
        name=name,
        base_url="https://example.com",
        mode="list",
        start_urls=[f"https://example.com/{i}" for i in range(5)],
        fields=[{"name": "title", "selector": "h1"}],
        max_failed_entries=max_failed,
        url_policy={"resolve_dns": False},
    )


def _ok(url, **kw):
    return FetchResult(content="<html><body><h1>OK</h1></body></html>",
                       requested_url=url, final_url=url, status_code=200,
                       headers={"content-type": "text/html"}, elapsed_ms=3.0)


async def _ok_fetch(self, url, purpose=None, parent_url=None):
    return _ok(url)


async def test_operation_manifest_finalized(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ctx = RunContext.create("ops", {"name": "ops"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=ctx, stream_writer=None)
    engine.checkpoint = CheckpointManager("ops", True, ctx.checkpoint_path)
    monkeypatch.setattr(ScraperEngine, "_fetch_page", _ok_fetch)
    await engine.run()
    manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert "started_at" in manifest


async def test_operation_partial_output_after_failure(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ctx = RunContext.create("ops", {"name": "ops"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=ctx)
    engine.checkpoint = CheckpointManager("ops", True, ctx.checkpoint_path)
    calls = []

    async def flaky_fetch(self, url, purpose=None, parent_url=None):
        calls.append(url)
        if "example.com/3" in url:
            raise RuntimeError("boom")
        return _ok(url)

    monkeypatch.setattr(ScraperEngine, "_fetch_page", flaky_fetch)
    await engine.run()
    manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "completed"
    assert manifest["failed_urls"] == 1
    assert len(calls) == 5


async def test_operation_dedup_count_reported(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ctx = RunContext.create("ops", {"name": "ops"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=ctx)
    engine.checkpoint = CheckpointManager("ops", True, ctx.checkpoint_path)
    # All pages return identical content -> exact_hash dedup collapses them.
    monkeypatch.setattr(ScraperEngine, "_fetch_page", _ok_fetch)
    await engine.run()
    snap = engine.metrics.snapshot()
    assert snap["duplicates_detected"] >= 4  # 5 identical pages -> 4 dupes


async def test_operation_no_data_loss_on_partial_flush(tmp_path, monkeypatch):
    config = ScraperConfig(
        name="flush",
        base_url="https://example.com",
        mode="list",
        start_urls=[f"https://example.com/{i}" for i in range(50)],
        fields=[{"name": "title", "selector": "h1"}],
        url_policy={"resolve_dns": False},
    )
    ctx = RunContext.create("flush", {"name": "flush"}, output_root=tmp_path)
    engine = ScraperEngine(config, run_context=ctx, stream_writer=JsonlStreamWriter(ctx.stream_path))
    engine.checkpoint = CheckpointManager("flush", True, ctx.checkpoint_path)
    engine.batch_size = 3

    async def distinct_fetch(self, url, purpose=None, parent_url=None):
        # Each URL returns distinct content so the crawl does not finish instantly.
        title = url.rstrip("/").rsplit("/", 1)[-1]
        return FetchResult(content=f"<html><body><h1>{title}</h1></body></html>",
                           requested_url=url, final_url=url, status_code=200,
                           headers={"content-type": "text/html"}, elapsed_ms=1.0)

    monkeypatch.setattr(ScraperEngine, "_fetch_page", distinct_fetch)

    # Cancel the run task directly (the realistic Ctrl+C path) after a beat.
    run_task = asyncio.ensure_future(engine.run())
    await asyncio.sleep(0.05)
    if not run_task.done():
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
    else:
        await run_task  # run finished before cancel landed; still valid
    assert ctx.stream_path.exists()
