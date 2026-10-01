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
    category: str   # "raw_fish" | "food" | "ore" | "junk" | "misc"
    sell_value: float = 0.0  # fiat value if sold to the generic market, 0 = unsellable


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
}


def get(item_id: str) -> Item | None:
    return ITEMS.get(item_id)


def name_of(item_id: str) -> str:
    item = ITEMS.get(item_id)
    return item.name if item else item_id
