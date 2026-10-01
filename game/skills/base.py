"""Skill framework: XP curve, level math, and the skill/action registry.

To add a new skill in the future: create `game/skills/<name>.py` defining
a `Skill` with its `SkillAction`s, then import it in
`game/skills/__init__.py`. Nothing else needs to change -- the dashboard,
TRAIN command, and leveling math all work off the registry.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_LEVEL = 99

# RuneScape-style XP curve: cumulative XP needed to reach a level grows
# roughly geometrically. Precompute a table once at import time.
_XP_AT_LEVEL: list[int] = [0]  # index 0 unused, level 1 requires 0 xp.
_running = 0.0
for _level in range(1, MAX_LEVEL):
    _running += (_level + 300.0 * (2.0 ** (_level / 7.0)))
    _XP_AT_LEVEL.append(int(_running / 4.0))


def level_for_xp(xp: float) -> int:
    """Return the level (1-99) reached by the given total xp."""
    level = 1
    for lvl in range(1, MAX_LEVEL + 1):
        if xp >= _XP_AT_LEVEL[lvl - 1]:
            level = lvl
        else:
            break
    return level


def xp_for_level(level: int) -> int:
    level = max(1, min(level, MAX_LEVEL))
    return _XP_AT_LEVEL[level - 1]


def xp_to_next_level(xp: float) -> tuple[int | None, int]:
    """Return (xp_needed_for_next_level, current_level). xp_needed is None at max level."""
    level = level_for_xp(xp)
    if level >= MAX_LEVEL:
        return None, level
    return int(xp_for_level(level + 1) - xp), level


@dataclass
class SkillAction:
    id: str
    name: str
    level_req: int
    xp: float
    cooldown: float            # seconds the action takes
    produces: str | None = None        # item id granted on success
    consumes: dict[str, int] = field(default_factory=dict)  # item id -> qty required
    base_success: float = 1.0          # success chance at level_req, scales toward 1.0 with level
    quantity: int = 1                  # how many of `produces` are granted per success
    fail_produces: str | None = None   # item id granted instead, on failure (e.g. burnt food)
    node_type: str | None = None       # if set, requires an available shared resource_node of this type


@dataclass
class Skill:
    id: str
    name: str
    location_ids: list[str]            # where this skill can be trained
    actions: dict[str, SkillAction] = field(default_factory=dict)

    def action(self, action_id: str) -> SkillAction | None:
        return self.actions.get(action_id.lower())


SKILLS: dict[str, Skill] = {}


def register_skill(skill: Skill):
    SKILLS[skill.id] = skill


def success_chance(action: SkillAction, level: int) -> float:
    """Success chance scales linearly from base_success at level_req up to
    1.0 at max level, and is always 1.0 if base_success is already 1.0
    (gathering skills with no failure, like RuneScape's tiered resources)."""
    if action.base_success >= 1.0:
        return 1.0
    if level <= action.level_req:
        return action.base_success
    span = MAX_LEVEL - action.level_req
    progress = (level - action.level_req) / span if span > 0 else 1.0
    return min(1.0, action.base_success + (1.0 - action.base_success) * progress)
