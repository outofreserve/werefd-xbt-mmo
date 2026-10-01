"""ANSI text-screen rendering for the dashboard-style commands.

Plain, redrawn text blocks (clear + home + formatted text) rather than a
persistent curses app, so any raw TCP client (nc, telnet, our client.py)
renders it correctly.
"""
from __future__ import annotations

from game import combat, companions, db, items, quests, world
from game.skills.base import SKILLS, level_for_xp, xp_to_next_level

CLEAR = "\x1b[2J\x1b[H"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
CYAN = "\x1b[36m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"


def _bar(fraction: float, width: int = 20) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(width * fraction)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _rule(title: str) -> str:
    return f"{BOLD}{CYAN}== {title} =={RESET}"


def dashboard(username: str) -> str:
    player = db.get_player(username)
    loc = world.get(player.location)
    xp_map = db.get_all_xp(username)
    active_quests = [q for q, status in quests.list_for_player(username) if status == "active"]
    companion_line = "none"
    if player.active_companion_id:
        comp = db.get_companion(player.active_companion_id)
        if comp:
            species = companions.get(comp["species_id"])
            companion_line = f"{comp['nickname']} (HP {species.hp}/ATK {species.attack}/DEF {species.defense})"

    lines = [CLEAR, _rule(f"{username}'s Dashboard"), ""]
    lines.append(f"Location : {BOLD}{loc.name}{RESET}")
    lines.append(f"Fiat     : ${player.fiat:,.2f}   XBT: {player.xbt:.8f}   Hash: {player.hash_power_ghs:g} GH/s")
    lines.append(f"Companion: {companion_line}")
    lines.append("")
    lines.append(_rule("Skills"))
    for skill_id, skill in SKILLS.items():
        xp = xp_map.get(skill_id, 0.0)
        level = level_for_xp(xp)
        to_next, _ = xp_to_next_level(xp)
        progress = "" if to_next is None else f" ({to_next:.0f} xp to next)"
        lines.append(f"  {skill.name:<10} Lv {level:>2}{progress}")
    lines.append("")
    lines.append(_rule("Active quests"))
    if active_quests:
        for q in active_quests:
            lines.append(f"  - {q.name}: {q.description}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(f"{DIM}Type HELP for commands, SKILLS/INVENTORY/QUESTS/MAP for detail screens.{RESET}")
    return "\n".join(lines)


def skills_screen(username: str) -> str:
    xp_map = db.get_all_xp(username)
    lines = [CLEAR, _rule("Skills"), ""]
    for skill_id, skill in SKILLS.items():
        xp = xp_map.get(skill_id, 0.0)
        level = level_for_xp(xp)
        to_next, _ = xp_to_next_level(xp)
        frac = 0.0 if to_next is None else 1 - (to_next / max(1, xp + to_next))
        lines.append(f"{skill.name} (Lv {level}, {xp:.0f} xp) {_bar(frac)}")
        for action in skill.actions.values():
            lock = "" if level >= action.level_req else f" {YELLOW}[locked, need Lv {action.level_req}]{RESET}"
            lines.append(f"    - {action.name} (+{action.xp:g} xp){lock}")
    return "\n".join(lines)


def inventory_screen(username: str) -> str:
    inv = db.get_inventory(username)
    lines = [CLEAR, _rule("Inventory"), ""]
    if not inv:
        lines.append("  (empty)")
    for item_id, qty in sorted(inv.items()):
        lines.append(f"  {qty:>4}x {items.name_of(item_id)}")
    return "\n".join(lines)


def quests_screen(username: str) -> str:
    lines = [CLEAR, _rule("Quests"), ""]
    for quest, status in quests.list_for_player(username):
        tag = {"active": YELLOW + "[active]", "complete": GREEN + "[complete]"}.get(status, DIM + "[" + status + "]")
        lines.append(f"  {tag}{RESET} {quest.name} -- {quest.description}")
    return "\n".join(lines)


def companions_screen(username: str) -> str:
    comps = db.get_companions(username)
    player = db.get_player(username)
    lines = [CLEAR, _rule("Companions"), ""]
    if not comps:
        lines.append("  (none yet -- defeat wild monsters, complete quests, or buy one)")
    for comp in comps:
        species = companions.get(comp["species_id"])
        active = " (ACTIVE)" if comp["id"] == player.active_companion_id else ""
        lines.append(
            f"  #{comp['id']} {comp['nickname']}{active} -- "
            f"HP {species.hp} ATK {species.attack} DEF {species.defense}"
        )
    return "\n".join(lines)


def map_screen(username: str) -> str:
    player = db.get_player(username)
    lines = [CLEAR, _rule("Map"), ""]
    for loc_id, loc in world.LOCATIONS.items():
        marker = f" {GREEN}<- you are here{RESET}" if loc_id == player.location else ""
        lines.append(f"  {loc.name}{marker}")
    lines.append("")
    lines.append(world.describe(player.location))
    return "\n".join(lines)
