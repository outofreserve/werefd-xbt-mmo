"""Renders the overworld as a realistic ASCII/ANSI terrain grid.

Deliberately generic so adding a new Location to game/world.py (with
coords/biome/glyph set) makes it appear on the map automatically --
no per-location branching here except the small BIOME_STYLES table,
which only needs a new entry when someone invents a new biome.

Plain colored text, redrawn each time -- works over raw nc/telnet.
"""
from __future__ import annotations

from game import world

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
REVERSE = "\x1b[7m"

GREEN = "\x1b[32m"
CYAN = "\x1b[36m"
GRAY = "\x1b[90m"
WHITE = "\x1b[37m"
YELLOW = "\x1b[33m"

GRID_WIDTH = 53
GRID_HEIGHT = 11

# Each biome: a few interchangeable fill glyphs (for organic texture) plus
# an optional overlay rule applied near locations of that biome, layered
# on top of the base voronoi fill.
BIOME_STYLES = {
    "forest": {"fill": [(".", DIM + GREEN), (",", DIM + GREEN), ("`", DIM + GREEN)]},
    "river": {"fill": [(".", DIM + GREEN), (",", DIM + GREEN)], "overlay": "river"},
    "town": {"fill": [(".", DIM + GREEN), (",", DIM + GREEN)], "overlay": "walls"},
    "mountain": {"fill": [(".", DIM + GREEN), (",", DIM + GREEN)], "overlay": "peaks"},
}
DEFAULT_FILL = [(".", DIM + GREEN)]

TRAIL_CHAR = (":", YELLOW)
RIVER_CHAR = ("~", CYAN)
PEAK_CHARS = [("^", GRAY), ("*", GRAY)]
WALL_CHAR = ("#", WHITE)


def _hash2(x: int, y: int) -> int:
    # Cheap deterministic pseudo-random value for stable terrain texture.
    return (x * 73856093) ^ (y * 19349663)


def _nearest_location(x: int, y: int):
    best, best_dist = None, None
    for loc in world.LOCATIONS.values():
        lx, ly = loc.coords
        dist = (lx - x) ** 2 + (ly - y) ** 2
        if best_dist is None or dist < best_dist:
            best, best_dist = loc, dist
    return best


def _bresenham(x0: int, y0: int, x1: int, y1: int):
    points = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        points.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x += sx
        if e2 < dx:
            err += dx
            y += sy
    return points


def _build_grid() -> list[list[tuple[str, str]]]:
    grid = [[None for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]

    # 1. Base terrain: voronoi fill by nearest location's biome.
    for y in range(GRID_HEIGHT):
        for x in range(GRID_WIDTH):
            loc = _nearest_location(x, y)
            style = BIOME_STYLES.get(loc.biome, {"fill": DEFAULT_FILL})
            options = style["fill"]
            ch, color = options[_hash2(x, y) % len(options)]
            grid[y][x] = (ch, color)

    # 2. Biome overlays (river band / mountain peaks / town walls), drawn
    #    near each location that has one, regardless of voronoi region.
    for loc in world.LOCATIONS.values():
        style = BIOME_STYLES.get(loc.biome)
        if not style or "overlay" not in style:
            continue
        lx, ly = loc.coords
        kind = style["overlay"]
        if kind == "river":
            for y in range(GRID_HEIGHT):
                for dx in (-1, 0, 1):
                    x = lx + dx
                    if 0 <= x < GRID_WIDTH:
                        grid[y][x] = RIVER_CHAR
        elif kind == "peaks":
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    x, y = lx + dx, ly + dy
                    if 0 <= x < GRID_WIDTH and 0 <= y < GRID_HEIGHT and (dx, dy) != (0, 0):
                        if abs(dx) + abs(dy) <= 3:
                            grid[y][x] = PEAK_CHARS[_hash2(x, y) % len(PEAK_CHARS)]
        elif kind == "walls":
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    x, y = lx + dx, ly + dy
                    if 0 <= x < GRID_WIDTH and 0 <= y < GRID_HEIGHT and (dx, dy) != (0, 0):
                        grid[y][x] = WALL_CHAR

    # 3. Trails: straight lines between every pair of connected locations.
    seen_pairs = set()
    for loc in world.LOCATIONS.values():
        for dest_id in loc.exits.values():
            dest = world.LOCATIONS[dest_id]
            pair = tuple(sorted((loc.id, dest.id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            for x, y in _bresenham(loc.coords[0], loc.coords[1], dest.coords[0], dest.coords[1]):
                if grid[y][x][0] not in ("~",):  # don't overwrite river crossings
                    grid[y][x] = TRAIL_CHAR

    # 4. Landmarks on top of everything else.
    for loc in world.LOCATIONS.values():
        x, y = loc.coords
        grid[y][x] = (loc.glyph, BOLD + loc.color)

    return grid


def render(player_location: str) -> str:
    grid = _build_grid()
    player_loc = world.get(player_location)
    px, py = player_loc.coords

    lines = [f"{BOLD}{CYAN}== Overworld Map =={RESET}  (N: up  S: down  E: right  W: left)", ""]
    border = "+" + "-" * GRID_WIDTH + "+"
    lines.append(border)
    for y in range(GRID_HEIGHT):
        row = ["|"]
        for x in range(GRID_WIDTH):
            ch, color = grid[y][x]
            if (x, y) == (px, py):
                row.append(f"{REVERSE}{BOLD}{player_loc.color}{ch}{RESET}")
            else:
                row.append(f"{color}{ch}{RESET}")
        row.append("|")
        lines.append("".join(row))
    lines.append(border)
    lines.append("")

    lines.append("Landmarks:")
    for loc in world.LOCATIONS.values():
        marker = f"  {REVERSE}{loc.glyph}{RESET}" if loc.id == player_location else f"  {loc.color}{loc.glyph}{RESET}"
        here = f" {YELLOW}<- you are here{RESET}" if loc.id == player_location else ""
        lines.append(f"{marker} {loc.name}{here}")

    lines.append("")
    if player_loc.exits:
        exits = ", ".join(f"{d.upper()} -> {world.LOCATIONS[dest].name}" for d, dest in player_loc.exits.items())
        lines.append(f"Exits from here: {exits}")
    lines.append(f"{DIM}Use TRAVEL <direction> to move.{RESET}")
    return "\n".join(lines)
