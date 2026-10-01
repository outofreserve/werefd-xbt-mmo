"""Skill training: resolves TRAIN commands against the skill registry."""
from __future__ import annotations

import random
import time

from game import db, items, resource_nodes, travel
from game.skills import base as skills_base
from game.skills.base import SKILLS


def train(username: str, skill_id: str, action_id: str, now: float | None = None) -> tuple[bool, str]:
    now = now if now is not None else time.time()
    travel.resolve_arrival(username, now)
    player = db.get_player(username)

    travelling, remaining = travel.is_travelling(player, now)
    if travelling:
        return False, f"You're on the road, arriving in {remaining:.0f}s."

    skill = SKILLS.get(skill_id.upper())
    if skill is None:
        return False, f"Unknown skill '{skill_id}'. Known skills: {', '.join(SKILLS)}."
    action = skill.action(action_id)
    if action is None:
        return False, f"Unknown action '{action_id}' for {skill.name}. Try: {', '.join(skill.actions)}."

    if player.location not in skill.location_ids:
        return False, f"You need to be at the right location to train {skill.name} here."

    xp_before = db.get_xp(username, skill.id)
    level = skills_base.level_for_xp(xp_before)
    if level < action.level_req:
        return False, f"Requires {skill.name} level {action.level_req} (you're {level})."

    cooldown_key = f"TRAIN:{skill.id}:{action.id}"
    remaining_cd = action.cooldown - (now - db.get_cooldown(username, cooldown_key))
    if remaining_cd > 0:
        return False, f"Not ready yet. Try again in {remaining_cd:.0f}s."

    node = None
    if action.node_type:
        node_kind = resource_nodes.get(action.node_type)
        nodes = [n for n in db.get_nodes(player.location) if n["type_id"] == action.node_type]
        if not nodes:
            return False, f"There's no {node_kind.name} here."
        available = [n for n in nodes if n["available_at"] <= now]
        if not available:
            soonest = min(n["available_at"] for n in nodes) - now
            return False, f"All {node_kind.name} nodes here are depleted. Soonest respawn in {soonest:.0f}s."
        node = available[0]

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
            if node is not None:
                node_kind = resource_nodes.get(action.node_type)
                db.deplete_node(node["id"], now + node_kind.respawn_seconds, conn=conn)
                lines.append(f"The {node['label']} is tapped out -- it'll respawn in {node_kind.respawn_seconds:.0f}s.")
        else:
            if action.fail_produces:
                db.add_item(username, action.fail_produces, 1, conn=conn)
            lines.append(f"You fail and ruin the materials ({items.name_of(action.fail_produces)}).")

    db.set_cooldown(username, cooldown_key, now)

    xp_after = db.get_xp(username, skill.id)
    level_after = skills_base.level_for_xp(xp_after)
    if level_after > level:
        lines.append(f"Level up! {skill.name} is now level {level_after}.")
    return True, "\n".join(lines)
