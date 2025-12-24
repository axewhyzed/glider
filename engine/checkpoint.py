import aiosqlite
from pathlib import Path
from typing import List, Set, Optional
from loguru import logger

class CheckpointManager:
    def __init__(self, name: str, enabled: bool = True):
        self.enabled = enabled
        self.db_path = Path("data") / f"{name.replace(' ', '_').lower()}.db"
        self.db_path.parent.mkdir(exist_ok=True)
        self._cache: Set[str] = set()
        self._db_conn: Optional[aiosqlite.Connection] = None  # [FIX #4] Shared Connection

    async def initialize(self):
        if not self.enabled: return
        
        # Open persistent connection
        self._db_conn = await aiosqlite.connect(self.db_path, timeout=30.0)
        
        # Enable WAL mode for concurrency
        await self._db_conn.execute("PRAGMA journal_mode=WAL")
        
        await self._db_conn.execute("""
            CREATE TABLE IF NOT EXISTS visited (
                url TEXT PRIMARY KEY,
                status TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._db_conn.commit()
        
        async with self._db_conn.execute("SELECT url FROM visited WHERE status = 'done'") as cursor:
            rows = await cursor.fetchall()
            self._cache = {row[0] for row in rows}
        
        logger.info(f"📁 Loaded {len(self._cache)} URLs from checkpoint")

    async def mark_in_progress(self, url: str):
        if not self.enabled or not self._db_conn: return
        try:
            await self._db_conn.execute(
                "INSERT OR REPLACE INTO visited (url, status) VALUES (?, 'in_progress')",
                (url,)
            )
            await self._db_conn.commit()
        except Exception as e:
            logger.warning(f"Checkpoint Error: {e}")

    async def mark_done(self, url: str):
        if not self.enabled or not self._db_conn: return
        self._cache.add(url)
        try:
            await self._db_conn.execute(
                "UPDATE visited SET status = 'done' WHERE url = ?",
                (url,)
            )
            await self._db_conn.commit()
        except Exception as e:
            logger.warning(f"Checkpoint Error: {e}")

    async def get_incomplete(self) -> List[str]:
        if not self.enabled or not self._db_conn: return []
        try:
            async with self._db_conn.execute("SELECT url FROM visited WHERE status = 'in_progress'") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception:
            return []

    def is_done(self, url: str) -> bool:
        return url in self._cache

    async def close(self):
        if self._db_conn:
            await self._db_conn.close()
            self._db_conn = None