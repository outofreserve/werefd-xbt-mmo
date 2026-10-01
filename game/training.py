"""Skill training: resolves TRAIN commands against the skill registry."""
from __future__ import annotations

import random
import time

from game import db, items
from game.skills import base as skills_base
from game.skills.base import SKILLS


def train(username: str, skill_id: str, action_id: str) -> tuple[bool, str]:
    skill = SKILLS.get(skill_id.upper())
    if skill is None:
        return False, f"Unknown skill '{skill_id}'. Known skills: {', '.join(SKILLS)}."
    action = skill.action(action_id)
    if action is None:
        return False, f"Unknown action '{action_id}' for {skill.name}. Try: {', '.join(skill.actions)}."

    player = db.get_player(username)
    if player.location not in skill.location_ids:
        return False, f"You need to be at the right location to train {skill.name} here."

    xp_before = db.get_xp(username, skill.id)
    level = skills_base.level_for_xp(xp_before)
    if level < action.level_req:
        return False, f"Requires {skill.name} level {action.level_req} (you're {level})."

    cooldown_key = f"TRAIN:{skill.id}:{action.id}"
    remaining = action.cooldown - (time.time() - db.get_cooldown(username, cooldown_key))
    if remaining > 0:
        return False, f"Not ready yet. Try again in {remaining:.0f}s."

    with db.connect() as conn:
        for item_id, qty in action.consumes.items():
            if db.get_item_qty(username, item_id) < qty:
                return False, f"You need {qty}x {items.name_of(item_id)} to do that."
        for item_id, qty in action.consumes.items():
            db.remove_item(username, item_id, qty, conn=conn)

        success = random.random() < skills_base.success_chance(action, level)
        lines = []
        if success:
            if action.produces:
                db.add_item(username, action.produces, action.quantity, conn=conn)
                lines.append(f"Success! You get {action.quantity}x {items.name_of(action.produces)}.")
            db.add_xp(username, skill.id, action.xp, conn=conn)
            lines.append(f"+{action.xp:g} {skill.name} XP.")
        else:
            if action.fail_produces:
                db.add_item(username, action.fail_produces, 1, conn=conn)
            lines.append(f"You fail and ruin the materials ({items.name_of(action.fail_produces)}).")

    db.set_cooldown(username, cooldown_key, time.time())

    xp_after = db.get_xp(username, skill.id)
    level_after = skills_base.level_for_xp(xp_after)
    if level_after > level:
        lines.append(f"Level up! {skill.name} is now level {level_after}.")
    return True, "\n".join(lines)
