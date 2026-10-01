"""ANSI text-screen rendering for the dashboard-style commands.

Plain, redrawn text blocks (clear + home + formatted text) rather than a
persistent curses app, so any raw TCP client (nc, telnet, our client.py)
renders it correctly.
"""
from __future__ import annotations

from game import chat, combat, companions, db, items, mapview, quests, travel, world
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


def _pad(text: str, width: int) -> str:
    """Pad/truncate a string to a visible width (ignores ANSI codes for length)."""
    visible_len = len(_strip_ansi(text))
    if visible_len >= width:
        return text
    return text + " " * (width - visible_len)


def _strip_ansi(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "\x1b" and i + 1 < n and text[i + 1] == "[":
            j = i + 2
            while j < n and text[j] not in "mK":
                j += 1
            i = j + 1
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _columns(col_lines: list[list[str]], widths: list[int], gap: str = " | ") -> list[str]:
    """Lay out several lists of lines side by side as fixed-width columns."""
    height = max(len(c) for c in col_lines)
    rows = []
    for i in range(height):
        parts = []
        for lines, width in zip(col_lines, widths):
            cell = lines[i] if i < len(lines) else ""
            parts.append(_pad(cell, width))
        rows.append(gap.join(parts).rstrip())
    return rows


def dashboard(
    username: str,
    last_event: str = "",
    online_count: int | None = None,
    players_here: list[str] | None = None,
) -> str:
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
    state = db.get_game_state()
    if online_count is None:
        online_count = db.count_players()
    players_here = players_here or []

    travelling, remaining = travel.is_travelling(player)

    import time as _time
    now = _time.strftime("%Y-%m-%d %H:%M:%S UTC", _time.gmtime())

    where = f"On the road to {world.get(player.travel_destination).name} (ETA {remaining:.0f}s)" if travelling else loc.name
    header = (
        f"{BOLD}{CYAN}WE'RE F'D: AN XBT MMO // DASHBOARD{RESET}"
        f"{' ' * 10}{DIM}{now}{RESET}\n"
        f"{BOLD}{username}{RESET} | {where} | Hash: {player.hash_power_ghs:g} GH/s"
        f" | Companion: {companion_line}"
    )

    # --- Left column: resources, skills, quests -----------------------
    left = [f"{BOLD}{CYAN}RESOURCES{RESET}"]
    left.append(f"Fiat     ${player.fiat:,.2f}")
    left.append(f"XBT      {player.xbt:.8f}")
    left.append(f"Hash pwr {player.hash_power_ghs:g} GH/s")
    left.append("")
    left.append(f"{BOLD}{CYAN}SKILLS{RESET}")
    for skill_id, skill in SKILLS.items():
        xp = xp_map.get(skill_id, 0.0)
        level = level_for_xp(xp)
        left.append(f" {skill.name:<10} Lv {level:>2} ({xp:.0f} xp)")
    left.append("")
    left.append(f"{BOLD}{CYAN}ACTIVE QUESTS{RESET}")
    if active_quests:
        for q in active_quests:
            left.append(f" {q.name}")
    else:
        left.append(" (none)")

    # --- Center column: location view ----------------------------------
    if travelling:
        center = [f"{BOLD}{CYAN}TRAVELLING{RESET}"]
        center.append(f"Heading to {world.get(player.travel_destination).name}.")
        center.append(f"Arriving in {remaining:.0f}s.")
        center.append("")
        center.append(f"{DIM}Other commands are unavailable until you arrive.{RESET}")
    else:
        center = [f"{BOLD}{CYAN}LOCATION: {loc.name}{RESET}"]
        for chunk_line in _wrap(loc.description, 36):
            center.append(chunk_line)
        center.append("")
        if loc.exits:
            center.append("Exits:")
            for d, dest in loc.exits.items():
                center.append(f"  {d}({world.LOCATIONS[dest].name})")
        if loc.skills:
            center.append("")
            center.append(f"Train here: {', '.join(loc.skills)}")
        if loc.monsters:
            center.append(f"Monsters: {', '.join(loc.monsters)}")
        center.append("")
        others = [p for p in players_here if p != username]
        center.append(f"Players here: {', '.join(others) if others else '(just you)'}")
        for ts, who, msg in chat.recent(player.location)[-5:]:
            center.append(f"{DIM}[{who}] {msg}{RESET}")
        center.append(f"{DIM}Type MAP for the full overworld view. SAY <msg> to chat.{RESET}")

    # --- Right column: command menu -------------------------------------
    right = [f"{BOLD}{CYAN}MENU{RESET}"]
    right.append(f"{YELLOW}ECONOMY{RESET}")
    right.append(" BUY HASH <n>")
    right.append(" MARKET BUY/SELL <amt>")
    right.append(" STATUS")
    right.append(f"{YELLOW}SKILLS{RESET}")
    right.append(" TRAIN <skill> <action>")
    right.append(" SKILLS / INVENTORY")
    right.append(f"{YELLOW}WORLD{RESET}")
    right.append(" TRAVEL <direction>")
    right.append(" MAP / QUESTS")
    right.append(f"{YELLOW}COMBAT{RESET}")
    right.append(" PVE <monster>")
    right.append(" DUEL CHALLENGE <user>")
    right.append(f"{YELLOW}SYSTEM{RESET}")
    right.append(" HELP  QUIT")

    body = _columns([left, center, right], [26, 38, 26])

    footer_rule = "-" * 94
    event_line = f"LAST EVENT: {last_event}" if last_event else "LAST EVENT: (none yet)"
    world_line = (
        f"WORLD  Fiat supply: ${state.get('total_fiat_supply', 0):,.2f} | "
        f"Pool: ${state.get('pool_fiat', 0):,.2f} | "
        f"XBT supply: {state.get('total_xbt_supply', 0):.8f} | "
        f"Players: {online_count}"
    )

    lines = [CLEAR, header, "", *body, "", footer_rule, event_line, footer_rule, world_line]
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


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


def map_screen(username: str, players_here: list[str] | None = None) -> str:
    player = db.get_player(username)
    out = CLEAR + mapview.render(player.location)
    others = [p for p in (players_here or []) if p != username]
    if others:
        out += f"\n{BOLD}{CYAN}Players here:{RESET} {', '.join(others)}"
    return out
