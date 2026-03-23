import logging
from pathlib import Path

import aiosqlite

class SQLiteHandler:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.sqlite_path = self.storage_dir / "client.db"
        self._logger = logging.getLogger(self.__class__.__name__)

    async def _init_database(self):
        try:
            async with aiosqlite.connect(self.sqlite_path) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS self_adverts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        snr REAL,
                        rssi INTEGER
                    )
                """)
                
                await conn.commit()
                self._logger.info(f"SQLite database initialized at {self.sqlite_path}")
        except:
            self._logger.critical("Failed to initialize db", exc_info=True)