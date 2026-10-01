"""PvP duel administration: challenge, stake negotiation, accept, cancel.

The actual fight (PvE or PvP) now plays out in real time via game/battle.py
-- this module just manages duel setup/stakes and companion shop purchases.
"""
from __future__ import annotations

import json
import time

from game import battle, companions, db, stakes, travel

VALID_STAKE_TYPES = stakes.VALID_STAKE_TYPES


def challenge(challenger: str, target: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    if challenger == target:
        return False, "You can't duel yourself."
    if db.get_player(target) is None:
        return False, f"No such player '{target}'."
    if battle.in_combat(challenger):
        return False, "You're already in combat. Type FLEE to disengage first."
    travel.resolve_arrival(challenger, now)
    player = db.get_player(challenger)
    travelling, remaining = travel.is_travelling(player, now)
    if travelling:
        return False, f"You're on the road, arriving in {remaining:.0f}s."
    if db.get_pending_duel_for(challenger) is not None:
        return False, "You already have a pending duel. DUEL CANCEL it first."
    if db.get_pending_duel_for(target) is not None:
        return False, f"{target} already has a pending duel."
    duel_id = db.create_duel(challenger, target)
    return True, (
        f"Duel #{duel_id} challenge sent to {target}. Both sides set a stake with "
        f"DUEL STAKE <FIAT|XBT|ITEM|COMPANION> <amount/id> [qty], then {target} runs DUEL ACCEPT."
    )


def set_stake(username: str, duel_id: int, stake: dict) -> tuple[bool, str]:
    duel = db.get_duel(duel_id)
    if duel is None or duel["status"] != "pending":
        return False, "No pending duel with that id."
    if username not in (duel["challenger"], duel["target"]):
        return False, "You're not part of that duel."
    error = stakes.validate_stake(username, stake)
    if error:
        return False, f"Can't set that stake: {error}."
    who = "challenger" if username == duel["challenger"] else "target"
    db.update_duel_stake(duel_id, who, json.dumps(stake))
    return True, f"Stake set for duel #{duel_id}."


def accept(duel_id: int, acceptor: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    duel = db.get_duel(duel_id)
    if duel is None or duel["status"] != "pending":
        return False, "No pending duel with that id."
    if acceptor != duel["target"]:
        return False, "Only the challenged player can accept."
    if battle.in_combat(duel["challenger"]) or battle.in_combat(duel["target"]):
        return False, "One of you is already in combat."

    challenger_stake = json.loads(duel["challenger_stake"])
    target_stake = json.loads(duel["target_stake"])
    for user, stake in ((duel["challenger"], challenger_stake), (duel["target"], target_stake)):
        error = stakes.validate_stake(user, stake)
        if error:
            db.set_duel_status(duel_id, "cancelled")
            return False, f"Duel cancelled: {user}'s stake is invalid ({error})."

    db.set_duel_status(duel_id, "accepted")
    return battle.start_duel(duel_id, duel["challenger"], duel["target"], now)


def cancel(duel_id: int, username: str) -> tuple[bool, str]:
    duel = db.get_duel(duel_id)
    if duel is None or duel["status"] != "pending":
        return False, "No pending duel with that id."
    if username not in (duel["challenger"], duel["target"]):
        return False, "You're not part of that duel."
    db.set_duel_status(duel_id, "cancelled")
    return True, f"Duel #{duel_id} cancelled."


def buy_companion(username: str, species_id: str) -> tuple[bool, str]:
    species = companions.get(species_id.lower())
    if species is None or species.acquisition != "shop":
        return False, f"'{species_id}' isn't available for purchase."
    with db.connect() as conn:
        player = conn.execute("SELECT xbt FROM players WHERE username = ?", (username,)).fetchone()
        if player["xbt"] < species.shop_price_xbt:
            return False, f"Need {species.shop_price_xbt} XBT, you have {player['xbt']:.8f}."
        conn.execute("UPDATE players SET xbt = xbt - ? WHERE username = ?", (species.shop_price_xbt, username))
        # Shop purchases burn XBT (a fiat-free sink), so the recorded total
        # XBT supply always matches the sum of player balances.
        conn.execute(
            "UPDATE game_state SET total_xbt_supply = total_xbt_supply - ? WHERE id = 1",
            (species.shop_price_xbt,),
        )
        comp_id = db.add_companion(username, species.id, species.name, conn=conn)
    return True, f"Bought {species.name} for {species.shop_price_xbt} XBT (companion #{comp_id})."
