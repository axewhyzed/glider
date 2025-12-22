import aiosqlite
import logging
from pathlib import Path
from typing import Set, List, Optional

logger = logging.getLogger("loguru")

class CheckpointManager:
    """
    Async Checkpoint Manager using aiosqlite.
    Prevents event loop blocking and SQL injection.
    """
    def __init__(self, config_name: str, enabled: bool = False):
        self.config_name = config_name
        self.enabled = enabled
        self.db_path = Path("data") / "checkpoints.db"
        self._cache: Set[str] = set()
        self._initialized = False

    async def initialize(self):
        """Async initialization of DB connection and schema."""
        if not self.enabled:
            return

        try:
            self.db_path.parent.mkdir(exist_ok=True)
            async with aiosqlite.connect(self.db_path) as db:
                # Fixed schema with job_name column (Prevents SQL Injection)
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS checkpoints (
                        job_name TEXT,
                        url_hash TEXT,
                        url TEXT,
                        status TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (job_name, url_hash)
                    )
                """)
                await db.commit()
                
                # Load cache
                async with db.execute(
                    "SELECT url FROM checkpoints WHERE job_name = ? AND status = 'done'",
                    (self.config_name,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    self._cache = {row[0] for row in rows}
            
            self._initialized = True
            logger.info(f"💾 Checkpoint loaded: {len(self._cache)} URLs done.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize checkpoint DB: {e}")
            self.enabled = False

    def is_done(self, url: str) -> bool:
        if not self.enabled:
            return False
        return url in self._cache

    async def mark_in_progress(self, url: str):
        if not self.enabled or not self._initialized:
            return
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO checkpoints (job_name, url_hash, url, status) VALUES (?, ?, ?, ?)",
                    (self.config_name, url, url, "in_progress")
                )
                await db.commit()
        except Exception as e:
            logger.warning(f"⚠️ Checkpoint write failed: {e}")

    async def mark_done(self, url: str):
        if not self.enabled or not self._initialized:
            return
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE checkpoints SET status = 'done', timestamp = CURRENT_TIMESTAMP WHERE job_name = ? AND url = ?",
                    (self.config_name, url)
                )
                await db.commit()
            self._cache.add(url)
        except Exception as e:
            logger.warning(f"⚠️ Checkpoint update failed: {e}")

    async def get_incomplete(self) -> List[str]:
        if not self.enabled or not self._initialized:
            return []
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT url FROM checkpoints WHERE job_name = ? AND status = 'in_progress'",
                    (self.config_name,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"❌ Failed to retrieve incomplete URLs: {e}")
            return []

    async def close(self):
        # aiosqlite manages connections per context manager usually, 
        # but if we held a persistent connection we would close it here.
        pass