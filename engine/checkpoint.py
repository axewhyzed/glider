import sqlite3
import logging
from pathlib import Path
from typing import Set

logger = logging.getLogger("loguru")

class CheckpointManager:
    """
    Manages scrape state using a local SQLite database.
    Enables resuming interrupted jobs (Checkpointing).
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
            # Load existing state into memory for fast lookups
            self.cursor.execute(f"SELECT url FROM {self.table_name}")
            self._cache = {row[0] for row in self.cursor.fetchall()}
            logger.info(f"💾 Checkpoint loaded: {len(self._cache)} URLs previously scraped.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize checkpoint DB: {e}")
            self.enabled = False

    def is_done(self, url: str) -> bool:
        if not self.enabled:
            return False
        return url in self._cache

    def mark_done(self, url: str):
        # FIX: Explicitly check self.cursor to satisfy type checker safety
        if not self.enabled or not self.conn or not self.cursor:
            return
        
        try:
            self.cursor.execute(
                f"INSERT OR IGNORE INTO {self.table_name} (url_hash, url, status) VALUES (?, ?, ?)",
                (url, url, "done")
            )
            self.conn.commit()
            self._cache.add(url)
        except Exception as e:
            logger.warning(f"⚠️ Failed to save checkpoint for {url}: {e}")

    def close(self):
        if self.conn:
            self.conn.close()