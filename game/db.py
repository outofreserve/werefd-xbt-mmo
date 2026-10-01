"""SQLite persistence layer.

Kept synchronous and wrapped with asyncio.to_thread() call sites in the
server, since sqlite3 connections aren't safe to share across threads
without care -- each call opens its own short-lived connection, which is
plenty fast for a lightweight game at this scale.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass

from game import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    username TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    fiat REAL NOT NULL,
    xbt REAL NOT NULL DEFAULT 0,
    hash_power_ghs REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    location TEXT NOT NULL DEFAULT 'camp',
    active_companion_id INTEGER
);

CREATE TABLE IF NOT EXISTS cooldowns (
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    last_used REAL NOT NULL,
    PRIMARY KEY (username, action)
);

-- Singleton row (id = 1) holding shared economy state.
CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pool_fiat REAL NOT NULL,
    total_fiat_supply REAL NOT NULL,
    total_xbt_supply REAL NOT NULL,
    amm_fiat_reserve REAL NOT NULL,
    amm_xbt_reserve REAL NOT NULL,
    last_tick REAL NOT NULL,
    last_block_time REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_xp (
    username TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    xp REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (username, skill_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    username TEXT NOT NULL,
    item_id TEXT NOT NULL,
    qty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (username, item_id)
);

CREATE TABLE IF NOT EXISTS quest_progress (
    username TEXT NOT NULL,
    quest_id TEXT NOT NULL,
    status TEXT NOT NULL,          -- active | complete
    updated_at REAL NOT NULL,
    PRIMARY KEY (username, quest_id)
);

CREATE TABLE IF NOT EXISTS companions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    species_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    acquired_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS duels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    challenger TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL,          -- pending | accepted | resolved | cancelled
    challenger_stake TEXT NOT NULL DEFAULT '{}',
    target_stake TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    resolved_at REAL,
    winner TEXT
);

CREATE TABLE IF NOT EXISTS resource_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id TEXT NOT NULL,
    type_id TEXT NOT NULL,
    label TEXT NOT NULL,
    available_at REAL NOT NULL DEFAULT 0
);
"""

# Columns added after the initial release. Each entry is applied with
# ALTER TABLE ... ADD COLUMN, ignoring "duplicate column" errors, so
# existing databases upgrade in place without a migration framework.
_MIGRATIONS = [
    ("players", "location", "TEXT NOT NULL DEFAULT 'camp'"),
    ("players", "active_companion_id", "INTEGER"),
    ("players", "travel_destination", "TEXT"),
    ("players", "travel_arrival", "REAL"),
    ("players", "hp", f"REAL NOT NULL DEFAULT {config.BASE_HP}"),
    ("players", "mana", f"REAL NOT NULL DEFAULT {config.BASE_MANA}"),
    ("players", "last_regen_at", "REAL"),  # NULL means "needs lazy init" -- see combat_stats.resolve_regen
    ("players", "equipped_weapon", "TEXT"),
]


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    first_time = not os.path.exists(config.DB_PATH)
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in _MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        if first_time:
            now = time.time()
            conn.execute(
                """INSERT OR IGNORE INTO game_state
                   (id, pool_fiat, total_fiat_supply, total_xbt_supply,
                    amm_fiat_reserve, amm_xbt_reserve, last_tick, last_block_time)
                   VALUES (1, 0, 0, 0, ?, ?, ?, ?)""",
                (config.AMM_SEED_FIAT, config.AMM_SEED_XBT, now, now),
            )
            from game import resource_nodes
            for location_id, type_id, label in resource_nodes.SEED_NODES:
                conn.execute(
                    """INSERT INTO resource_nodes (location_id, type_id, label, available_at)
                       VALUES (?, ?, ?, 0)""",
                    (location_id, type_id, label),
                )


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


@dataclass
class Player:
    username: str
    fiat: float
    xbt: float
    hash_power_ghs: float
    created_at: float
    location: str = "camp"
    active_companion_id: int | None = None
    travel_destination: str | None = None
    travel_arrival: float | None = None
    hp: float | None = None
    mana: float | None = None
    last_regen_at: float | None = None
    equipped_weapon: str | None = None


