"""Combat attribute "skills": Strength, Dexterity, Constitution, Evasion,
Intelligence.

These are registered like any other skill (so they show up on the
dashboard/SKILLS screen and level up on the same RuneScape-style XP curve),
but they have no `location_ids`/`actions` -- TRAIN can't touch them. They
only gain XP automatically as a side effect of combat (see game/battle.py).
"""
from __future__ import annotations

from game.skills.base import Skill, register_skill

STRENGTH = Skill(id="STRENGTH", name="Strength", location_ids=[])
DEXTERITY = Skill(id="DEXTERITY", name="Dexterity", location_ids=[])
CONSTITUTION = Skill(id="CONSTITUTION", name="Constitution", location_ids=[])
EVASION = Skill(id="EVASION", name="Evasion", location_ids=[])
INTELLIGENCE = Skill(id="INTELLIGENCE", name="Intelligence", location_ids=[])

for _skill in (STRENGTH, DEXTERITY, CONSTITUTION, EVASION, INTELLIGENCE):
    register_skill(_skill)
