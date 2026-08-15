"""JsonlStreamWriter tests (P7.6)."""

import json

import pytest

from engine.scraper import ScraperEngine
from engine.schemas import ScraperConfig
from engine.writer import JsonlStreamWriter


async def test_writer_writes_valid_jsonl(tmp_path):
    path = tmp_path / "stream.jsonl"
    writer = JsonlStreamWriter(path)
    await writer.write({"items": [{"a": 1}]})
    await writer.write({"items": [{"b": 2}]})
    await writer.write({"items": [{"c": 3}]})
    await writer.close()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    for line in lines:
        json.loads(line)


async def test_writer_flushes_per_write(tmp_path):
    path = tmp_path / "stream.jsonl"
    writer = JsonlStreamWriter(path)
    await writer.write({"items": [{"x": 1}]})
    # Readable without close.
    assert path.read_text(encoding="utf-8").strip()
    await writer.close()


async def test_writer_append_mode(tmp_path):
    path = tmp_path / "stream.jsonl"
    writer = JsonlStreamWriter(path)
    await writer.write({"items": [{"a": 1}]})
    await writer.close()
    writer2 = JsonlStreamWriter(path)
    await writer2.write({"items": [{"b": 2}]})
    await writer2.close()
    assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2


async def test_writer_close_idempotent(tmp_path):
    writer = JsonlStreamWriter(tmp_path / "s.jsonl")
    await writer.open()
    await writer.close()
    await writer.close()  # second close is a no-op


async def test_engine_flush_uses_writer_when_provided(tmp_path):
    config = ScraperConfig(name="w", base_url="https://example.com", fields=[])
    writer = JsonlStreamWriter(tmp_path / "out.jsonl")
    engine = ScraperEngine(config, stream_writer=writer)
    engine.batch_size = 1
    called = []

    async def capture(value):
        called.append(value)

    engine.output_callback = capture
    await engine._merge_data({"title": "x"})
    await engine._flush_remaining_batches()
    assert called == []  # writer wins over callback
    await writer.close()
    content = (tmp_path / "out.jsonl").read_text(encoding="utf-8")
    assert "title" in content


async def test_engine_flush_uses_callback_when_no_writer(tmp_path):
    config = ScraperConfig(name="w", base_url="https://example.com", fields=[])
    engine = ScraperEngine(config)
    engine.batch_size = 1
    called = []

    async def capture(value):
        called.append(value)

    engine.output_callback = capture
    await engine._merge_data({"title": "x"})
    await engine._flush_remaining_batches()
    assert len(called) == 1


async def test_writer_closed_on_engine_cleanup(tmp_path):
    config = ScraperConfig(name="w", base_url="https://example.com", fields=[])
    writer = JsonlStreamWriter(tmp_path / "out.jsonl")
    engine = ScraperEngine(config, stream_writer=writer)
    await writer.open()
    await engine._cleanup_resources()
    assert writer._file is None  # closed by engine
