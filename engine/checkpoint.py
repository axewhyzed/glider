"""Typed, run-scoped checkpoint state with safe legacy compatibility."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite
from loguru import logger


class CheckpointManager:
    """Persist crawl work by URL *and semantic kind*.

    The old implementation used one URL-only table. A composite key keeps a
    nested URL from being confused with a pagination URL and allows the same
    resource to be attached to more than one parent.
    """

    def __init__(self, name: str, enabled: bool = True, db_path: Optional[Path] = None):
        self.enabled = enabled
        self.db_path = db_path or (Path("data") / f"{name.replace(' ', '_').lower()}.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Set[Tuple[str, str]] = set()
        self._done_urls: Set[str] = set()
        self._db_conn: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        if not self.enabled:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_conn = await aiosqlite.connect(self.db_path, timeout=30.0)
        await self._db_conn.execute("PRAGMA journal_mode=WAL")
        await self._db_conn.execute("PRAGMA foreign_keys=ON")
        await self._db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_items (
                url TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'generic',
                status TEXT NOT NULL,
                parent_url TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                PRIMARY KEY (url, kind)
            )
            """
        )
        # Guarded migration: add the depth column to databases created before
        # cycle detection existed.
        async with self._db_conn.execute("PRAGMA table_info(crawl_items)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        if "depth" not in columns:
            await self._db_conn.execute(
                "ALTER TABLE crawl_items ADD COLUMN depth INTEGER NOT NULL DEFAULT 0"
            )
        await self._db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS child_results (
                url TEXT NOT NULL,
                parent_url TEXT NOT NULL,
                field_key TEXT NOT NULL,
                record TEXT NOT NULL,
                PRIMARY KEY (url, parent_url, field_key)
            )
            """
        )
        await self._db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visited (
                url TEXT PRIMARY KEY,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await self._db_conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedup_keys (
                key TEXT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Migrate legacy rows. ``visited`` may or may not have a timestamp
        # column depending on when the database was created, so select only
        # columns that are guaranteed to exist.
        await self._db_conn.execute(
            """
            INSERT OR IGNORE INTO crawl_items(url, kind, status)
            SELECT url, 'generic', status FROM visited
            """
        )
        await self._db_conn.commit()

        async with self._db_conn.execute(
            "SELECT url, kind FROM crawl_items WHERE status = 'done'"
        ) as cursor:
            rows = await cursor.fetchall()
        self._cache = {(row[0], row[1]) for row in rows}
        self._done_urls = {row[0] for row in rows}
        logger.info(f"Loaded {len(self._cache)} completed checkpoint items")

    async def mark_in_progress(self, url: str, kind: str = "generic", parent_url: Optional[str] = None, depth: int = 0):
        if not self.enabled or not self._db_conn:
            return
        try:
            await self._db_conn.execute(
                """
                INSERT INTO crawl_items(url, kind, status, parent_url, attempts, depth)
                VALUES (?, ?, 'in_progress', ?, 1, ?)
                ON CONFLICT(url, kind) DO UPDATE SET
                    status = 'in_progress',
                    parent_url = COALESCE(excluded.parent_url, crawl_items.parent_url),
                    attempts = crawl_items.attempts + 1,
                    last_error = NULL,
                    depth = excluded.depth,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (url, kind, parent_url, depth),
            )
            await self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"Checkpoint Error: {exc}")

    async def mark_done(self, url: str, kind: str = "generic"):
        if not self.enabled or not self._db_conn:
            return
        try:
            await self._db_conn.execute(
                """
                INSERT INTO crawl_items(url, kind, status, completed_at)
                VALUES (?, ?, 'done', CURRENT_TIMESTAMP)
                ON CONFLICT(url, kind) DO UPDATE SET
                    status = 'done', last_error = NULL,
                    completed_at = CURRENT_TIMESTAMP, timestamp = CURRENT_TIMESTAMP
                """,
                (url, kind),
            )
            await self._db_conn.commit()
            # Do not claim completion in memory until the durable transition
            # has committed; otherwise a transient SQLite failure can cause
            # the current process to skip work that was never persisted.
            self._cache.add((url, kind))
            self._done_urls.add(url)
        except Exception as exc:
            logger.warning(f"Checkpoint Error: {exc}")

    async def mark_failed(self, url: str, kind: str = "generic", error: str = ""):
        if not self.enabled or not self._db_conn:
            return
        try:
            await self._db_conn.execute(
                """
                INSERT INTO crawl_items(url, kind, status, last_error)
                VALUES (?, ?, 'failed', ?)
                ON CONFLICT(url, kind) DO UPDATE SET
                    status = 'failed', last_error = excluded.last_error,
                    timestamp = CURRENT_TIMESTAMP
                """,
                (url, kind, error[:4000]),
            )
            await self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"Checkpoint Error: {exc}")

    async def get_incomplete(self, kind: Optional[str] = None) -> List[str]:
        if not self.enabled or not self._db_conn:
            return []
        try:
            query = "SELECT url FROM crawl_items WHERE status IN ('in_progress', 'failed')"
            params: tuple = ()
            if kind:
                query += " AND kind = ?"
                params = (kind,)
            async with self._db_conn.execute(query, params) as cursor:
                rows = await cursor.fetchall()
            return [row[0] for row in rows]
        except Exception:
            return []

    async def get_incomplete_items(self, kind: Optional[str] = None) -> List[Dict[str, str]]:
        if not self.enabled or not self._db_conn:
            return []
        query = "SELECT url, kind, parent_url FROM crawl_items WHERE status IN ('in_progress', 'failed')"
        params: tuple = ()
        if kind:
            query += " AND kind = ?"
            params = (kind,)
        async with self._db_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [{"url": row[0], "kind": row[1], "parent_url": row[2]} for row in rows]

    async def get_done_nested_urls(self) -> Set[str]:
        """All child URLs marked done (for fetch-level dedup on resume)."""
        if not self.enabled or not self._db_conn:
            return set()
        query = "SELECT url FROM crawl_items WHERE kind = 'nested' AND status = 'done'"
        async with self._db_conn.execute(query) as cursor:
            rows = await cursor.fetchall()
        return {row[0] for row in rows}

    async def get_dedup_keys(self, limit: Optional[int] = None) -> List[str]:
        """Load authoritative exact-dedup keys for a resumed run."""
        if not self.enabled or not self._db_conn:
            return []
        query = "SELECT key FROM dedup_keys ORDER BY rowid DESC"
        params = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        async with self._db_conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    async def mark_dedup_key(self, key: str, max_keys: Optional[int] = None) -> None:
        """Persist an exact key atomically; optionally evict oldest keys."""
        if not self.enabled or not self._db_conn:
            return
        try:
            await self._db_conn.execute(
                "INSERT OR IGNORE INTO dedup_keys(key) VALUES (?)", (key,)
            )
            if max_keys is not None:
                await self._db_conn.execute(
                    "DELETE FROM dedup_keys WHERE key IN "
                    "(SELECT key FROM dedup_keys ORDER BY rowid ASC LIMIT "
                    "MAX(0, (SELECT COUNT(*) FROM dedup_keys) - ?))",
                    (max_keys,),
                )
            await self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"Checkpoint dedup error: {exc}")

    async def mark_child_result(self, url: str, parent_url: str, field_key: str, record_json: str):
        """Persist an extracted child record for resume re-attachment (P4.6)."""
        if not self.enabled or not self._db_conn:
            return
        try:
            await self._db_conn.execute(
                """
                INSERT OR REPLACE INTO child_results(url, parent_url, field_key, record)
                VALUES (?, ?, ?, ?)
                """,
                (url, parent_url, field_key, record_json),
            )
            await self._db_conn.commit()
        except Exception as exc:
            logger.warning(f"Checkpoint Error: {exc}")

    async def get_child_results(self, url: str, field_key: str) -> Dict[str, str]:
        """All persisted records for a child URL + field key, keyed by parent."""
        if not self.enabled or not self._db_conn:
            return {}
        try:
            query = "SELECT parent_url, record FROM child_results WHERE url = ? AND field_key = ?"
            async with self._db_conn.execute(query, (url, field_key)) as cursor:
                rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception:
            return {}

    def is_done(self, url: str, kind: Optional[str] = None) -> bool:
        """Return completion state, preferably scoped to a semantic kind.

        Passing ``kind`` is required for typed resume decisions.  The
        URL-only form is retained for legacy callers and means that *any*
        completed kind for the URL makes the result true; it must not be used
        to decide whether a root, pagination, or nested item is complete.
        """
        if kind:
            return (url, kind) in self._cache
        return url in self._done_urls

    async def close(self):
        if self._db_conn:
            await self._db_conn.close()
            self._db_conn = None
