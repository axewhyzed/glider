import pytest
import pytest_asyncio
from pathlib import Path
from engine.checkpoint import CheckpointManager


@pytest_asyncio.fixture
async def temp_checkpoint(tmp_path):
    """Provides an initialized CheckpointManager backed by a temp SQLite file."""
    manager = CheckpointManager("test_config", enabled=True)
    manager.db_path = tmp_path / "test_checkpoints.db"
    await manager.initialize()
    yield manager
    await manager.close()


def test_checkpoint_disabled():
    """Disabled manager always reports not-done and ignores marks."""
    manager = CheckpointManager("test", enabled=False)
    assert manager.is_done("http://example.com") is False


@pytest.mark.asyncio
async def test_mark_and_check_done(temp_checkpoint):
    url = "http://example.com/page1"

    assert temp_checkpoint.is_done(url) is False

    await temp_checkpoint.mark_done(url)

    assert temp_checkpoint.is_done(url) is True


@pytest.mark.asyncio
async def test_mark_in_progress(temp_checkpoint):
    url = "http://example.com/progress"

    await temp_checkpoint.mark_in_progress(url)
    incomplete = await temp_checkpoint.get_incomplete()

    assert url in incomplete
    assert temp_checkpoint.is_done(url) is False


@pytest.mark.asyncio
async def test_persistence(tmp_path):
    """State (done URLs) persists across separate manager instances."""
    db_file = tmp_path / "persistent.db"
    url = "http://persist.com"

    # Run 1: save state
    mgr1 = CheckpointManager("persist_test", enabled=True)
    mgr1.db_path = db_file
    await mgr1.initialize()
    await mgr1.mark_done(url)
    await mgr1.close()

    # Run 2: load state
    mgr2 = CheckpointManager("persist_test", enabled=True)
    mgr2.db_path = db_file
    await mgr2.initialize()

    assert mgr2.is_done(url) is True
    await mgr2.close()