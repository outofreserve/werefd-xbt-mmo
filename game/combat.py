"""Turn-based combat: PvE monster fights and staked PvP duels.

Combat is simple stat-exchange (hp/attack/defense) rather than a full
card-hand TCG, with room to layer ability cards on top later without
changing the player-facing commands.
"""
from __future__ import annotations

import json
import random
import time

from game import companions, config, db, items, monsters, world

PVE_COOLDOWN = 15.0
MAX_ROUNDS = 50


def get_combat_stats(username: str) -> dict:
    player = db.get_player(username)
    if player.active_companion_id:
        comp = db.get_companion(player.active_companion_id)
        if comp is not None:
            species = companions.get(comp["species_id"])
            return {
                "name": comp["nickname"],
                "hp": species.hp,
                "attack": species.attack,
                "defense": species.defense,
            }
    # Bare-handed, no companion: deliberately weak to encourage recruiting one.
    return {"name": username, "hp": 10, "attack": 2, "defense": 1}


def battle(a: dict, b: dict, rng: random.Random | None = None) -> dict:
    rng = rng or random
    hp_a, hp_b = a["hp"], b["hp"]
    log = [f"{a['name']} ({hp_a} HP) vs {b['name']} ({hp_b} HP)!"]
    rounds = 0
    while hp_a > 0 and hp_b > 0 and rounds < MAX_ROUNDS:
        rounds += 1
        dmg_a = max(1, a["attack"] - b["defense"] + rng.randint(-1, 2))
        hp_b -= dmg_a
        log.append(f"Round {rounds}: {a['name']} hits {b['name']} for {dmg_a} ({max(hp_b, 0)} HP left).")
        if hp_b <= 0:
            break
        dmg_b = max(1, b["attack"] - a["defense"] + rng.randint(-1, 2))
        hp_a -= dmg_b
        log.append(f"Round {rounds}: {b['name']} hits {a['name']} for {dmg_b} ({max(hp_a, 0)} HP left).")

    if hp_a <= 0 and hp_b <= 0:
        winner = "a" if hp_a >= hp_b else "b"
    elif hp_b <= 0:
        winner = "a"
    elif hp_a <= 0:
        winner = "b"
    else:
        winner = "a" if hp_a >= hp_b else "b"  # round cap hit: higher remaining hp wins
    log.append(f"{(a if winner == 'a' else b)['name']} wins!")
    return {"winner": winner, "rounds": rounds, "log": log}


def pve_fight(username: str, monster_id: str) -> tuple[bool, str]:
    monster_id = monster_id.lower()
    monster = monsters.get(monster_id)
    if monster is None:
        return False, f"Unknown monster '{monster_id}'."

    player = db.get_player(username)
    loc = world.get(player.location)
    if loc is None or monster_id not in loc.monsters:
        return False, f"There's no {monster.name} here."

    cooldown_key = f"PVE:{monster_id}"
    remaining = PVE_COOLDOWN - (time.time() - db.get_cooldown(username, cooldown_key))
    if remaining > 0:
        return False, f"You're still recovering. Try again in {remaining:.0f}s."

    stats_a = get_combat_stats(username)
    stats_b = {"name": monster.name, "hp": monster.hp, "attack": monster.attack, "defense": monster.defense}
    result = battle(stats_a, stats_b)
    db.set_cooldown(username, cooldown_key, time.time())

    lines = list(result["log"])
    if result["winner"] == "a":
        with db.connect() as conn:
            state = conn.execute("SELECT pool_fiat FROM game_state WHERE id = 1").fetchone()
            payout = min(monster.fiat_reward, state["pool_fiat"])
            conn.execute("UPDATE players SET fiat = fiat + ? WHERE username = ?", (payout, username))
            conn.execute("UPDATE game_state SET pool_fiat = pool_fiat - ? WHERE id = 1", (payout,))
        lines.append(f"You loot ${payout:,.2f} from the {monster.name}.")
        if monster.recruit_species:
            species = companions.get(monster.recruit_species)
            if random.random() < species.recruit_chance:
                comp_id = db.add_companion(username, species.id, species.name)
                lines.append(f"The {monster.name} warms up to you! Recruited as companion #{comp_id}: {species.name}.")
    else:
        lines.append("You limp away empty-handed.")
    return True, "\n".join(lines)


# --- PvP duels --------------------------------------------------------------

VALID_STAKE_TYPES = ("fiat", "xbt", "item", "companion")


def challenge(challenger: str, target: str) -> tuple[bool, str]:
    if challenger == target:
        return False, "You can't duel yourself."
    if db.get_player(target) is None:
        return False, f"No such player '{target}'."
    if db.get_pending_duel_for(challenger) is not None:
        return False, "You already have a pending duel. DUEL CANCEL it first."
    if db.get_pending_duel_for(target) is not None:
        return False, f"{target} already has a pending duel."
    duel_id = db.create_duel(challenger, target)
    return True, (
        f"Duel #{duel_id} challenge sent to {target}. Both sides set a stake with "
        f"DUEL STAKE <FIAT|XBT|ITEM|COMPANION> <amount/id> [qty], then {target} runs DUEL ACCEPT."
    )


def _validate_and_describe_stake(username: str, stake: dict) -> str | None:
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


def set_stake(username: str, duel_id: int, stake: dict) -> tuple[bool, str]:
    duel = db.get_duel(duel_id)
    if duel is None or duel["status"] != "pending":
        return False, "No pending duel with that id."
    if username not in (duel["challenger"], duel["target"]):
        return False, "You're not part of that duel."
    error = _validate_and_describe_stake(username, stake)
    if error:
        return False, f"Can't set that stake: {error}."
    who = "challenger" if username == duel["challenger"] else "target"
    db.update_duel_stake(duel_id, who, json.dumps(stake))
    return True, f"Stake set for duel #{duel_id}."


def _transfer_stake(conn, from_user: str, to_user: str, stake: dict):
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


def accept(duel_id: int, acceptor: str) -> tuple[bool, str]:
    duel = db.get_duel(duel_id)
    if duel is None or duel["status"] != "pending":
        return False, "No pending duel with that id."
    if acceptor != duel["target"]:
        return False, "Only the challenged player can accept."

    challenger_stake = json.loads(duel["challenger_stake"])
    target_stake = json.loads(duel["target_stake"])
    for user, stake in ((duel["challenger"], challenger_stake), (duel["target"], target_stake)):
        error = _validate_and_describe_stake(user, stake)
        if error:
            db.set_duel_status(duel_id, "cancelled")
            return False, f"Duel cancelled: {user}'s stake is invalid ({error})."

    stats_a = get_combat_stats(duel["challenger"])
    stats_b = get_combat_stats(duel["target"])
    result = battle(stats_a, stats_b)
    winner = duel["challenger"] if result["winner"] == "a" else duel["target"]
    loser = duel["target"] if winner == duel["challenger"] else duel["challenger"]
    loser_stake = target_stake if winner == duel["challenger"] else challenger_stake
    winner_stake = challenger_stake if winner == duel["challenger"] else target_stake

    with db.connect() as conn:
        _transfer_stake(conn, loser, winner, loser_stake)
        # Winner keeps their own stake; only the loser's stake moves.
        _ = winner_stake
    db.set_duel_status(duel_id, "resolved", winner=winner)

    lines = list(result["log"])
    lines.append(f"{winner} wins duel #{duel_id} and takes {loser}'s stake!")
    return True, "\n".join(lines)


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
