"""Movement between locations.

Travel is not instant: setting off starts a timer (config.TRAVEL_SECONDS)
and the player arrives only once that time has elapsed. Arrival is
resolved lazily -- resolve_arrival() is called at the top of every
authenticated server command, so there's no background task per player.
"""
from __future__ import annotations

import time

from game import config, db, world
from game import battle


def is_travelling(player, now: float | None = None) -> tuple[bool, float]:
    """Return (travelling, seconds_remaining) for a player's current trip."""
    if player.travel_destination is None or player.travel_arrival is None:
        return False, 0.0
    now = now if now is not None else time.time()
    remaining = player.travel_arrival - now
    return remaining > 0, max(0.0, remaining)


def resolve_arrival(username: str, now: float | None = None) -> str:
    """If a pending trip has finished, finalize it. Returns the player's
    (possibly just-updated) current location id."""
    player = db.get_player(username)
    now = now if now is not None else time.time()
    if player.travel_destination is not None and player.travel_arrival is not None:
        if now >= player.travel_arrival:
            db.finish_travel(username, player.travel_destination)
            return player.travel_destination
    return player.location


def travel(username: str, direction: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    if battle.in_combat(username):
        return False, "You're in combat! Type FLEE to disengage first."
    resolve_arrival(username, now)
    player = db.get_player(username)

    travelling, remaining = is_travelling(player, now)
    if travelling:
        dest_name = world.get(player.travel_destination).name
        return False, f"You're already on your way to {dest_name}, arriving in {remaining:.0f}s."

    loc = world.get(player.location)
    direction = direction.lower()
    dest = loc.exits.get(direction)
    if dest is None:
        exits = ", ".join(loc.exits) or "none"
        return False, f"You can't go '{direction}' from here. Exits: {exits}."

    arrival = now + config.TRAVEL_SECONDS
    db.start_travel(username, dest, arrival)
    dest_name = world.get(dest).name
    if config.TRAVEL_SECONDS <= 0:
        # Instant travel (e.g. tests) -- resolve right away rather than
        # waiting for the next command.
        resolve_arrival(username, now)
        return True, f"You arrive at {dest_name}."
    return True, f"You set off toward {dest_name}. Arriving in {config.TRAVEL_SECONDS:.0f}s."
