"""Importing this package registers every built-in skill.

To add a new skill later: create `game/skills/<name>.py` following the
pattern in fishing.py/mining.py/cooking.py, then import it here.
"""
from game.skills import fishing, mining, cooking  # noqa: F401
