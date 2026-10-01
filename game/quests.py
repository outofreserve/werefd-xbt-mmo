"""Quest framework.

Quests are declarative: an id, description, a `check(username)` predicate
re-evaluated against live player state, and a reward. New quests are new
entries in QUESTS -- no engine changes required. `auto_start=True` quests
begin the moment an account is created (used for the tutorial quest);
future quests can require prerequisites via their own `check`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from game import companions, db


@dataclass
class Quest:
    id: str
    name: str
    description: str
    check: Callable[[str], bool]
    reward_fiat: float = 0.0
    reward_items: dict[str, int] = field(default_factory=dict)
    reward_companion: str | None = None
    auto_start: bool = True


QUESTS: dict[str, Quest] = {}


def register(quest: Quest):
    QUESTS[quest.id] = quest


register(Quest(
    id="journey_to_town",
    name="Journey to Town",
    description="Travel from the Wilderness Camp to Town.",
    check=lambda username: db.get_player(username).location == "town",
    reward_fiat=50.0,
    reward_companion="pebble",
))


def start_default_quests(username: str):
    for quest in QUESTS.values():
        if quest.auto_start and db.get_quest_status(username, quest.id) is None:
            db.set_quest_status(username, quest.id, "active")


def check_and_complete(username: str) -> list[str]:
    """Re-check all of a player's active quests; complete+reward any that
    now satisfy their condition. Returns human-readable completion lines."""
    messages = []
    statuses = db.get_all_quest_status(username)
    for quest_id, status in statuses.items():
        if status != "active":
            continue
        quest = QUESTS.get(quest_id)
        if quest is None or not quest.check(username):
            continue
        with db.connect() as conn:
            if quest.reward_fiat:
                conn.execute(
                    "UPDATE players SET fiat = fiat + ? WHERE username = ?",
                    (quest.reward_fiat, username),
                )
                conn.execute(
                    "UPDATE game_state SET total_fiat_supply = total_fiat_supply + ? WHERE id = 1",
                    (quest.reward_fiat,),
                )
            for item_id, qty in quest.reward_items.items():
                db.add_item(username, item_id, qty, conn=conn)
            db.set_quest_status(username, quest_id, "complete", conn=conn)
        reward_bits = []
        if quest.reward_fiat:
            reward_bits.append(f"${quest.reward_fiat:,.2f}")
        if quest.reward_items:
            reward_bits.append(", ".join(f"{q}x {i}" for i, q in quest.reward_items.items()))
        if quest.reward_companion:
            species = companions.get(quest.reward_companion)
            comp_id = db.add_companion(username, species.id, species.name)
            reward_bits.append(f"companion #{comp_id} {species.name}")
        messages.append(
            f"Quest complete: {quest.name}! Reward: {', '.join(reward_bits) if reward_bits else 'bragging rights'}."
        )
    return messages


def list_for_player(username: str) -> list[tuple[Quest, str]]:
    statuses = db.get_all_quest_status(username)
    return [(q, statuses.get(q.id, "not started")) for q in QUESTS.values()]
