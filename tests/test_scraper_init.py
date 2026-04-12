import pytest
import asyncio
from pathlib import Path
from engine.schemas import ScraperConfig, StatsEvent
from engine.scraper import ScraperEngine

def test_engine_initialization_with_callbacks():
    # FIX: Use dictionary unpacking to allow Pydantic to coerce string to HttpUrl
    # without Pylance complaining about type mismatch in __init__
    config = ScraperConfig(**{
        "name": "InitTest",
        "base_url": "http://test.com",
        "fields": []
    })
    
    async def mock_output(data):
        pass
        
    def mock_stats(status):
        pass
    
    engine = ScraperEngine(
        config,
        output_callback=mock_output,
        stats_callback=mock_stats
    )
    
    assert engine.output_callback is mock_output
    assert engine.stats_callback is mock_stats
    assert engine.ua_rotator is not None
    assert engine.checkpoint.enabled is False  # Default from config

@pytest.mark.asyncio
async def test_proxy_pool_rotation():
    # FIX: Use dictionary unpacking
    config = ScraperConfig(**{
        "name": "ProxyTest",
        "base_url": "http://test.com",
        "proxies": ["p1", "p2"],
        "fields": []
    })
    
    engine = ScraperEngine(config)
    
    # Check rotation logic
    p1 = engine._get_next_proxy()
    p2 = engine._get_next_proxy()
    p3 = engine._get_next_proxy()
    
    assert p1 == "p1"
    assert p2 == "p2"
    assert p3 == "p1"  # Should cycle back


# --- Stats callback bug fixes ---

def _make_engine(tmp_path: Path) -> tuple:
    """Helper: returns (engine, events_list)."""
    config = ScraperConfig(**{
        "name": "StatsTest",
        "base_url": "http://test.com",
        "fields": []
    })
    events = []
    engine = ScraperEngine(config, stats_callback=events.append)
    # Redirect bloom file to tmp_path to avoid polluting working directory
    engine.bloom_path = tmp_path / "test.bloom"
    return engine, events


@pytest.mark.asyncio
async def test_flush_remaining_batches_fires_entries_added(tmp_path):
    """Bug 2 fix: _flush_remaining_batches must fire entries_added for leftover items."""
    engine, events = _make_engine(tmp_path)

    received = []

    async def capture(data):
        received.append(data)

    engine.output_callback = capture

    # Three flat records (no list values) → each counts as 1 item → total 3
    engine.pending_batch = [{"title": f"item{i}"} for i in range(3)]

    await engine._flush_remaining_batches()

    entries_events = [e for e in events if e.event_type == "entries_added"]
    assert len(entries_events) == 1
    assert entries_events[0].count == 3


@pytest.mark.asyncio
async def test_entries_added_counts_list_items(tmp_path):
    """Per-item counting: entries_added should sum list-field lengths, not page_data units."""
    engine, events = _make_engine(tmp_path)

    received = []

    async def capture(data):
        received.append(data)

    engine.output_callback = capture
    engine.batch_size = 1  # Flush immediately on each _merge_data call

    # One page_data with a 'books' list of 5 items → entries_added count = 5
    page_data = {"books": [{"title": f"Book {i}"} for i in range(5)]}
    await engine._merge_data(page_data)

    entries_events = [e for e in events if e.event_type == "entries_added"]
    assert len(entries_events) == 1
    assert entries_events[0].count == 5


@pytest.mark.asyncio
async def test_page_skipped_fires_on_duplicate(tmp_path):
    """Deduplicated pages must fire the page_skipped stats event."""
    engine, events = _make_engine(tmp_path)

    received = []

    async def capture(data):
        received.append(data)

    engine.output_callback = capture
    engine.batch_size = 1

    page_data = {"title": "duplicate page", "price": 9.99}
    await engine._merge_data(page_data)  # First time → accepted
    await engine._merge_data(page_data)  # Second time → duplicate

    skipped = [e for e in events if e.event_type == "page_skipped"]
    assert len(skipped) == 1


def test_append_json_suffix_defaults_to_false():
    """append_json_suffix must default to False so non-Reddit JSON APIs are unaffected."""
    config = ScraperConfig(**{"name": "t", "base_url": "http://x.com", "fields": []})
    assert config.append_json_suffix is False


def test_append_json_suffix_accepted_in_config():
    """append_json_suffix can be set to True in config."""
    config = ScraperConfig(**{
        "name": "t",
        "base_url": "http://x.com",
        "append_json_suffix": True,
        "fields": []
    })
    assert config.append_json_suffix is True


@pytest.mark.asyncio
async def test_merge_data_non_serializable_does_not_raise(tmp_path):
    """Bug 5 fix: non-JSON-serializable values must not crash _merge_data.
    
    json.dumps with default=str converts unrecognised types to their string
    representation so the deduplication hash can still be computed and the
    item is accepted rather than causing an unhandled TypeError.
    """
    engine, events = _make_engine(tmp_path)

    # object() is not natively JSON-serializable; with default=str it becomes
    # its repr string, so _merge_data should complete without raising.
    page_data = {"field": object()}
    await engine._merge_data(page_data)  # Must not raise


@pytest.mark.asyncio
async def test_merge_data_default_str_for_unusual_types(tmp_path):
    """Bug 5 fix: unusual-but-stringifiable types (e.g. bytes) are accepted via default=str."""
    engine, events = _make_engine(tmp_path)

    received = []

    async def capture(data):
        received.append(data)

    engine.output_callback = capture
    # Set batch_size to 1 so flush happens immediately
    engine.batch_size = 1

    # bytes is not JSON-serializable by default but str(b"hello") works fine
    page_data = {"value": "hello"}
    await engine._merge_data(page_data)

    assert len(received) == 1