"""Shared, depletable resource nodes.

Unlike ordinary (unlimited) skill actions, a node-gated SkillAction can
only be performed while a matching node at the player's location is
"available". The first player to harvest it depletes it -- for everyone
-- until it respawns, so players genuinely race for it. Declarative and
small: add a NodeType and a row in SEED_NODES to introduce a new one;
nothing else needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class NodeType:
    id: str
    name: str
    respawn_seconds: float


NODE_TYPES: dict[str, NodeType] = {
    "iron_vein": NodeType("iron_vein", "Iron Vein", respawn_seconds=45.0),
    "gold_vein": NodeType("gold_vein", "Gold Vein", respawn_seconds=180.0),
}

# (location_id, node_type_id, label) -- seeded once, the first time the
# database is created. Multiple nodes of the same type can exist at one
# location (e.g. two iron veins) to reduce contention between players.
SEED_NODES = [
    ("quarry", "iron_vein", "Iron Vein (north wall)"),
    ("quarry", "iron_vein", "Iron Vein (east wall)"),
    ("quarry", "gold_vein", "Gold Vein (deep shaft)"),
]


def get(type_id: str) -> NodeType | None:
    return NODE_TYPES.get(type_id)