def create_player(username: str, password: str) -> Player:
    salt = os.urandom(16).hex()
    pw_hash = hash_password(password, salt)
    now = time.time()
    with connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM players WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise ValueError("username already taken")
        conn.execute(
            """INSERT INTO players
                   (username, salt, password_hash, fiat, xbt, hash_power_ghs, created_at,
                    hp, mana, last_regen_at)
               VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?, ?)""",
            (username, salt, pw_hash, config.STARTING_FIAT, now, config.BASE_HP, config.BASE_MANA, now),
        )
        conn.execute(
            """UPDATE game_state SET total_fiat_supply = total_fiat_supply + ?""",
            (config.STARTING_FIAT,),
        )
    return Player(
        username, config.STARTING_FIAT, 0.0, 0.0, now,
        hp=config.BASE_HP, mana=config.BASE_MANA, last_regen_at=now,
    )


def authenticate(username: str, password: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT salt, password_hash FROM players WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return False
        return hash_password(password, row["salt"]) == row["password_hash"]


def get_player(username: str) -> Player | None:
    with connect() as conn:
        row = conn.execute(
            """SELECT username, fiat, xbt, hash_power_ghs, created_at, location, active_companion_id,
                      travel_destination, travel_arrival, hp, mana, last_regen_at, equipped_weapon
               FROM players WHERE username = ?""",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return Player(
            row["username"], row["fiat"], row["xbt"], row["hash_power_ghs"], row["created_at"],
            row["location"], row["active_companion_id"],
            row["travel_destination"], row["travel_arrival"],
            row["hp"], row["mana"], row["last_regen_at"], row["equipped_weapon"],
        )


def set_hp_mana(username: str, hp: float, mana: float, now: float, conn=None):
    def _run(c):
        c.execute(
            "UPDATE players SET hp = ?, mana = ?, last_regen_at = ? WHERE username = ?",
            (hp, mana, now, username),
        )

    if conn is not None:
        _run(conn)
    else:
        with connect() as c:
            _run(c)


def set_equipped_weapon(username: str, item_id: str | None):
    with connect() as conn:
        conn.execute(
            "UPDATE players SET equipped_weapon = ? WHERE username = ?", (item_id, username)
        )


def start_travel(username: str, destination: str, arrival: float):
    with connect() as conn:
        conn.execute(
            "UPDATE players SET travel_destination = ?, travel_arrival = ? WHERE username = ?",
            (destination, arrival, username),
        )


def finish_travel(username: str, destination: str):
    with connect() as conn:
        conn.execute(
            """UPDATE players SET location = ?, travel_destination = NULL, travel_arrival = NULL
               WHERE username = ?""",
            (destination, username),
        )


def get_nodes(location_id: str):
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM resource_nodes WHERE location_id = ? ORDER BY id", (location_id,)
        ).fetchall()


def deplete_node(node_id: int, available_at: float, conn=None):
    def _run(c):
        c.execute("UPDATE resource_nodes SET available_at = ? WHERE id = ?", (available_at, node_id))

    if conn is not None:
        _run(conn)
    else:
        with connect() as c2:
            _run(c2)


def get_game_state() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM game_state WHERE id = 1").fetchone()
        return dict(row) if row else {}


def count_players() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM players").fetchone()["n"]


def set_location(username: str, location_id: str):
    with connect() as conn:
        conn.execute("UPDATE players SET location = ? WHERE username = ?", (location_id, username))


def set_active_companion(username: str, companion_id: int | None):
    with connect() as conn:
        conn.execute(
            "UPDATE players SET active_companion_id = ? WHERE username = ?", (companion_id, username)
        )


def get_cooldown(username: str, action: str) -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT last_used FROM cooldowns WHERE username = ? AND action = ?",
            (username, action),
        ).fetchone()
        return row["last_used"] if row else 0.0


def set_cooldown(username: str, action: str, when: float):
    with connect() as conn:
        conn.execute(
            """INSERT INTO cooldowns (username, action, last_used) VALUES (?, ?, ?)
               ON CONFLICT(username, action) DO UPDATE SET last_used = excluded.last_used""",
            (username, action, when),
        )


# --- Inventory -----------------------------------------------------------

def add_item(username: str, item_id: str, qty: int, conn=None):
    def _run(c):
        c.execute(
            """INSERT INTO inventory (username, item_id, qty) VALUES (?, ?, ?)
               ON CONFLICT(username, item_id) DO UPDATE SET qty = qty + excluded.qty""",
            (username, item_id, qty),
        )

    if conn is not None:
        _run(conn)
    else:
        with connect() as c:
            _run(c)


