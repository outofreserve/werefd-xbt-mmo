"""Ephemeral, location-scoped chat.

Deliberately NOT persisted to the database -- messages live only in this
in-memory buffer and expire after config.CHAT_MESSAGE_TTL_SECONDS. A
restart, or just enough time passing, wipes them for good.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from game import config

# location_id -> deque of (timestamp, username, message), oldest first.
_BUFFERS: dict[str, deque] = defaultdict(deque)


def _trim(location_id: str, now: float):
    buf = _BUFFERS[location_id]
    while buf and now - buf[0][0] > config.CHAT_MESSAGE_TTL_SECONDS:
        buf.popleft()


def post(location_id: str, username: str, message: str, now: float | None = None):
    now = now if now is not None else time.time()
    _trim(location_id, now)
    _BUFFERS[location_id].append((now, username, message))


def recent(location_id: str, now: float | None = None) -> list[tuple[float, str, str]]:
    now = now if now is not None else time.time()
    _trim(location_id, now)
    return list(_BUFFERS[location_id])
