"""Deduplication tests (P7.1-P7.3)."""

import pytest

from engine.schemas import DedupConfig, DedupMode, ScraperConfig
from engine.scraper import ScraperEngine


def _make_engine(tmp_path, dedup=None):
    config = ScraperConfig(
        name="dedup",
        base_url="https://example.com",
        fields=[],
        dedup=dedup or DedupConfig(),
    )
    engine = ScraperEngine(config)
    engine.bloom_path = tmp_path / "dedupe.bloom"
    engine.batch_size = 1
    return engine


async def _collect(engine, page_datas):
    captured = []

    async def capture(value):
        captured.append(value)

    engine.output_callback = capture
    for page_data in page_datas:
        await engine._merge_data(page_data)
    await engine._flush_remaining_batches()
    return captured


def test_dedup_mode_exact_hash_is_default():
    config = ScraperConfig(name="t", base_url="https://example.com", fields=[])
    assert config.dedup.mode == DedupMode.EXACT_HASH


async def test_dedup_mode_none_emits_everything(tmp_path):
    engine = _make_engine(tmp_path, DedupConfig(mode=DedupMode.NONE))
    captured = await _collect(engine, [
        {"title": "same"},
        {"title": "same"},
        {"title": "same"},
    ])
    assert len(captured) == 3


async def test_dedup_exact_hash_skips_duplicates(tmp_path):
    engine = _make_engine(tmp_path)
    captured = await _collect(engine, [
        {"title": "x", "price": 1},
        {"title": "x", "price": 1},
    ])
    assert len(captured) == 1


async def test_dedup_mode_url_keeps_distinct_urls(tmp_path):
    engine = _make_engine(tmp_path, DedupConfig(mode=DedupMode.URL))
    captured = await _collect(engine, [
        {"title": "same"},
        {"title": "same"},
    ])
    # URL mode keys on source_url; both have source_url=None -> "" -> duplicate.
    assert len(captured) == 1

    # Distinct URLs emit both.
    captured2 = []
    async def capture2(value):
        captured2.append(value)
    engine.output_callback = capture2
    engine.exact_seen.clear()
    await engine._merge_data({"title": "a"}, source_url="https://x.com/1")
    await engine._merge_data({"title": "b"}, source_url="https://x.com/2")
    await engine._flush_remaining_batches()
    assert len(captured2) == 2


async def test_dedup_mode_fields_keys_on_selected_fields(tmp_path):
    engine = _make_engine(tmp_path, DedupConfig(mode=DedupMode.FIELDS, fields=["id"]))
    captured = await _collect(engine, [
        {"id": 1, "note": "first"},
        {"id": 1, "note": "second"},  # same key field -> duplicate
        {"id": 2, "note": "third"},
    ])
    assert len(captured) == 2


async def test_false_positive_does_not_drop_unique(tmp_path, monkeypatch):
    engine = _make_engine(tmp_path)
    # Force Bloom to say "maybe present" for everything.
    engine.seen_hashes.__contains__ = lambda item: True  # type: ignore[assignment]
    captured = await _collect(engine, [{"title": "unique-1"}])
    # Exact confirmation wins: the unique item is emitted.
    assert len(captured) == 1
    assert captured[0]["items"][0]["title"] == "unique-1"


async def test_back_to_back_duplicates_skipped_via_exact_set(tmp_path):
    engine = _make_engine(tmp_path)
    captured = await _collect(engine, [
        {"title": "dup"},
        {"title": "dup"},
        {"title": "other"},
    ])
    assert len(captured) == 2


async def test_recent_hashes_removed(tmp_path):
    engine = _make_engine(tmp_path)
    assert not hasattr(engine, "recent_hashes")


async def test_dedup_none_skips_bloom_io(tmp_path):
    engine = _make_engine(tmp_path, DedupConfig(mode=DedupMode.NONE))
    # Bloom save is still called in cleanup, but no keys are added.
    await engine._merge_data({"a": 1})
    assert engine.seen_hashes.item_count == 0
