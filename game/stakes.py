"""Shared PvP duel stake validation/transfer helpers.

Split out from game/combat.py so both combat.py (duel admin: challenge,
stake, cancel) and game/battle.py (real-time fight resolution) can use them
without importing each other.
"""
from __future__ import annotations

from game import db

VALID_STAKE_TYPES = ("fiat", "xbt", "item", "companion")


def validate_stake(username: str, stake: dict) -> str | None:
    """Returns an error string, or None if the stake is currently affordable."""
    if not stake:
        return "no stake set"
    player = db.get_player(username)
    t = stake["type"]
    if t == "fiat":
        if player.fiat < stake["amount"]:
            return "insufficient fiat"
    elif t == "xbt":
        if player.xbt < stake["amount"]:
            return "insufficient XBT"
    elif t == "item":
        if db.get_item_qty(username, stake["item_id"]) < stake["qty"]:
            return "insufficient items"
    elif t == "companion":
        comp = db.get_companion(stake["companion_id"])
        if comp is None or comp["username"] != username:
            return "companion not owned"
    return None


def transfer_stake(conn, from_user: str, to_user: str, stake: dict):
    t = stake["type"]
    if t == "fiat":
        conn.execute("UPDATE players SET fiat = fiat - ? WHERE username = ?", (stake["amount"], from_user))
        conn.execute("UPDATE players SET fiat = fiat + ? WHERE username = ?", (stake["amount"], to_user))
    elif t == "xbt":
        conn.execute("UPDATE players SET xbt = xbt - ? WHERE username = ?", (stake["amount"], from_user))
        conn.execute("UPDATE players SET xbt = xbt + ? WHERE username = ?", (stake["amount"], to_user))
    elif t == "item":
        db.remove_item(from_user, stake["item_id"], stake["qty"], conn=conn)
        db.add_item(to_user, stake["item_id"], stake["qty"], conn=conn)
    elif t == "companion":
        conn.execute("UPDATE companions SET username = ? WHERE id = ?", (to_user, stake["companion_id"]))
