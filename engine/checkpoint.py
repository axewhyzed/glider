import sqlite3
import logging
from pathlib import Path
from typing import Set, List

logger = logging.getLogger("loguru")

class CheckpointManager:
    """
    Manages scrape state using a local SQLite database.
    Enables resuming interrupted jobs (Checkpointing).
    Uses two-phase commit to prevent data loss on crashes.
    """
    def __init__(self, config_name: str, enabled: bool = False):
        self.enabled = enabled
        self.db_path = Path("data") / "checkpoints.db"
        self.table_name = f"scrape_{config_name.replace(' ', '_').lower()}"
        self.conn = None
        self.cursor = None
        self._cache: Set[str] = set()

        if self.enabled:
            self._init_db()

    def _init_db(self):
        try:
            self.db_path.parent.mkdir(exist_ok=True)
            self.conn = sqlite3.connect(self.db_path)
            self.cursor = self.conn.cursor()
            # Create table if not exists
            self.cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT,
                    status TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
            # Load existing state into memory for fast lookups (only completed)
            self.cursor.execute(f"SELECT url FROM {self.table_name} WHERE status = 'done'")
            self._cache = {row[0] for row in self.cursor.fetchall()}
            logger.info(f"💾 Checkpoint loaded: {len(self._cache)} URLs previously scraped.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize checkpoint DB: {e}")
            self.enabled = False

    def is_done(self, url: str) -> bool:
        if not self.enabled:
            return False
        return url in self._cache

    def mark_in_progress(self, url: str):
        """
        Mark URL as currently being processed.
        This allows recovery of incomplete URLs on restart.
        """
        if not self.enabled or not self.conn or not self.cursor:
            return
        
        try:
            self.cursor.execute(
                f"INSERT OR REPLACE INTO {self.table_name} (url_hash, url, status) VALUES (?, ?, ?)",
                (url, url, "in_progress")
            )
            self.conn.commit()
        except Exception as e:
            logger.warning(f"⚠️ Failed to mark in-progress: {e}")

    def mark_done(self, url: str):
        """
        Mark URL as successfully completed.
        Updates status from 'in_progress' to 'done'.
        """
        if not self.enabled or not self.conn or not self.cursor:
            return
        
        try:
            self.cursor.execute(
                f"UPDATE {self.table_name} SET status = 'done', timestamp = CURRENT_TIMESTAMP WHERE url = ?",
                (url,)
            )
            self.conn.commit()
            self._cache.add(url)
        except Exception as e:
            logger.warning(f"⚠️ Failed to save checkpoint for {url}: {e}")

    def get_incomplete(self) -> List[str]:
        """
        Retrieve URLs that were in-progress during crash.
        These should be re-queued for processing.
        """
        if not self.enabled or not self.cursor:
            return []
        
        try:
            self.cursor.execute(
                f"SELECT url FROM {self.table_name} WHERE status = 'in_progress'"
            )
            incomplete = [row[0] for row in self.cursor.fetchall()]
            if incomplete:
                logger.warning(f"⚠️ Found {len(incomplete)} incomplete URLs from previous session")
            return incomplete
        except Exception as e:
            logger.error(f"❌ Failed to retrieve incomplete URLs: {e}")
            return []

    def close(self):
        if self.conn:
            self.conn.close()
