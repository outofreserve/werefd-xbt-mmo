"""Companion species catalog.

New species are just new dict entries -- give them an acquisition method
so the dashboard/help text can describe how to get one.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Species:
    id: str
    name: str
    hp: int
    attack: int
    defense: int
    acquisition: str          # "wild" | "quest" | "shop"
    recruit_chance: float = 0.0   # chance to tame after defeating it in the wild
    shop_price_xbt: float = 0.0   # cost if acquisition == "shop"


SPECIES: dict[str, Species] = {
    "boar_pup": Species(
        id="boar_pup", name="Boar Pup", hp=18, attack=4, defense=2,
        acquisition="wild", recruit_chance=0.35,
    ),
    "pebble": Species(
        id="pebble", name="Pebble the Scout Squirrel", hp=15, attack=3, defense=4,
        acquisition="quest",
    ),
    "trained_falcon": Species(
        id="trained_falcon", name="Trained Falcon", hp=14, attack=6, defense=1,
        acquisition="shop", shop_price_xbt=0.01,
    ),
}


def get(species_id: str) -> Species | None:
    return SPECIES.get(species_id)