def remove_item(username: str, item_id: str, qty: int, conn=None) -> bool:
    """Returns False (no-op) if the player doesn't have enough of the item."""
    def _run(c) -> bool:
        row = c.execute(
            "SELECT qty FROM inventory WHERE username = ? AND item_id = ?", (username, item_id)
        ).fetchone()
        have = row["qty"] if row else 0
        if have < qty:
            return False
        c.execute(
            "UPDATE inventory SET qty = qty - ? WHERE username = ? AND item_id = ?",
            (qty, username, item_id),
        )
        return True

    if conn is not None:
        return _run(conn)
    with connect() as c:
        return _run(c)


def get_inventory(username: str) -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT item_id, qty FROM inventory WHERE username = ? AND qty > 0", (username,)
        ).fetchall()
        return {r["item_id"]: r["qty"] for r in rows}


def get_item_qty(username: str, item_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT qty FROM inventory WHERE username = ? AND item_id = ?", (username, item_id)
        ).fetchone()
        return row["qty"] if row else 0


# --- Skill XP --------------------------------------------------------------

def get_xp(username: str, skill_id: str) -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT xp FROM skill_xp WHERE username = ? AND skill_id = ?", (username, skill_id)
        ).fetchone()
        return row["xp"] if row else 0.0


def get_all_xp(username: str) -> dict[str, float]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT skill_id, xp FROM skill_xp WHERE username = ?", (username,)
        ).fetchall()
        return {r["skill_id"]: r["xp"] for r in rows}


def add_xp(username: str, skill_id: str, amount: float, conn=None):
    def _run(c):
        c.execute(
            """INSERT INTO skill_xp (username, skill_id, xp) VALUES (?, ?, ?)
               ON CONFLICT(username, skill_id) DO UPDATE SET xp = xp + excluded.xp""",
            (username, skill_id, amount),
        )

    if conn is not None:
        _run(conn)
    else:
        with connect() as c:
            _run(c)


# --- Quests ------------------------------------------------------------

def get_quest_status(username: str, quest_id: str) -> str | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT status FROM quest_progress WHERE username = ? AND quest_id = ?",
            (username, quest_id),
        ).fetchone()
        return row["status"] if row else None


def get_all_quest_status(username: str) -> dict[str, str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT quest_id, status FROM quest_progress WHERE username = ?", (username,)
        ).fetchall()
        return {r["quest_id"]: r["status"] for r in rows}


def set_quest_status(username: str, quest_id: str, status: str, conn=None):
    now = time.time()

    def _run(c):
        c.execute(
            """INSERT INTO quest_progress (username, quest_id, status, updated_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(username, quest_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at""",
            (username, quest_id, status, now),
        )

    if conn is not None:
        _run(conn)
    else:
        with connect() as c:
            _run(c)


# --- Companions ----------------------------------------------------------

def add_companion(username: str, species_id: str, nickname: str, conn=None) -> int:
    now = time.time()

    def _run(c) -> int:
        cur = c.execute(
            "INSERT INTO companions (username, species_id, nickname, acquired_at) VALUES (?, ?, ?, ?)",
            (username, species_id, nickname, now),
        )
        return cur.lastrowid

    if conn is not None:
        return _run(conn)
    with connect() as c:
        return _run(c)


def get_companions(username: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM companions WHERE username = ? ORDER BY id", (username,)
        ).fetchall()


def get_companion(companion_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM companions WHERE id = ?", (companion_id,)).fetchone()


# --- Duels -----------------------------------------------------------------

def create_duel(challenger: str, target: str) -> int:
    now = time.time()
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO duels (challenger, target, status, created_at) VALUES (?, ?, 'pending', ?)""",
            (challenger, target, now),
        )
        return cur.lastrowid


def get_pending_duel_for(username: str) -> sqlite3.Row | None:
    """Most recent pending/accepted duel where username is challenger or target."""
    with connect() as conn:
        return conn.execute(
            """SELECT * FROM duels WHERE (challenger = ? OR target = ?)
               AND status IN ('pending', 'accepted') ORDER BY id DESC LIMIT 1""",
            (username, username),
        ).fetchone()


def get_duel(duel_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM duels WHERE id = ?", (duel_id,)).fetchone()


def update_duel_stake(duel_id: int, who: str, stake_json: str):
    column = "challenger_stake" if who == "challenger" else "target_stake"
    with connect() as conn:
        conn.execute(f"UPDATE duels SET {column} = ? WHERE id = ?", (stake_json, duel_id))


def set_duel_status(duel_id: int, status: str, winner: str | None = None):
    with connect() as conn:
        conn.execute(
            "UPDATE duels SET status = ?, winner = ?, resolved_at = ? WHERE id = ?",
            (status, winner, time.time(), duel_id),
        )
