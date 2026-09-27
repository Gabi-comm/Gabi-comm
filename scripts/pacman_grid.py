"""Render the animated contribution maze: pacman_dark.svg + pacman_light.svg.

WakaTime-dashboard look: 1-bit dithered cells on tall rectangles, stat tiles
with a dithered strip, tiny month labels. The year is a Pac-Man maze: walls sit
in the gutters between days, Pac-Man path-finds to every day you contributed,
your four biggest days are power pellets that turn the chasing ghosts
frightened. Everyone spawns in a ghost house in the middle of the year;
the four ghosts leave it one by one. Pure SVG + SMIL, so it animates inside a GitHub README <img>.

Usage:
    python scripts/pacman_grid.py               # live data from your public profile
    python scripts/pacman_grid.py --offline     # fake calendar, no network
"""
import argparse
import os
import random
import re
import urllib.request
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from profile_card import PAD, THEMES, USER, graphql

ROOT = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("Asia/Manila")

# Geometry (px). Dither pixels are 2px, so every coordinate stays a multiple
# of 4 and the patterns line up across cells.
PX = 2
CELL_W, CELL_H = 12, 24
COL, ROW = 16, 28          # pitch; the 4px gutters hold the maze walls
TILE_H = 56
TILES_GAP = 24
MONTH_H = 24
SPEED = 90                 # Pac-Man, px per second
PAUSE = 4.0                # s at the end before the loop restarts
READY = 2.0                # s everyone sits in the ghost house before Pac-Man sets off
GHOST_LAG = (2.0, 4.5, 7.0, 9.5)  # s each ghost trails Pac-Man; staggered release
GHOST_FILLS = ("solid", "l3", "l2", "l1")
HOUSE_W, HOUSE_H, HOUSE_ROW = 6, 3, 2  # ghost house: 6x3 days, rows 2-4, mid-year
POWER_PELLETS = 4          # biggest days become power pellets
FRIGHT = 6.0               # s the ghosts stay frightened
WALL_CHANCE = 0.45         # share of gutters that try to become walls

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount contributionLevel } }
      }
    }
  }
}
"""

PACMAN_OPEN = ["..###..", ".#####.", "####...", "###....", "####...", ".#####.", "..###.."]
PACMAN_SHUT = ["..###..", ".#####.", "#######", "#######", "#######", ".#####.", "..###.."]
GHOST = ["..###..", ".#####.", "#.##.##", "#######", "#######", "#######", "#.#.#.#"]
GHOST_SCARED = ["..###..", ".#####.", "##.#.##", "#######", "#.#.#.#", "#######", "#.#.#.#"]
POWER = [".##.", "####", "####", ".##."]


# ---------------------------------------------------------------- data

def day(d: date, count: int, level: int) -> dict:
    return {"date": d, "weekday": (d.weekday() + 1) % 7, "count": count, "level": level}


def to_weeks(days: list[dict]) -> list[list[dict]]:
    """Group days into Sunday-first columns, like the GitHub calendar."""
    weeks: list[list[dict]] = []
    for d in sorted(days, key=lambda d: d["date"]):
        if not weeks or d["weekday"] == 0:
            weeks.append([])
        weeks[-1].append(d)
    return weeks


def fetch_public_calendar() -> list[list[dict]]:
    """The calendar on github.com/<user>: what visitors see, no token needed."""
    req = urllib.request.Request(f"https://github.com/users/{USER}/contributions",
                                 headers={"User-Agent": "profile-readme"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8")
    cells = re.findall(r'data-date="([\d-]+)" id="(contribution-day-component-[\d-]+)" data-level="(\d)"', html)
    tips = dict(re.findall(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)</tool-tip>', html))
    if len(cells) < 300:
        raise RuntimeError(f"contributions page changed: parsed {len(cells)} days")
    days = []
    for iso, cid, level in cells:
        m = re.match(r"(\d+) contribution", tips.get(cid, ""))
        days.append(day(date.fromisoformat(iso), int(m.group(1)) if m else 0, int(level)))
    return to_weeks(days)


def fetch_api_calendar(token: str) -> list[list[dict]]:
    data = graphql(token, CALENDAR_QUERY, {"login": USER})
    weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return to_weeks([day(date.fromisoformat(d["date"]), d["contributionCount"], LEVELS[d["contributionLevel"]])
                     for w in weeks for d in w["contributionDays"]])


def fake_calendar(today: date) -> list[list[dict]]:
    rng = random.Random(7)
    days = []
    for i in range(365):
        d = today - timedelta(days=364 - i)
        count = rng.choice([1, 2, 3, 5, 8, 13]) if rng.random() < 0.2 else 0
        days.append(day(d, count, 0 if not count else min(4, 1 + count // 4)))
    return to_weeks(days)


def tiles(weeks: list[list[dict]], today: date) -> list[tuple[str, str]]:
    days = {d["date"]: d["count"] for w in weeks for d in w}

    def total(start: date, end: date = today) -> int:
        return sum(c for d, c in days.items() if start <= d <= end)

    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    streak, d = 0, today if days.get(today) else today - timedelta(days=1)
    while days.get(d):
        streak, d = streak + 1, d - timedelta(days=1)
    return [
        (str(days.get(today, 0)), "Today"),
        (str(days.get(today - timedelta(days=1), 0)), "Yesterday"),
        (str(total(today - timedelta(days=today.weekday()))), "This Week"),
        (str(total(today - timedelta(days=6))), "Last 7 Days"),
        (f"{streak}d", "Current Streak"),
        (str(total(month_start)), "This Month"),
        (str(total(last_month_end.replace(day=1), last_month_end)), "Last Month"),
        (str(total(today - timedelta(days=29))), "Last 30 Days"),
        (str(total(today - timedelta(days=89))), "Last 3 Months"),
        (f"{sum(days.values()):,}", "Last Year"),
    ]


# ---------------------------------------------------------------- maze + route
# Nodes are (week, weekday). Walls are removed grid edges.

def grid_graph(weeks: list[list[dict]]) -> dict[tuple, set]:
    nodes = {(w, d["weekday"]) for w, week in enumerate(weeks) for d in week}
    return {n: {m for m in ((n[0] + 1, n[1]), (n[0] - 1, n[1]), (n[0], n[1] + 1), (n[0], n[1] - 1))
                if m in nodes} for n in nodes}


def connected(graph: dict[tuple, set]) -> bool:
    start = next(iter(graph))
    seen, todo = {start}, [start]
    while todo:
        for m in graph[todo.pop()] - seen:
            seen.add(m)
            todo.append(m)
    return len(seen) == len(graph)


def ghost_house(weeks: list[list[dict]]) -> dict:
    """A walled box mid-year with a two-cell door on top."""
    c0 = len(weeks) // 2 - HOUSE_W // 2
    cells = {(c0 + x, HOUSE_ROW + y) for x in range(HOUSE_W) for y in range(HOUSE_H)}
    door_cols = (c0 + HOUSE_W // 2 - 1, c0 + HOUSE_W // 2)
    doors = {frozenset(((c, HOUSE_ROW - 1), (c, HOUSE_ROW))) for c in door_cols}
    mid = HOUSE_ROW + HOUSE_H // 2
    return {
        "cells": cells,
        "doors": doors,
        "start": (door_cols[0], mid),
        "slots": [(c0, mid), (c0 + 1, mid), (c0 + HOUSE_W - 2, mid), (c0 + HOUSE_W - 1, mid)],
    }


def build_maze(graph: dict[tuple, set], rng: random.Random, house: dict) -> set[frozenset]:
    """Knock walls into gutters at random, never leaving a dead end or cutting the maze in two.

    The ghost house is fixed: walled all round except its door, open inside."""
    walls = set()
    inside = house["cells"]
    for a in inside:
        for b in list(graph[a]):
            edge = frozenset((a, b))
            if b not in inside and edge not in house["doors"]:
                graph[a].discard(b)
                graph[b].discard(a)
                walls.add(edge)
    edges = sorted({frozenset((a, b)) for a in graph for b in graph[a]}, key=sorted)
    rng.shuffle(edges)
    for edge in edges:
        a, b = tuple(edge)
        if a in inside or b in inside or edge in house["doors"]:
            continue
        if rng.random() > WALL_CHANCE or len(graph[a]) <= 2 or len(graph[b]) <= 2:
            continue
        graph[a].discard(b)
        graph[b].discard(a)
        if connected(graph):
            walls.add(edge)
        else:
            graph[a].add(b)
            graph[b].add(a)
    return walls


def bfs_path(graph: dict[tuple, set], start: tuple, targets: set) -> list[tuple]:
    prev, todo = {start: None}, deque([start])
    while todo:
        n = todo.popleft()
        if n in targets:
            path = []
            while n is not None:
                path.append(n)
                n = prev[n]
            return path[::-1]
        for m in sorted(graph[n]):
            if m not in prev:
                prev[m] = n
                todo.append(m)
    raise ValueError("unreachable pellet")


def route(graph: dict[tuple, set], start: tuple, pellets: set) -> list[tuple]:
    """Greedy: always head for the nearest uneaten pellet."""
    path, left = [start], set(pellets) - {start}
    while left:
        leg = bfs_path(graph, path[-1], left)
        path += leg[1:]
        left -= set(leg)
    return path


# ---------------------------------------------------------------- drawing

def pixel_art(rows: list[str], fill: str, px: int = PX) -> str:
    """Centre a '#' bitmap on (0, 0) as crisp squares."""
    off = len(rows) * px / 2
    return "".join(
        f'<rect x="{x * px - off}" y="{y * px - off}" width="{px}" height="{px}"/>'
        for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "#"
    ).join([f'<g fill="{fill}">', "</g>"])


def patterns(ink: str) -> str:
    """Level 0-3 dither fills: 4x4 tiles of 2px 'pixels' (level 0 is a faint 1px dot)."""
    def pat(pid, rects, opacity=1):
        body = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{w}"/>' for x, y, w in rects)
        return (f'<pattern id="{pid}" width="4" height="4" patternUnits="userSpaceOnUse">'
                f'<g fill="{ink}" opacity="{opacity}">{body}</g></pattern>')
    return "".join([
        pat("l0", [(0, 0, 1)], 0.45),
        pat("l1", [(0, 0, 2)]),
        pat("l2", [(0, 0, 2), (2, 2, 2)]),
        pat("l3", [(0, 0, 2), (2, 2, 2), (2, 0, 2)]),
    ])


def fill_for(level: int, ink: str) -> str:
    return ink if level >= 4 else f"url(#l{max(level, 1)})"


def discrete(windows: list[tuple[float, float]], dur: float, inside: str, outside: str) -> str:
    """values/keyTimes for a discrete animate that is `inside` during windows (s)."""
    points = [(0.0, outside)]
    for start, end in windows:
        points += [(start / dur, inside), (min(end, dur) / dur, outside)]
    points = [p for i, p in enumerate(points) if i == 0 or p[0] > points[i - 1][0]]
    return (f'values="{";".join(v for _, v in points)}" '
            f'keyTimes="{";".join(f"{t:.4f}" for t, _ in points)}"')


def render(theme: dict, weeks: list[list[dict]], stats: list[tuple[str, str]], seed: int) -> str:
    ink, bg, accent, wall = theme["text"], theme["bg"], theme["key"], theme["value"]
    grid_w = len(weeks) * COL - (COL - CELL_W)
    width = PAD * 2 + grid_w
    grid_top = PAD + 2 * TILE_H + TILES_GAP
    height = grid_top + 7 * ROW + MONTH_H + PAD // 2
    by_node = {(w, d["weekday"]): d for w, week in enumerate(weeks) for d in week}

    def cell_xy(n: tuple) -> tuple[int, int]:
        return PAD + n[0] * COL, grid_top + n[1] * ROW

    def centre(n: tuple) -> tuple[int, int]:
        x, y = cell_xy(n)
        return x + CELL_W // 2, y + CELL_H // 2

    # Maze, pellets, route.
    graph = grid_graph(weeks)
    house = ghost_house(weeks)
    walls = build_maze(graph, random.Random(seed), house)
    pellets = {n for n, d in by_node.items() if d["count"]}
    power = set(sorted(pellets, key=lambda n: (-by_node[n]["count"], n))[:POWER_PELLETS])
    start = house["start"]
    path = route(graph, start, pellets)

    pts = [centre(n) for n in path]
    dist = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        dist.append(dist[-1] + abs(x1 - x0) + abs(y1 - y0))
    length = max(dist[-1], 1.0)
    travel = length / SPEED
    dur = READY + max(GHOST_LAG) + travel + PAUSE
    eaten_at = {}
    for n, d_ in zip(path, dist):
        eaten_at.setdefault(n, READY + d_ / SPEED)  # first visit, seconds

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges" '
        f'font-family="Consolas, \'Courier New\', monospace">',
        f"<defs>{patterns(ink)}</defs>",
        f'<rect width="{width}" height="{height}" rx="15" fill="{bg}"/>',
    ]

    # Stat tiles: dithered strip, big number, small label. Two rows of five.
    tile_w = grid_w / 5
    for i, (value, label) in enumerate(stats):
        x = PAD + (i % 5) * tile_w
        y = PAD + (i // 5) * TILE_H
        out.append(
            f'<rect x="{x:.0f}" y="{y + 4}" width="8" height="{TILE_H - 16}" fill="url(#l1)"/>'
            f'<text x="{x + 16:.0f}" y="{y + 26}" font-size="24" fill="{ink}">{escape(value)}</text>'
            f'<text x="{x + 16:.0f}" y="{y + 40}" font-size="11" fill="{ink}" opacity="0.8">{escape(label)}</text>'
        )

    # Floor: faint empty texture on every day, with a hover title.
    for n, d in sorted(by_node.items()):
        x, y = cell_xy(n)
        c = d["count"]
        floor = "none" if n in house["cells"] else "url(#l0)"
        out.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="{floor}" pointer-events="all">'
                   f'<title>{d["date"]:%b %d}: {c} contribution{"s" * (c != 1)}</title></rect>')

    # Maze: outer frame plus a 2px wall in the gutter for every knocked-out edge.
    fx, fy = PAD - 3, grid_top - 3
    out.append(f'<rect x="{fx}" y="{fy}" width="{grid_w + 6}" height="{7 * ROW - (ROW - CELL_H) + 6}" '
               f'fill="none" stroke="{wall}" stroke-width="2"/>')
    bars = []
    for edge in walls:
        a, b = sorted(edge)
        x, y = cell_xy(a)
        if a[0] != b[0]:   # side by side: vertical bar
            bars.append(f'<rect x="{x + CELL_W + 1}" y="{y - 2}" width="2" height="{ROW}"/>')
        else:              # stacked: horizontal bar
            bars.append(f'<rect x="{x - 2}" y="{y + CELL_H + 1}" width="{COL}" height="2"/>')
    out.append(f'<g fill="{wall}">{"".join(bars)}</g>')

    # Ghost house door (a paler bar) and the READY! sign under the house.
    door = "".join(f'<rect x="{cell_xy(min(e))[0] - 2}" y="{cell_xy(min(e))[1] + CELL_H + 1}" '
                   f'width="{COL}" height="2"/>' for e in house["doors"])
    out.append(f'<g fill="{ink}" opacity="0.55">{door}</g>')
    hx = cell_xy(min(house["cells"]))[0] + HOUSE_W * COL // 2 - 2
    hy = cell_xy(max(house["cells"]))[1] + ROW + CELL_H // 2 + 4
    out.append(f'<text x="{hx}" y="{hy}" text-anchor="middle" font-size="12" font-weight="bold" '
               f'fill="{accent}" opacity="0">READY!<animate attributeName="opacity" values="1;0" '
               f'keyTimes="0;{READY / dur:.4f}" calcMode="discrete" dur="{dur:.2f}s" '
               f'repeatCount="indefinite"/></text>')

    # Pellets vanish the moment Pac-Man reaches them.
    def eat(n: tuple) -> str:
        return (f'<animate attributeName="opacity" values="1;0" keyTimes="0;{eaten_at[n] / dur:.4f}" '
                f'calcMode="discrete" dur="{dur:.2f}s" repeatCount="indefinite"/>')

    for n in sorted(pellets):
        x, y = cell_xy(n)
        d = by_node[n]
        if n in power:
            blink = 'dur="0.8s" values="1;0.25" calcMode="discrete" repeatCount="indefinite"'
            out.append(f'<g>{eat(n)}<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="url(#l1)"/>'
                       f'<g transform="translate({x + CELL_W // 2},{y + CELL_H // 2})">'
                       f'{pixel_art(POWER, accent, 3)}<animate attributeName="opacity" {blink}/></g></g>')
        else:
            out.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" '
                       f'fill="{fill_for(d["level"], ink)}">{eat(n)}</rect>')

    # Month labels under the first column of each month.
    seen = set()
    for w, week in enumerate(weeks):
        month = next((d["date"] for d in week if d["date"].day == 1), None)
        first = week[0]["date"]
        if month is None and w == 0 and first.day <= 7:
            month = first
        if month and month.month not in seen:
            seen.add(month.month)
            out.append(f'<text x="{PAD + w * COL}" y="{grid_top + 7 * ROW + 12}" font-size="10" '
                       f'fill="{ink}" opacity="0.75">{month:%b}</text>')

    loop = f'dur="{dur:.2f}s" repeatCount="indefinite"'

    def keys(times: list[float]) -> str:
        return ";".join(f"{t / dur:.4f}" for t in times)

    # Ghosts wait in the house (bobbing), leave one by one and trail Pac-Man
    # through the maze; power pellets frighten them. Everyone resets each loop.
    fright = [(eaten_at[n], eaten_at[n] + FRIGHT) for n in sorted(power, key=eaten_at.get)]
    flash = [(e - 1.6 + k * 0.4, e - 1.4 + k * 0.4) for _, e in fright for k in range(4)]
    anim = f'calcMode="discrete" {loop}'
    sx, sy = pts[0]
    for slot, lag, fill in zip(house["slots"], GHOST_LAG, GHOST_FILLS):
        gx, gy = centre(slot)
        exit_len = abs(gx - sx) + abs(gy - sy)
        arrive = READY + lag                 # reaches Pac-Man's start `lag` s behind him
        leave = arrive - exit_len / SPEED
        total = exit_len + length
        g_path = f"M{gx},{gy} L{sx},{sy} " + " ".join(f"L{x},{y}" for x, y in pts[1:])
        bob_t = [k * 0.4 for k in range(int(leave / 0.4) + 1)] + [leave]
        bob_v = ["0,0" if k % 2 == 0 else "0,-2" for k in range(len(bob_t) - 1)] + ["0,0"]
        paint = ink if fill == "solid" else f"url(#{fill})"
        out.append(
            f'<g><animateMotion path="{g_path}" keyPoints="0;0;{exit_len / total:.4f};1;1" '
            f'keyTimes="0;{keys([leave, arrive, arrive + travel])};1" calcMode="linear" {loop}/>'
            f'<g><animateTransform attributeName="transform" type="translate" values="{";".join(bob_v)}" '
            f'keyTimes="{keys(bob_t)}" {anim}/>'
            f'<g>{pixel_art(GHOST, paint)}'
            f'<animate attributeName="opacity" {discrete(fright, dur, "0", "1")} {anim}/></g>'
            f'<g opacity="0">{pixel_art(GHOST_SCARED, wall)}'
            f'<animate attributeName="opacity" {discrete(fright, dur, "1", "0")} {anim}/>'
            f'<animate attributeName="fill-opacity" {discrete(flash, dur, "0", "1")} {anim}/></g>'
            f'</g></g>'
        )

    # Pac-Man: READY in the house, then out through the door. Two frames swap
    # for the chomp; rotate="auto" faces travel.
    path_d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    chomp = 'dur="0.36s" repeatCount="indefinite" calcMode="discrete"'
    out.append(
        f'<g>'
        f'<g>{pixel_art(PACMAN_OPEN, accent)}<animate attributeName="opacity" values="1;0" {chomp}/></g>'
        f'<g>{pixel_art(PACMAN_SHUT, accent)}<animate attributeName="opacity" values="0;1" {chomp}/></g>'
        f'<animateMotion path="{path_d}" keyPoints="0;0;1;1" '
        f'keyTimes="0;{keys([READY, READY + travel])};1" calcMode="linear" rotate="auto" {loop}/></g>'
    )
    out.append("</svg>")
    print(f"maze: {len(walls)} walls, {len(pellets)} pellets ({len(power)} power), "
          f"route {len(path)} steps, loop {dur:.0f}s")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use a fake calendar")
    args = ap.parse_args()
    today = datetime.now(TZ).date()

    if args.offline:
        weeks = fake_calendar(today)
    else:
        try:
            weeks = fetch_public_calendar()
        except Exception as err:  # page layout changed: fall back to the API
            print("public calendar failed, using API:", err)
            weeks = fetch_api_calendar(os.environ.get("ACCESS_TOKEN") or os.environ["GITHUB_TOKEN"])
    stats = tiles(weeks, today)
    print("tiles:", stats)

    seed = today.toordinal()  # a new maze every day
    for name, theme in THEMES.items():
        path = ROOT / f"pacman_{name}.svg"
        path.write_text(render(theme, weeks, stats, seed), encoding="utf-8")
        print("wrote", path.name, f"({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
