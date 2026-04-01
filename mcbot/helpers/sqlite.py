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
    "name"  TEXT NOT NULL,
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
    name,
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
    :name,
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
    name=excluded.name,
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

SQL_CREATE_MESSAGE_STATS = """
CREATE TABLE IF NOT EXISTS message_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    sender_id TEXT NOT NULL,
    channel TEXT,
    content TEXT NOT NULL,
    is_dm BOOLEAN NOT NULL,
    hops INTEGER,
    snr REAL,
    rssi INTEGER,
    path TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

SQL_CREATE_COMPLETE_CONTACT_TRACKING = """
CREATE TABLE IF NOT EXISTS complete_contact_tracking (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    public_key TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    device_type TEXT,
    first_heard TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_heard TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    advert_count INTEGER DEFAULT 1,
    latitude REAL,
    longitude REAL,
    city TEXT,
    state TEXT,
    country TEXT,
    raw_advert_data TEXT,
    signal_strength REAL,
    snr REAL,
    hop_count INTEGER,
    is_currently_tracked BOOLEAN DEFAULT 0,
    last_advert_timestamp TIMESTAMP,
    location_accuracy REAL,
    contact_source TEXT DEFAULT 'advertisement',
    out_path TEXT,
    out_path_len INTEGER,
    is_starred INTEGER DEFAULT 0
);
"""

SQL_CREATE_MESH_CONNECTIONS = """
CREATE TABLE IF NOT EXISTS mesh_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_prefix TEXT NOT NULL,
    to_prefix TEXT NOT NULL,
    from_public_key TEXT,
    to_public_key TEXT,
    observation_count INTEGER DEFAULT 1,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    avg_hop_position REAL,
    geographic_distance REAL,
    UNIQUE(from_prefix, to_prefix)
);
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
            await db.execute(SQL_CREATE_COMPLETE_CONTACT_TRACKING)
            await db.execute(SQL_CREATE_MESH_CONNECTIONS)
            await db.execute(SQL_CREATE_MESSAGE_STATS)
            
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_public_key ON complete_contact_tracking(public_key)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_role ON complete_contact_tracking(role)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_last_heard ON complete_contact_tracking(last_heard)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_currently_tracked ON complete_contact_tracking(is_currently_tracked)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_location ON complete_contact_tracking(latitude, longitude)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_complete_role_tracked ON complete_contact_tracking(role, is_currently_tracked)')
            
            await db.execute('CREATE INDEX IF NOT EXISTS idx_from_prefix ON mesh_connections(from_prefix)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_to_prefix ON mesh_connections(to_prefix)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_last_seen ON mesh_connections(last_seen)')
            
    async def load_contacts(self) -> list[Contact]:
        """Load all contacts from the database"""
        contacts = []
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM contacts")
            results = await cursor.fetchall()
            for row in results:
                data = {
                    "name": row["name"],
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
            "name": contact.name,
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
                "name": contact.name,
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
                await db.execute("INSERT INTO last_advert (last_advert_timestamp) VALUES (?)", (last,))
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
                
