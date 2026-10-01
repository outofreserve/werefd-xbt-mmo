"""Item registry.

A flat, declarative catalog -- new items are just new dict entries. Items
have no behavior of their own; skills and recipes reference them by id.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Item:
    id: str
    name: str
    category: str   # "raw_fish" | "food" | "ore" | "junk" | "misc" | "weapon"
    sell_value: float = 0.0  # fiat value if sold to the generic market, 0 = unsellable
    # --- Equipment fields (only meaningful when slot is set) ---
    slot: str | None = None             # "weapon" (more slots can be added later)
    damage_type: str | None = None      # "melee" | "ranged" | "magic"
    str_bonus: float = 0.0
    dex_bonus: float = 0.0
    con_bonus: float = 0.0
    eva_bonus: float = 0.0
    int_bonus: float = 0.0
    attack_speed_bonus: float = 0.0     # seconds shaved off the base attack interval


ITEMS: dict[str, Item] = {
    # Fishing
    "raw_shrimp": Item("raw_shrimp", "Raw Shrimp", "raw_fish", sell_value=1.0),
    "raw_trout": Item("raw_trout", "Raw Trout", "raw_fish", sell_value=4.0),
    # Cooking outputs
    "cooked_shrimp": Item("cooked_shrimp", "Cooked Shrimp", "food", sell_value=3.0),
    "cooked_trout": Item("cooked_trout", "Cooked Trout", "food", sell_value=9.0),
    "burnt_food": Item("burnt_food", "Burnt Food", "junk", sell_value=0.0),
    # Mining
    "copper_ore": Item("copper_ore", "Copper Ore", "ore", sell_value=2.0),
    "tin_ore": Item("tin_ore", "Tin Ore", "ore", sell_value=2.0),
    "iron_ore": Item("iron_ore", "Iron Ore", "ore", sell_value=6.0),
    "gold_ore": Item("gold_ore", "Gold Ore", "ore", sell_value=25.0),
    # Weapons (Journey to Town quest reward choice)
    "magic_staff": Item(
        "magic_staff", "Magic Staff", "weapon", sell_value=0.0,
        slot="weapon", damage_type="magic", int_bonus=1.0,
    ),
    "wooden_bow": Item(
        "wooden_bow", "Wooden Bow", "weapon", sell_value=0.0,
        slot="weapon", damage_type="ranged", dex_bonus=0.5, attack_speed_bonus=0.5,
    ),
    "bronze_sword": Item(
        "bronze_sword", "Bronze Sword", "weapon", sell_value=0.0,
        slot="weapon", damage_type="melee", str_bonus=1.0,
    ),
}


def get(item_id: str) -> Item | None:
    return ITEMS.get(item_id)


def name_of(item_id: str) -> str:
    item = ITEMS.get(item_id)
    return item.name if item else item_id
