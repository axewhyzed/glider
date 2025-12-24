import aiosqlite
from pathlib import Path
from typing import List, Set
from loguru import logger

class CheckpointManager:
    def __init__(self, name: str, enabled: bool = True):
        self.enabled = enabled
        self.db_path = Path("data") / f"{name.replace(' ', '_').lower()}.db"
        self.db_path.parent.mkdir(exist_ok=True)
        self._cache: Set[str] = set()

    async def initialize(self):
        if not self.enabled: return
        
        # [FIXED] Added timeout to prevent locking hangs
        async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS visited (
                    url TEXT PRIMARY KEY,
                    status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            
            async with db.execute("SELECT url FROM visited WHERE status = 'done'") as cursor:
                rows = await cursor.fetchall()
                self._cache = {row[0] for row in rows}
        
        logger.info(f"📁 Loaded {len(self._cache)} URLs from checkpoint")

    async def mark_in_progress(self, url: str):
        if not self.enabled: return
        try:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO visited (url, status) VALUES (?, 'in_progress')",
                    (url,)
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"Checkpoint Error: {e}")

    async def mark_done(self, url: str):
        if not self.enabled: return
        self._cache.add(url)
        try:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                await db.execute(
                    "UPDATE visited SET status = 'done' WHERE url = ?",
                    (url,)
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"Checkpoint Error: {e}")

    async def get_incomplete(self) -> List[str]:
        if not self.enabled: return []
        try:
            async with aiosqlite.connect(self.db_path, timeout=30.0) as db:
                async with db.execute("SELECT url FROM visited WHERE status = 'in_progress'") as cursor:
                    rows = await cursor.fetchall()
                    return [row[0] for row in rows]
        except Exception:
            return []

    def is_done(self, url: str) -> bool:
        return url in self._cache

    async def close(self):
        pass