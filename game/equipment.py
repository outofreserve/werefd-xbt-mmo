"""Weapon equip/unequip.

Equipping doesn't consume the item from inventory -- only an item_id
reference is stored (players.equipped_weapon). Combat stats look up the
item fresh each time and silently drop the bonus if the player no longer
owns at least one (see game/combat_stats.get_equipped_weapon).
"""
from __future__ import annotations

from game import battle, db, items


def equip(username: str, item_id: str) -> tuple[bool, str]:
    if battle.in_combat(username):
        return False, "You can't swap weapons mid-combat."
    item_id = item_id.lower()
    item = items.get(item_id)
    if item is None or item.slot != "weapon":
        return False, f"'{item_id}' isn't a weapon you can equip."
    if db.get_item_qty(username, item_id) < 1:
        return False, f"You don't have a {item.name}."
    db.set_equipped_weapon(username, item_id)
    return True, f"You equip the {item.name}."


def unequip(username: str) -> tuple[bool, str]:
    if battle.in_combat(username):
        return False, "You can't swap weapons mid-combat."
    db.set_equipped_weapon(username, None)
    return True, "You unequip your weapon."
