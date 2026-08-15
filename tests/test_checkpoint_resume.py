"""Resume/crash integration tests for the kind-aware checkpoint.

Phase 2 (P2.10): resume must select only resumable root/pagination work for
pagination, only resumable nested work for nested processing, keep transitions
atomic and idempotent under concurrent workers, and never collide across two
independent simultaneous runs.
"""

import asyncio

import pytest

from engine.checkpoint import CheckpointManager


@pytest.fixture
async def manager(tmp_path):
    mgr = CheckpointManager("resume_test", enabled=True, db_path=tmp_path / "checkpoint.sqlite")
    await mgr.initialize()
    yield mgr
    await mgr.close()


# ------------------------------------------------- kind-aware resume selection

async def test_resume_selects_only_pagination_work(manager):
    """A nested URL marked in_progress must not appear as pagination resume work."""
    await manager.mark_in_progress("https://site.com/root", kind="pagination")
    await manager.mark_in_progress("https://site.com/child", kind="nested", parent_url="https://site.com/root")

    pagination = await manager.get_incomplete_items(kind="pagination")
    assert [item["url"] for item in pagination] == ["https://site.com/root"]

    nested = await manager.get_incomplete_items(kind="nested")
    assert [item["url"] for item in nested] == ["https://site.com/child"]
    assert nested[0]["parent_url"] == "https://site.com/root"


async def test_resume_selects_root_for_list_mode(manager):
    await manager.mark_in_progress("https://site.com/a", kind="root")
    await manager.mark_in_progress("https://site.com/p2", kind="pagination")
    roots = await manager.get_incomplete_items(kind="root")
    assert [item["url"] for item in roots] == ["https://site.com/a"]


# ------------------------------------------------------------ atomic/idempotent

async def test_mark_done_is_idempotent_and_overrides_failed(manager):
    url = "https://site.com/p2"
    await manager.mark_in_progress(url, kind="pagination")
    await manager.mark_failed(url, kind="pagination", error="boom")
    assert manager.is_done(url, kind="pagination") is False

    await manager.mark_done(url, kind="pagination")
    assert manager.is_done(url, kind="pagination") is True
    # Marking done twice must not raise or flip state.
    await manager.mark_done(url, kind="pagination")
    assert manager.is_done(url, kind="pagination") is True

    # After done, it is no longer resumable.
    assert await manager.get_incomplete_items(kind="pagination") == []


async def test_failed_items_are_resumable(manager):
    url = "https://site.com/retry"
    await manager.mark_in_progress(url, kind="pagination")
    await manager.mark_failed(url, kind="pagination", error="503")
    incomplete = await manager.get_incomplete_items(kind="pagination")
    assert [item["url"] for item in incomplete] == [url]


async def test_concurrent_marks_are_consistent(manager):
    """P2.4: concurrent workers marking the same URL settle on a single state."""
    url = "https://site.com/contended"
    await asyncio.gather(
        *(manager.mark_in_progress(url, kind="pagination") for _ in range(8))
    )
    await asyncio.gather(*(manager.mark_done(url, kind="pagination") for _ in range(8)))
    assert manager.is_done(url, kind="pagination") is True
    assert await manager.get_incomplete_items(kind="pagination") == []


# ------------------------------------------------------------- crash simulation

async def test_interrupted_run_resumes_incomplete_only(manager):
    """Simulate a crash: done work is not redone, in-progress work is resumable."""
    done_url = "https://site.com/done"
    pending_url = "https://site.com/pending"
    await manager.mark_done(done_url, kind="pagination")
    await manager.mark_in_progress(pending_url, kind="pagination")

    # New manager instance (fresh process) reads the same database.
    resume = CheckpointManager("resume_test", enabled=True, db_path=manager.db_path)
    await resume.initialize()
    try:
        assert resume.is_done(done_url, kind="pagination") is True
        assert resume.is_done(pending_url, kind="pagination") is False
        pending = await resume.get_incomplete_items(kind="pagination")
        assert [item["url"] for item in pending] == [pending_url]
    finally:
        await resume.close()


async def test_visited_table_migrated_to_generic_kind(tmp_path):
    """Legacy 'visited' rows surface as generic-kind crawl items for old runs."""
    import sqlite3
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE visited (url TEXT PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO visited VALUES ('http://legacy.com/', 'done')")
    conn.commit()
    conn.close()

    mgr = CheckpointManager("legacy", enabled=True, db_path=db)
    await mgr.initialize()
    try:
        assert mgr.is_done("http://legacy.com/") is True
    finally:
        await mgr.close()


# ----------------------------------------------------- simultaneous run safety

async def test_two_independent_runs_do_not_collide(tmp_path):
    """P2.8/P2.10: two runs (same config name) use separate databases."""
    db_a = tmp_path / "run_a.sqlite"
    db_b = tmp_path / "run_b.sqlite"
    mgr_a = CheckpointManager("same_config", enabled=True, db_path=db_a)
    mgr_b = CheckpointManager("same_config", enabled=True, db_path=db_b)
    await mgr_a.initialize()
    await mgr_b.initialize()
    try:
        await mgr_a.mark_done("https://site.com/a", kind="pagination")
        await mgr_b.mark_done("https://site.com/b", kind="pagination")
        # Each run only sees its own state.
        assert mgr_a.is_done("https://site.com/a", kind="pagination") is True
        assert mgr_a.is_done("https://site.com/b", kind="pagination") is False
        assert mgr_b.is_done("https://site.com/b", kind="pagination") is True
        assert mgr_b.is_done("https://site.com/a", kind="pagination") is False
    finally:
        await mgr_a.close()
        await mgr_b.close()


# ---------------------------------------------------------------- disabled mode

async def test_disabled_manager_never_returns_work(manager):
    off = CheckpointManager("off", enabled=False)
    await off.mark_in_progress("https://site.com/x", kind="pagination")
    assert off.is_done("https://site.com/x", kind="pagination") is False
    assert await off.get_incomplete_items(kind="pagination") == []
    await off.close()
