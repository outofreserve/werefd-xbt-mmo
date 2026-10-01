"""World map: locations and travel.

Deliberately small and declarative so new regions can be added later by
appending to LOCATIONS -- nothing else needs to change.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Location:
    id: str
    name: str
    description: str
    exits: dict[str, str]          # direction/command -> location id
    skills: list[str] = field(default_factory=list)   # skill ids trainable here
    monsters: list[str] = field(default_factory=list)  # monster ids found here


LOCATIONS: dict[str, Location] = {
    "camp": Location(
        id="camp",
        name="Wilderness Camp",
        description=(
            "A battered canvas tent and a dying fire mark the edge of civilization. "
            "A forest path leads east toward the sound of running water."
        ),
        exits={"east": "riverside"},
        monsters=["boar"],
    ),
    "riverside": Location(
        id="riverside",
        name="Riverside",
        description=(
            "A wide river cuts through the forest, shallow enough to fish. "
            "The path continues east into Town, and west back to camp."
        ),
        exits={"west": "camp", "east": "town"},
        skills=["FISHING"],
    ),
    "town": Location(
        id="town",
        name="Town",
        description=(
            "Smoke rises from chimneys and a kitchen hearth burns in the square. "
            "A trail leads north into the hills toward an old quarry, "
            "and the river road runs west."
        ),
        exits={"west": "riverside", "north": "quarry"},
        skills=["COOKING"],
    ),
    "quarry": Location(
        id="quarry",
        name="Old Quarry",
        description=(
            "Pickaxe-scarred rock walls surround a played-out quarry, still rich "
            "with ore. The trail back to Town runs south."
        ),
        exits={"south": "town"},
        skills=["MINING"],
    ),
}

STARTING_LOCATION = "camp"


def get(location_id: str) -> Location | None:
    return LOCATIONS.get(location_id)


def describe(location_id: str) -> str:
    loc = LOCATIONS[location_id]
    lines = [f"== {loc.name} ==", loc.description]
    if loc.exits:
        exits = ", ".join(f"{d} -> {LOCATIONS[dest].name}" for d, dest in loc.exits.items())
        lines.append(f"Exits: {exits}")
    if loc.skills:
        lines.append(f"Skills trainable here: {', '.join(loc.skills)}")
    if loc.monsters:
        lines.append(f"Monsters nearby: {', '.join(loc.monsters)}")
    return "\n".join(lines)
