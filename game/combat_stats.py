"""Derives a player's live combat profile (HP/mana pools, damage, defense,
evasion, attack speed) from their attribute skill levels, equipped weapon,
and active companion.

HP/mana regen is lazy, same pattern as travel arrival: resolve_regen() is
called whenever we need a fresh value, rather than running a per-player
timer.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from game import companions, config, db, items
from game.skills.base import level_for_xp

ATTRIBUTE_SKILLS = ("STRENGTH", "DEXTERITY", "CONSTITUTION", "EVASION", "INTELLIGENCE")


def max_hp(con_level: float) -> float:
    return config.BASE_HP + con_level * config.HP_PER_CON_LEVEL


def max_mana(int_level: float) -> float:
    return config.BASE_MANA + int_level * config.MANA_PER_INT_LEVEL


def get_equipped_weapon(player) -> items.Item | None:
    """The weapon's bonuses only apply while the player still owns at least
    one -- selling/trading it away silently drops the bonus without needing
    explicit unequip-on-sell logic."""
    if not player.equipped_weapon:
        return None
    if db.get_item_qty(player.username, player.equipped_weapon) < 1:
        return None
    return items.get(player.equipped_weapon)


def resolve_regen(username: str, now: float | None = None) -> db.Player:
    """Lazily applies HP/mana regen since the player's last recorded tick.
    Returns the (possibly just-updated) Player."""
    now = now if now is not None else time.time()
    player = db.get_player(username)
    con_level = level_for_xp(db.get_xp(username, "CONSTITUTION"))
    int_level = level_for_xp(db.get_xp(username, "INTELLIGENCE"))
    cap_hp = max_hp(con_level)
    cap_mana = max_mana(int_level)

    hp = player.hp if player.hp is not None else cap_hp
    mana = player.mana if player.mana is not None else cap_mana
    last = player.last_regen_at if player.last_regen_at is not None else now
    elapsed = max(0.0, now - last)

    new_hp = min(cap_hp, hp + elapsed * config.HP_REGEN_PER_SECOND)
    new_mana = min(cap_mana, mana + elapsed * config.MANA_REGEN_PER_SECOND)
    new_hp = min(new_hp, cap_hp)  # also clamps down if a CON loss ever shrinks the cap
    new_mana = min(new_mana, cap_mana)

    if new_hp != player.hp or new_mana != player.mana or player.last_regen_at is None:
        db.set_hp_mana(username, new_hp, new_mana, now)
    player.hp, player.mana, player.last_regen_at = new_hp, new_mana, now
    return player


@dataclass
class CombatProfile:
    name: str
    hp: float
    max_hp: float
    attack_interval: float
    damage_type: str
    power: float               # base damage dealt per hit, before rng variance
    mitigation: float          # flat damage reduction
    evasion_chance: float      # chance to fully dodge an incoming hit


def player_combat_profile(username: str, now: float | None = None) -> CombatProfile:
    now = now if now is not None else time.time()
    player = resolve_regen(username, now)
    weapon = get_equipped_weapon(player)

    str_lvl = level_for_xp(db.get_xp(username, "STRENGTH")) + (weapon.str_bonus if weapon else 0.0)
    dex_lvl = level_for_xp(db.get_xp(username, "DEXTERITY")) + (weapon.dex_bonus if weapon else 0.0)
    con_lvl = level_for_xp(db.get_xp(username, "CONSTITUTION")) + (weapon.con_bonus if weapon else 0.0)
    eva_lvl = level_for_xp(db.get_xp(username, "EVASION")) + (weapon.eva_bonus if weapon else 0.0)
    int_lvl = level_for_xp(db.get_xp(username, "INTELLIGENCE")) + (weapon.int_bonus if weapon else 0.0)

    damage_type = weapon.damage_type if weapon else "melee"
    if damage_type == "ranged":
        power = config.BASE_UNARMED_DAMAGE + dex_lvl * config.DEX_DAMAGE_PER_LEVEL
    elif damage_type == "magic":
        power = config.BASE_UNARMED_DAMAGE + int_lvl * config.INT_DAMAGE_PER_LEVEL
    else:
        power = config.BASE_UNARMED_DAMAGE + str_lvl * config.STR_DAMAGE_PER_LEVEL

    companion_atk = companion_def = 0.0
    if player.active_companion_id:
        comp = db.get_companion(player.active_companion_id)
        if comp is not None:
            species = companions.get(comp["species_id"])
            companion_atk, companion_def = species.attack, species.defense

    attack_interval = config.BASE_ATTACK_INTERVAL - (weapon.attack_speed_bonus if weapon else 0.0)
    attack_interval = max(config.MIN_ATTACK_INTERVAL, attack_interval)

    return CombatProfile(
        name=username,
        hp=player.hp,
        max_hp=max_hp(con_lvl),
        attack_interval=attack_interval,
        damage_type=damage_type,
        power=power + companion_atk,
        mitigation=con_lvl * config.DEFENSE_PER_CON_LEVEL + companion_def,
        evasion_chance=min(config.MAX_EVASION_CHANCE, eva_lvl * config.EVASION_PERCENT_PER_LEVEL / 100.0),
    )


def monster_combat_profile(monster) -> CombatProfile:
    return CombatProfile(
        name=monster.name,
        hp=float(monster.hp),
        max_hp=float(monster.hp),
        attack_interval=monster.attack_interval,
        damage_type=monster.damage_type,
        power=float(monster.attack),
        mitigation=float(monster.defense),
        evasion_chance=0.0,
    )
