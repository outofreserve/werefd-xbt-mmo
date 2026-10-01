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
    created_at REAL NOT NULL
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
"""


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
        if first_time:
            now = time.time()
            conn.execute(
                """INSERT OR IGNORE INTO game_state
                   (id, pool_fiat, total_fiat_supply, total_xbt_supply,
                    amm_fiat_reserve, amm_xbt_reserve, last_tick, last_block_time)
                   VALUES (1, 0, 0, 0, ?, ?, ?, ?)""",
                (config.AMM_SEED_FIAT, config.AMM_SEED_XBT, now, now),
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
            """INSERT INTO players (username, salt, password_hash, fiat, xbt, hash_power_ghs, created_at)
               VALUES (?, ?, ?, ?, 0, 0, ?)""",
            (username, salt, pw_hash, config.STARTING_FIAT, now),
        )
        conn.execute(
            """UPDATE game_state SET total_fiat_supply = total_fiat_supply + ?""",
            (config.STARTING_FIAT,),
        )
    return Player(username, config.STARTING_FIAT, 0.0, 0.0, now)


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
            "SELECT username, fiat, xbt, hash_power_ghs, created_at FROM players WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        return Player(row["username"], row["fiat"], row["xbt"], row["hash_power_ghs"], row["created_at"])


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
