"""Real-time, diku-style auto-attack combat engine.

Unlike a manual turn-based system, a player doesn't choose actions each
round: PVE/DUEL ACCEPT just starts the fight, and each combatant then
swings automatically on their own attack-speed timer (faster weapons =
more swings over time) until one side's HP hits zero or someone flees.
Rounds are resolved by process_tick(), called every COMBAT_PULSE_SECONDS
from the server's combat loop, which pushes new log lines straight to the
fighters' terminals.

Battle state is intentionally in-memory only (ACTIVE_BATTLES), mirroring
the existing SESSIONS/chat registries -- a server restart simply ends any
fight in progress, which is an acceptable tradeoff for a lightweight game.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from game import combat_stats, companions, config, db, monsters, stakes, world
from game.skills.base import level_for_xp

PVE_COOLDOWN = 15.0
MAX_SWINGS_PER_PULSE = 50  # safety cap against clock-skew/backlog loops

DAMAGE_TYPE_SKILL = {"melee": "STRENGTH", "ranged": "DEXTERITY", "magic": "INTELLIGENCE"}


@dataclass
class Fighter:
    kind: str           # "player" | "monster"
    key: str            # username for players, battle-local id for monsters
    name: str
    hp: float
    max_hp: float
    mana: float
    attack_interval: float
    damage_type: str
    power: float
    mitigation: float
    evasion_chance: float
    next_attack_at: float
    monster_id: str | None = None
    recruit_species: str | None = None
    fiat_reward: float = 0.0


@dataclass
class Battle:
    kind: str  # "pve" | "duel"
    a: Fighter
    b: Fighter
    duel_id: int | None = None
    finished: bool = False
    winner: str | None = None


ACTIVE_BATTLES: dict[str, Battle] = {}


def in_combat(username: str) -> bool:
    battle = ACTIVE_BATTLES.get(username)
    return battle is not None and not battle.finished


def get_battle(username: str) -> Battle | None:
    return ACTIVE_BATTLES.get(username)


def _opponent(battle: Battle, username: str) -> Fighter:
    return battle.b if battle.a.key == username else battle.a


def _mine(battle: Battle, username: str) -> Fighter:
    return battle.a if battle.a.key == username else battle.b


def _player_fighter(username: str, now: float) -> Fighter:
    profile = combat_stats.player_combat_profile(username, now)
    return Fighter(
        kind="player", key=username, name=username,
        hp=profile.hp, max_hp=profile.max_hp, mana=0.0,
        attack_interval=profile.attack_interval, damage_type=profile.damage_type,
        power=profile.power, mitigation=profile.mitigation,
        evasion_chance=profile.evasion_chance, next_attack_at=now,
    )


def _save_player_hp(fighter: Fighter, now: float):
    player = db.get_player(fighter.key)
    db.set_hp_mana(fighter.key, max(0.0, fighter.hp), player.mana if player.mana is not None else 0.0, now)


def _single_swing(battle: Battle, attacker: Fighter, defender: Fighter, now: float) -> str:
    """Resolves one attack, mutates defender.hp, and returns a log line."""
    if random.random() < defender.evasion_chance:
        if defender.kind == "player":
            db.add_xp(defender.key, "EVASION", 3.0)
        line = f"{attacker.name} attacks {defender.name} -- {defender.name} evades!"
    else:
        dmg = max(1, round(attacker.power - defender.mitigation + random.uniform(-1.0, 1.5)))
        defender.hp = max(0.0, defender.hp - dmg)
        if attacker.kind == "player":
            db.add_xp(attacker.key, DAMAGE_TYPE_SKILL[attacker.damage_type], 4.0)
        if defender.kind == "player":
            db.add_xp(defender.key, "CONSTITUTION", 2.0)
            _save_player_hp(defender, now)
        line = f"{attacker.name} hits {defender.name} for {dmg} ({defender.hp:.0f}/{defender.max_hp:.0f} HP left)."
        if defender.hp <= 0:
            battle.finished = True
            battle.winner = attacker.key
    return line


def _advance(battle: Battle, now: float) -> list[str]:
    lines: list[str] = []
    if battle.finished:
        return lines
    for _ in range(MAX_SWINGS_PER_PULSE):
        if battle.a.hp <= 0 or battle.b.hp <= 0:
            break
        first, second = (battle.a, battle.b) if battle.a.next_attack_at <= battle.b.next_attack_at else (battle.b, battle.a)
        if first.next_attack_at > now:
            break
        lines.append(_single_swing(battle, first, second, now))
        first.next_attack_at = now + first.attack_interval
        if battle.finished:
            break
    return lines


def _conclude_pve(battle: Battle, now: float) -> list[str]:
    player = battle.a
    monster_f = battle.b
    lines = []
    db.set_cooldown(player.key, f"PVE:{monster_f.monster_id}", now)
    if battle.winner == player.key:
        with db.connect() as conn:
            state = conn.execute("SELECT pool_fiat FROM game_state WHERE id = 1").fetchone()
            payout = min(monster_f.fiat_reward, state["pool_fiat"])
            conn.execute("UPDATE players SET fiat = fiat + ? WHERE username = ?", (payout, player.key))
            conn.execute("UPDATE game_state SET pool_fiat = pool_fiat - ? WHERE id = 1", (payout,))
        lines.append(f"You loot ${payout:,.2f} from the {monster_f.name}.")
        if monster_f.recruit_species:
            species = companions.get(monster_f.recruit_species)
            if random.random() < species.recruit_chance:
                comp_id = db.add_companion(player.key, species.id, species.name)
                lines.append(f"The {monster_f.name} warms up to you! Recruited as companion #{comp_id}: {species.name}.")
    else:
        lines.append(f"You are defeated by the {monster_f.name} and limp away.")
    return lines


def _conclude_duel(battle: Battle, now: float) -> list[str]:
    duel = db.get_duel(battle.duel_id)
    winner = battle.winner
    loser = duel["target"] if winner == duel["challenger"] else duel["challenger"]
    import json
    loser_stake = json.loads(duel["target_stake"] if loser == duel["target"] else duel["challenger_stake"])
    with db.connect() as conn:
        stakes.transfer_stake(conn, loser, winner, loser_stake)
    db.set_duel_status(battle.duel_id, "resolved", winner=winner)
    return [f"{winner} wins duel #{battle.duel_id} and takes {loser}'s stake!"]


def start_pve(username: str, monster_id: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    if in_combat(username):
        return False, "You're already in combat. Type FLEE to disengage first."
    monster_id = monster_id.lower()
    monster = monsters.get(monster_id)
    if monster is None:
        return False, f"Unknown monster '{monster_id}'."

    player = db.get_player(username)
    if player.travel_destination is not None and player.travel_arrival is not None and now < player.travel_arrival:
        remaining = player.travel_arrival - now
        return False, f"You're on the road, arriving in {remaining:.0f}s."
    loc = world.get(player.location)
    if loc is None or monster_id not in loc.monsters:
        return False, f"There's no {monster.name} here."

    remaining = PVE_COOLDOWN - (now - db.get_cooldown(username, f"PVE:{monster_id}"))
    if remaining > 0:
        return False, f"You're still recovering. Try again in {remaining:.0f}s."

    player_f = _player_fighter(username, now)
    monster_profile = combat_stats.monster_combat_profile(monster)
    monster_f = Fighter(
        kind="monster", key=f"{username}:{monster_id}", name=monster.name,
        hp=monster_profile.hp, max_hp=monster_profile.max_hp, mana=0.0,
        attack_interval=monster_profile.attack_interval, damage_type=monster_profile.damage_type,
        power=monster_profile.power, mitigation=monster_profile.mitigation,
        evasion_chance=0.0, next_attack_at=now + monster_profile.attack_interval,
        monster_id=monster_id, recruit_species=monster.recruit_species, fiat_reward=monster.fiat_reward,
    )
    battle = Battle(kind="pve", a=player_f, b=monster_f)
    ACTIVE_BATTLES[username] = battle

    lines = [f"You engage the {monster.name} ({monster_f.hp:.0f} HP)!"]
    lines.extend(_advance(battle, now))
    if battle.finished:
        lines.extend(_conclude_pve(battle, now))
        del ACTIVE_BATTLES[username]
    return True, "\n".join(lines)


def start_duel(duel_id: int, challenger: str, target: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    a = _player_fighter(challenger, now)
    b = _player_fighter(target, now)
    b.next_attack_at = now + b.attack_interval  # target reacts a beat after the challenger's opener
    battle = Battle(kind="duel", a=a, b=b, duel_id=duel_id)
    ACTIVE_BATTLES[challenger] = battle
    ACTIVE_BATTLES[target] = battle

    lines = [f"Duel #{duel_id} begins: {challenger} vs {target}!"]
    lines.extend(_advance(battle, now))
    if battle.finished:
        lines.extend(_conclude_duel(battle, now))
        ACTIVE_BATTLES.pop(challenger, None)
        ACTIVE_BATTLES.pop(target, None)
    return True, "\n".join(lines)


def flee(username: str, now: float | None = None) -> tuple[bool, str, list[tuple[str, str]]]:
    now = now if now is not None else time.time()
    battle = ACTIVE_BATTLES.get(username)
    if battle is None or battle.finished:
        return False, "You're not in combat.", []

    me = _mine(battle, username)
    opponent = _opponent(battle, username)
    eva_level = level_for_xp(db.get_xp(username, "EVASION"))
    chance = min(0.95, config.FLEE_BASE_CHANCE + eva_level * config.FLEE_CHANCE_PER_EVASION_LEVEL)

    pushes: list[tuple[str, str]] = []
    if random.random() < chance:
        battle.finished = True
        if battle.kind == "pve":
            db.set_cooldown(username, f"PVE:{opponent.monster_id}", now)
        else:
            battle.winner = opponent.key
            pushes.append((opponent.key, "\n".join(_conclude_duel(battle, now))))
            pushes.append((opponent.key, f"{username} flees the duel -- you win by forfeit!"))
        for key in (battle.a.key, battle.b.key):
            ACTIVE_BATTLES.pop(key, None)
        return True, "You slip away and flee the fight!", pushes

    # Failed escape attempt: the opponent gets a free swing.
    line = _single_swing(battle, opponent, me, now)
    opponent.next_attack_at = now + opponent.attack_interval
    msg = f"You fail to escape! {line}"
    if battle.finished:
        conclude_lines = _conclude_pve(battle, now) if battle.kind == "pve" else _conclude_duel(battle, now)
        msg += "\n" + "\n".join(conclude_lines)
        if battle.kind == "duel":
            pushes.append((opponent.key, "\n".join(conclude_lines)))
        for key in (battle.a.key, battle.b.key):
            ACTIVE_BATTLES.pop(key, None)
    return False, msg, pushes


def process_tick(now: float | None = None) -> list[tuple[str, str]]:
    """Advances every active battle by one pulse. Returns a list of
    (username, message) pairs to push to online sessions."""
    now = now if now is not None else time.time()
    pushes: list[tuple[str, str]] = []
    seen: set[int] = set()
    for battle in list(ACTIVE_BATTLES.values()):
        if id(battle) in seen or battle.finished:
            continue
        seen.add(id(battle))
        lines = _advance(battle, now)
        if lines:
            pushes.append((battle.a.key, "\n".join(lines)))
            if battle.kind == "duel":
                pushes.append((battle.b.key, "\n".join(lines)))
        if battle.finished:
            if battle.kind == "pve":
                conclude_lines = _conclude_pve(battle, now)
                pushes.append((battle.a.key, "\n".join(conclude_lines)))
                del ACTIVE_BATTLES[battle.a.key]
            else:
                conclude_lines = _conclude_duel(battle, now)
                pushes.append((battle.a.key, "\n".join(conclude_lines)))
                pushes.append((battle.b.key, "\n".join(conclude_lines)))
                ACTIVE_BATTLES.pop(battle.a.key, None)
                ACTIVE_BATTLES.pop(battle.b.key, None)
    return pushes
