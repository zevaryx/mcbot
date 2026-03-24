import binascii
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite
from pymc_core import Packet
from pymc_core.companion.models import Contact

if TYPE_CHECKING:
    from mcbot.settings import Settings
    
SQL_CREATE_CONTACTS = """
CREATE TABLE IF NOT EXISTS "contacts" (
    "id"	INTEGER,
    "public_key"	TEXT NOT NULL UNIQUE,
    "adv_type"	INTEGER DEFAULT 0,
    "flags"	INTEGER DEFAULT 0,
    "out_path_len"	INTEGER DEFAULT -1,
    "out_path"	BLOB,
    "last_advert_timestamp"	INTEGER DEFAULT 0,
    "last_mod"	INTEGER DEFAULT 0,
    "gps_lat"	NUMERIC DEFAULT 0.0,
    "gps_lon"	NUMERIC DEFAULT 0.0,
    "sync_since"	INTEGER DEFAULT 0,
    PRIMARY KEY("id" AUTOINCREMENT)
);
"""

SQL_CREATE_LAST_ADVERT = """
CREATE TABLE IF NOT EXISTS "last_advert" (
    "id"	INTEGER,
    "last_advert_timestamp"	INTEGER DEFAULT 0,
    PRIMARY KEY("id" AUTOINCREMENT)
)
"""

SQL_INSERT_CONTACT = """
INSERT INTO contacts (
    public_key,
    adv_type,
    flags,
    out_path_len,
    out_path,
    last_advert_timestamp,
    last_mod,
    gps_lat,
    gps_lon,
    sync_since
) VALUES (
    :public_key,
    :adv_type,
    :flags,
    :out_path_len,
    :out_path,
    :last_advert_timestamp,
    :last_mod,
    :gps_lat,
    :gps_lon,
    :sync_since
)
ON CONFLICT(public_key) DO UPDATE SET
    public_key=excluded.public_key,
    adv_type=excluded.adv_type,
    flags=excluded.flags,
    out_path_len=excluded.out_path_len,
    out_path=excluded.out_path,
    last_advert_timestamp=excluded.last_advert_timestamp,
    last_mod=excluded.last_mod,
    gps_lat=excluded.gps_lat,
    gps_lon=excluded.gps_lon,
    sync_since=excluded.sync_since;
"""

SQL_LAST_ADVERT = """
UPDATE contacts
   SET last_advert_packet=:last_advert_packet
 WHERE public_key=:public_key
"""

class SQLiteHelper:
    def __init__(self, settings: Settings):
        self.settings = settings.sqlite
        if not self.settings:
            raise ValueError("SQLite is not configured")
        
        self.path = Path(self.settings.path)
        
    async def _init_db(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(SQL_CREATE_CONTACTS)
            await db.execute(SQL_CREATE_LAST_ADVERT)
            
    async def load_contacts(self) -> list[Contact]:
        """Load all contacts from the database"""
        contacts = []
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM contacts")
            results = await cursor.fetchall()
            for row in results:
                print(row)
                data = {
                    "public_key": binascii.unhexlify(row["public_key"]),
                    "adv_type": row["adv_type"],
                    "flags": row["flags"],
                    "out_path_len": row["out_path_len"],
                    "out_path": row["out_path"],
                    "last_advert_timestamp": row["last_advert_timestamp"],
                    "lastmod": row["last_mod"],
                    "gps_lat": row["gps_lat"],
                    "gps_lon": row["gps_lon"],
                    "sync_since": row["sync_since"],
                }
                contacts.append(Contact(**data))
        return contacts
                
                
    async def save_contact(self, contact: Contact) -> None:
        payload = {
            "public_key": binascii.hexlify(contact.public_key),
            "adv_type": contact.adv_type,
            "flags": contact.flags,
            "out_path_len": contact.out_path_len,
            "out_path": contact.out_path,
            "last_advert_timestamp": contact.last_advert_timestamp,
            "last_mod": contact.lastmod,
            "gps_lat": contact.gps_lat,
            "gps_lon": contact.gps_lon,
            "sync_since": contact.sync_since
        }
        async with aiosqlite.connect(self.path) as db:
            await db.execute(SQL_INSERT_CONTACT, payload)
            await db.commit()
            
    async def save_contacts(self, contacts: list[Contact]) -> None:
        payload = []
        for contact in contacts:
            payload.append({
                "public_key": binascii.hexlify(contact.public_key),
                "adv_type": contact.adv_type,
                "flags": contact.flags,
                "out_path_len": contact.out_path_len,
                "out_path": contact.out_path,
                "last_advert_timestamp": contact.last_advert_timestamp,
                "last_mod": contact.lastmod,
                "gps_lat": contact.gps_lat,
                "gps_lon": contact.gps_lon,
                "sync_since": contact.sync_since
            })
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(SQL_INSERT_CONTACT, payload)
            await db.commit()
            
    async def get_last_advert(self) -> int:
        last = 0
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM last_advert")
            result = await cursor.fetchone()
            if not result:
                await db.execute("INSERT INTO last_advert (last_advert_timestamp) VALUES (?)", last)
                await db.commit()
            else:
                last = result["last_advert_timestamp"]
        return last
            
    async def update_advert(self, timestamp: int) -> None:
        payload = {
            "last_advert_timestamp": timestamp
        }
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE last_advert SET last_advert_timestamp = :last_advert_timestamp", payload)
            await db.commit()
                
