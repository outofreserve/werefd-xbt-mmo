"""Movement between locations."""
from __future__ import annotations

from game import db, world


def travel(username: str, direction: str) -> tuple[bool, str]:
    player = db.get_player(username)
    loc = world.get(player.location)
    direction = direction.lower()
    dest = loc.exits.get(direction)
    if dest is None:
        exits = ", ".join(loc.exits) or "none"
        return False, f"You can't go '{direction}' from here. Exits: {exits}."
    db.set_location(username, dest)
    return True, world.describe(dest)
