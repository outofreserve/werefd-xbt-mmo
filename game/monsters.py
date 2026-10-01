"""Wild monster catalog for PvE combat."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Monster:
    id: str
    name: str
    hp: int
    attack: int
    defense: int
    fiat_reward: float
    recruit_species: str | None = None  # species id players may tame on victory
    attack_interval: float = 3.0        # seconds between the monster's own swings
    damage_type: str = "melee"          # flavor text only for now


MONSTERS: dict[str, Monster] = {
    "boar": Monster(
        id="boar", name="Wild Boar", hp=20, attack=3, defense=2,
        fiat_reward=15.0, recruit_species="boar_pup",
    ),
}


def get(monster_id: str) -> Monster | None:
    return MONSTERS.get(monster_id)
