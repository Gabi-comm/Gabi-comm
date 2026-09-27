"""Render the animated contribution maze: pacman_dark.svg + pacman_light.svg.

WakaTime-dashboard look: 1-bit dithered cells on tall rectangles, stat tiles
with a dithered strip, tiny month labels. The year is a Pac-Man maze: walls sit
in the gutters between days and every day you contributed is a pellet (your
four biggest are power pellets).

Each loop is one real game, simulated tick by tick here and baked into SVG +
SMIL (so it animates inside a GitHub README <img>): everyone spawns in the ghost
house mid-year, four ghosts hunt Pac-Man, a power pellet turns them blue and
Pac-Man hunts them back, and a normal ghost touching Pac-Man is GAME OVER.
Then it resets.

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
WALL_CHANCE = 0.45         # share of gutters that try to become walls
HOUSE_W, HOUSE_H, HOUSE_ROW = 6, 3, 2  # ghost house: 6x3 days, rows 2-4, mid-year
POWER_PELLETS = 4          # biggest days become power pellets

# Game timing. One tick = every sprite moves at most one day.
TICK = 0.24                # s per tick
READY = 2.0                # s everyone sits in the ghost house first
RELEASE = (0, 12, 24, 36)  # tick each ghost leaves the house
GHOST_FILLS = ("solid", "l3", "l2", "l1")
FLASH = 8                  # ghosts flash for the last ticks of their fright
RESPAWN = 10               # ticks eaten ghosts wait in the house before rejoining
DANGER = 3                 # Pac-Man dodges ghosts closer than this (steps)
MAX_TICKS = 500            # stalemate cap (~2 min): TIME UP
DEATH = 1.6                # s for Pac-Man's death animation
END_PAUSE = 3.0            # s showing GAME OVER / YOU WIN! before the reset
WALL_FLASH = 1.6           # s the maze flashes after a level is cleared
JUMP = 0.1                 # s sprites are hidden while they hop back to the house

# Levels 1-3: a fresh maze each, ghosts keener (chase odds per ghost), quicker
# (skip one tick in `slow`) and blue for less time (`fright` ticks).
LEVEL_CFG = (
    {"chase": (0.6, 0.45, 0.35, 0.25), "slow": 6, "fright": 28},
    {"chase": (0.7, 0.55, 0.45, 0.35), "slow": 9, "fright": 22},
    {"chase": (0.8, 0.65, 0.55, 0.45), "slow": 14, "fright": 16},
)

# Pac-Man's colour changes every time the game resets to level 1. SVG has no
# runtime randomness, so each day bakes in a shuffled cycle of these.
PAC_COLOURS = {
    "dark": ("#ff7b72", "#d2a8ff", "#7ee787", "#79c0ff", "#f2cc60", "#ff9bce", "#56d4dd"),
    "light": ("#cf222e", "#8250df", "#1a7f37", "#0969da", "#9a6700", "#bf3989", "#1b7c83"),
}
COLOUR_CYCLE = 6           # resets before the colour sequence repeats

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
PACMAN_DEATH = [  # mouth opens upward until he's gone
    [".......", ".#...#.", "##...##", "###.###", "#######", ".#####.", "..###.."],
    [".......", ".......", "#.....#", "##...##", "#######", ".#####.", "..###.."],
    [".......", ".......", ".......", "#.....#", "##...##", ".#####.", "..###.."],
    [".......", ".......", ".......", ".......", ".......", ".#...#.", "..###.."],
    [".......", ".......", ".......", ".......", ".......", ".......", "...#..."],
]
GHOST = ["..###..", ".#####.", "#.##.##", "#######", "#######", "#######", "#.#.#.#"]
GHOST_SCARED = ["..###..", ".#####.", "##.#.##", "#######", "#.#.#.#", "#######", "#.#.#.#"]
GHOST_EYES = [".......", ".......", "##..##.", "##..##.", ".......", ".......", "......."]
POWER = [".##.", "####", "####", ".##."]
ANGLE = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}


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


# ---------------------------------------------------------------- maze
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
    """A walled box mid-year with a two-cell open door on top, and a wall-free
    lobby above it (one column wider each side) so the way out is always clear."""
    c0 = len(weeks) // 2 - HOUSE_W // 2
    cells = {(c0 + x, HOUSE_ROW + y) for x in range(HOUSE_W) for y in range(HOUSE_H)}
    door_cols = (c0 + HOUSE_W // 2 - 1, c0 + HOUSE_W // 2)
    doors = {frozenset(((c, HOUSE_ROW - 1), (c, HOUSE_ROW))) for c in door_cols}
    mid = HOUSE_ROW + HOUSE_H // 2
    return {
        "cells": cells,
        "doors": doors,
        "lobby": {(c, r) for c in range(c0 - 1, c0 + HOUSE_W + 1) for r in range(HOUSE_ROW)},
        "exit": (door_cols[0], HOUSE_ROW - 1),  # just outside the door
        "start": (door_cols[0], mid),
        "slots": [(c0, mid), (c0 + 1, mid), (c0 + HOUSE_W - 2, mid), (c0 + HOUSE_W - 1, mid)],
    }


def build_maze(graph: dict[tuple, set], rng: random.Random, house: dict) -> set[frozenset]:
    """Knock walls into gutters at random, never leaving a dead end or cutting the maze in two.

    The ghost house is fixed: walled all round except its door, open inside,
    and nothing is ever walled off inside the lobby above it."""
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
        if a in house["lobby"] and b in house["lobby"]:
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


def bfs(graph: dict[tuple, set], start: tuple, targets, blocked=frozenset()) -> list[tuple] | None:
    """Shortest path from start to the nearest target, avoiding blocked nodes."""
    targets = targets if isinstance(targets, (set, frozenset)) else {targets}
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
            if m not in prev and m not in blocked:
                prev[m] = n
                todo.append(m)
    return None


def distances(graph: dict[tuple, set], start: tuple) -> dict[tuple, int]:
    dist, todo = {start: 0}, deque([start])
    while todo:
        n = todo.popleft()
        for m in graph[n]:
            if m not in dist:
                dist[m] = dist[n] + 1
                todo.append(m)
    return dist


# ---------------------------------------------------------------- game

def simulate(graph, house, pellets, power, rng, cfg: dict) -> dict:
    """Play one level. Returns per-tick frames plus eat times and the outcome."""
    inside = frozenset(house["cells"])
    pac, facing = house["start"], (1, 0)
    ghosts = [{"at": s, "prev": s, "mode": "house", "release": r, "scared": False}
              for s, r in zip(house["slots"], RELEASE)]
    left = set(pellets)
    eaten_at, fright_until = {}, -1
    frames, outcome, ghosts_eaten = [], "clear", 0

    def snapshot(k):
        frames.append({
            "pac": pac, "facing": facing,
            "ghosts": [(g["at"], ghost_look(g, k), g["mode"] == "house") for g in ghosts],
        })

    def ghost_look(g, k):
        if g["mode"] == "eyes":
            return "eyes"
        if g["scared"]:
            flashing = fright_until - k <= FLASH and k % 2
            return "flash" if flashing else "scared"
        return "normal"

    if pac in left:
        left.discard(pac)
        eaten_at[pac] = 0
    snapshot(0)

    for k in range(1, MAX_TICKS + 1):
        if not left:
            break
        # --- Pac-Man
        hunters = [g for g in ghosts if g["mode"] in ("roam", "leaving") and not g["scared"]]
        prey = [g["at"] for g in ghosts if g["mode"] == "roam" and g["scared"]]
        blocked = set() if pac in inside else set(inside)
        danger = set()
        for g in hunters:
            near = distances(graph, g["at"])
            danger |= {n for n, d in near.items() if d < DANGER}
        route = None
        if prey:
            route = bfs(graph, pac, set(prey), blocked | danger)
        if route is None:
            route = bfs(graph, pac, left, blocked | (danger - {pac}))
        if route is None:
            route = bfs(graph, pac, left, blocked | {g["at"] for g in hunters})
        if route is None or len(route) < 2:  # cornered: back away from the nearest hunter
            far = {n: min((distances(graph, g["at"]).get(n, 99) for g in hunters), default=99)
                   for n in graph[pac] if n not in blocked}
            step = max(sorted(far), key=far.get) if far else pac
        else:
            step = route[1]
        pac_prev, pac = pac, step
        if pac != pac_prev:
            facing = (pac[0] - pac_prev[0], pac[1] - pac_prev[1])
        if pac in left:
            left.discard(pac)
            eaten_at[pac] = k
            if pac in power:
                fright_until = k + cfg["fright"]
                for g in ghosts:
                    g["scared"] = g["mode"] != "eyes"
                    g["last"] = None  # the one moment a ghost may turn around
        if k >= fright_until:
            for g in ghosts:
                g["scared"] = False

        # --- Ghosts. Like the arcade, a roaming ghost never turns back on
        # itself: it picks the best way forward at each junction.
        to_pac = distances(graph, pac)
        for i, g in enumerate(ghosts):
            g["prev"] = g["at"]
            mode = g["mode"]
            if mode == "house":
                if k >= g["release"]:
                    g["mode"] = "leaving"
                continue
            if mode == "leaving":
                path = bfs(graph, g["at"], house["exit"])
                g["at"] = path[1] if path and len(path) > 1 else g["at"]
                if g["at"] == house["exit"]:
                    g["mode"] = "roam"
                continue
            if mode == "eyes":
                slot = house["slots"][i]
                path = bfs(graph, g["at"], slot)
                g["at"] = path[1] if path and len(path) > 1 else slot
                if g["at"] == slot:
                    g.update(mode="house", release=k + RESPAWN)
                continue
            # roam
            options = [n for n in sorted(graph[g["at"]]) if n not in inside]
            forward = [n for n in options if n != g.get("last")] or options
            if g["scared"]:
                if k % 2:  # half speed while blue
                    continue
                g["at"] = max(forward, key=lambda n: (to_pac.get(n, 0), rng.random()))
            elif k % cfg["slow"] == cfg["slow"] - 1:  # a touch slower than Pac-Man
                continue
            elif rng.random() < cfg["chase"][i]:
                g["at"] = min(forward, key=lambda n: (to_pac.get(n, 99), rng.random()))
            else:  # wander, preferring to carry straight on
                last = g.get("last")
                ahead = (2 * g["at"][0] - last[0], 2 * g["at"][1] - last[1]) if last else None
                g["at"] = ahead if ahead in forward and rng.random() < 0.7 else rng.choice(forward)
            g["last"] = g["prev"]

        # --- Collisions: same cell, or passing through each other.
        dead = False
        for g in ghosts:
            if g["mode"] not in ("roam", "leaving"):
                continue
            touch = g["at"] == pac or (g["at"] == pac_prev and g["prev"] == pac)
            if not touch:
                continue
            if g["scared"]:
                g.update(mode="eyes", scared=False)
                ghosts_eaten += 1
            else:
                dead = True
        snapshot(k)
        if dead:
            outcome = "over"
            break
    else:
        outcome = "time" if left else "clear"
    return {"frames": frames, "eaten_at": eaten_at, "outcome": outcome, "ghosts_eaten": ghosts_eaten}


def play(weeks: list[list[dict]], seed: int):
    """Play up to three levels, each on a fresh maze, stopping at the first non-clear."""
    by_node = {(w, d["weekday"]): d for w, week in enumerate(weeks) for d in week}
    house = ghost_house(weeks)
    pellets = {n for n, d in by_node.items() if d["count"] and n not in house["cells"]}
    power = set(sorted(pellets, key=lambda n: (-by_node[n]["count"], n))[:POWER_PELLETS])
    levels = []
    for number, cfg in enumerate(LEVEL_CFG, 1):
        rng = random.Random(seed * 10 + number)
        graph = grid_graph(weeks)
        walls = build_maze(graph, rng, house)
        game = simulate(graph, house, pellets, power, rng, cfg)
        levels.append({"number": number, "walls": walls, "game": game})
        if game["outcome"] != "clear":
            break
    return house, pellets, power, levels


def pick_seed(weeks: list[list[dict]], day_seed: int, tries: int = 12) -> int:
    """Audition a dozen runs for the day and keep the most watchable: one that
    climbs a level or two, eats some ghosts, and ends with the ghosts finally
    catching Pac-Man (or a full three-level win), without dragging on."""
    def score(seed: int) -> float:
        *_, levels = play(weeks, seed)
        last = levels[-1]["game"]["outcome"]
        ticks = sum(len(lv["game"]["frames"]) for lv in levels)
        ghosts = sum(lv["game"]["ghosts_eaten"] for lv in levels)
        return (250 * len(levels) + 20 * min(ghosts, 8)
                + 60 * (last == "over") + 100 * (last == "clear")
                - 400 * (last == "time") - max(0, ticks - 1100))
    return max((day_seed * 100 + j for j in range(tries)), key=score)


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


class Timeline:
    """Builds SMIL attributes on one shared loop of `dur` seconds."""

    def __init__(self, dur: float):
        self.dur = dur
        self.loop = f'dur="{dur:.2f}s" repeatCount="indefinite"'

    def key(self, t: float) -> str:
        return f"{min(max(t / self.dur, 0), 1):.5f}"

    def steps(self, changes: list[tuple[float, str]]) -> str:
        """Discrete values from (time, value) change points; first must be at 0."""
        pts = []
        for t, v in changes:
            if pts and pts[-1][1] == v:
                continue
            if pts and self.key(t) == self.key(pts[-1][0]):
                pts[-1] = (pts[-1][0], v)
            else:
                pts.append((t, v))
        return (f'values="{";".join(v for _, v in pts)}" '
                f'keyTimes="{";".join(self.key(t) for t, _ in pts)}" calcMode="discrete" {self.loop}')

    def show(self, changes: list[tuple[float, bool]]) -> str:
        return f'<animate attributeName="opacity" {self.steps([(t, "1" if on else "0") for t, on in changes])}/>'

    def motion(self, times: list[float], points: list[tuple[float, float]]) -> str:
        """Linear motion through points at times; holds the first/last point outside them."""
        times, points = [0.0] + times + [self.dur], [points[0]] + points + [points[-1]]
        keep = [0] + [i for i in range(1, len(times)) if self.key(times[i]) != self.key(times[i - 1])]
        vals = ";".join(f"{points[i][0]},{points[i][1]}" for i in keep)
        keys = ";".join(self.key(times[i]) for i in keep)
        return f'<animateMotion values="{vals}" keyTimes="{keys}" calcMode="linear" {self.loop}/>'


def render(name: str, theme: dict, weeks: list[list[dict]], stats: list[tuple[str, str]], seed: int) -> str:
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

    # Play the run, then lay the levels end to end on one looping timeline.
    house, pellets, power, levels = play(weeks, seed)
    t = 0.0
    for i, lv in enumerate(levels):
        g = lv["game"]
        lv["start"], lv["play"] = t, t + READY
        lv["end"] = lv["play"] + (len(g["frames"]) - 1) * TICK
        lv["tick"] = lambda k, lv=lv: lv["play"] + k * TICK
        if g["outcome"] == "clear":  # maze flashes, then the next level (or the win)
            lv["flash"] = (lv["end"] + 0.4, lv["end"] + 0.4 + WALL_FLASH)
            t = lv["flash"][1] + JUMP
        if i + 1 < len(levels):
            lv["next"] = t
    final = levels[-1]
    outcome = final["game"]["outcome"]
    died = outcome == "over"
    result_at = final["end"] + (DEATH if died else 0.4)
    if outcome == "clear":
        result_at = final["flash"][1]
    dur = result_at + END_PAUSE
    for lv in levels:
        lv["stop"] = lv.get("next", dur)
    tl = Timeline(dur)

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

    # Floor: faint empty texture on every day (bare inside the house), hover titles.
    for n, d in sorted(by_node.items()):
        x, y = cell_xy(n)
        c = d["count"]
        floor = "none" if n in house["cells"] else "url(#l0)"
        out.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="{floor}" pointer-events="all">'
                   f'<title>{d["date"]:%b %d}: {c} contribution{"s" * (c != 1)}</title></rect>')

    # Maze: the outer frame is fixed; each level has its own walls, which
    # flash when it's cleared and then give way to the next level's.
    fx, fy = PAD - 3, grid_top - 3
    out.append(f'<rect x="{fx}" y="{fy}" width="{grid_w + 6}" height="{7 * ROW - (ROW - CELL_H) + 6}" '
               f'fill="none" stroke="{wall}" stroke-width="2"/>')
    for lv in levels:
        bars = []
        for edge in lv["walls"]:
            a, b = sorted(edge)
            x, y = cell_xy(a)
            if a[0] != b[0]:   # side by side: vertical bar
                bars.append(f'<rect x="{x + CELL_W + 1}" y="{y - 2}" width="2" height="{ROW}"/>')
            else:              # stacked: horizontal bar
                bars.append(f'<rect x="{x - 2}" y="{y + CELL_H + 1}" width="{COL}" height="2"/>')
        shown = [(0, lv is levels[0]), (lv["start"], True)]
        if "flash" in lv:
            f0, f1 = lv["flash"]
            shown += [(f0 + j * 0.2, j % 2 == 1) for j in range(int(WALL_FLASH / 0.2))] + [(f1, True)]
        if "next" in lv:
            shown.append((lv["next"], False))
        out.append(f'<g fill="{wall}" opacity="0">{tl.show(shown)}{"".join(bars)}</g>')

    # Pellets: refilled at the start of every level, gone once eaten.
    for n in sorted(pellets):
        x, y = cell_xy(n)
        shown = [(0, True)]
        for lv in levels:
            shown.append((lv["start"], True))
            if n in lv["game"]["eaten_at"]:
                shown.append((lv["tick"](lv["game"]["eaten_at"][n]), False))
        gone = tl.show(shown)
        if n in power:
            blink = 'dur="0.8s" values="1;0.25" calcMode="discrete" repeatCount="indefinite"'
            out.append(f'<g>{gone}<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="url(#l1)"/>'
                       f'<g transform="translate({x + CELL_W // 2},{y + CELL_H // 2})">'
                       f'{pixel_art(POWER, accent, 3)}<animate attributeName="opacity" {blink}/></g></g>')
        else:
            out.append(f'<g>{gone}<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" '
                       f'fill="{fill_for(by_node[n]["level"], ink)}"/></g>')

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

    def track(get, glide=lambda f: False) -> tuple[list[float], list]:
        """Times + values of one sprite across all levels, holding in the house
        through READY and hopping back (while hidden) between levels.

        Where `glide(frame)` holds, a one-tick stand-still right before a move
        is dropped, so a slowed sprite (a ghost skipping a tick) eases through
        that step over two ticks instead of visibly stopping."""
        times, vals = [], []
        for lv in levels:
            frames = lv["game"]["frames"]
            times.append(lv["start"])
            vals.append(get(frames[0], 0))
            seq = [get(f, k) for k, f in enumerate(frames)]
            for k, f in enumerate(frames):
                if 0 < k < len(seq) - 1 and glide(f) and seq[k] == seq[k - 1] != seq[k + 1]:
                    continue
                times.append(lv["tick"](k))
                vals.append(seq[k])
            if "next" in lv:
                times.append(lv["next"] - JUMP)
                vals.append(vals[-1])
        return times, vals

    # Ghosts: one moving group each, four looks switched per tick; hidden while the maze flashes.
    for i, fill in enumerate(GHOST_FILLS):
        def ghost_pos(f, k, i=i):
            x, y = centre(f["ghosts"][i][0])
            return x, y - 2 if f["ghosts"][i][2] and k % 4 >= 2 else y  # bob while in the house
        times, pts = track(ghost_pos, glide=lambda f, i=i: not f["ghosts"][i][2])  # not while bobbing
        looks = []
        for lv in levels:
            frames = lv["game"]["frames"]
            looks.append((lv["start"], frames[0]["ghosts"][i][1]))
            looks += [(lv["tick"](k), f["ghosts"][i][1]) for k, f in enumerate(frames) if k]
            if "flash" in lv:
                looks.append((lv["flash"][0], "hidden"))
        looks[0] = (0, looks[0][1])
        paint = ink if fill == "solid" else f"url(#{fill})"
        sprites = {"normal": pixel_art(GHOST, paint), "scared": pixel_art(GHOST_SCARED, wall),
                   "flash": pixel_art(GHOST_SCARED, ink), "eyes": pixel_art(GHOST_EYES, ink)}
        out.append("<g>" + tl.motion(times, pts) + "".join(
            f'<g>{art}{tl.show([(t, look == nm) for t, look in looks])}</g>' for nm, art in sprites.items()
        ) + "</g>")

    # Pac-Man: chomping frames turned to face travel; a new colour every reset
    # to level 1 (the colour animation spans COLOUR_CYCLE loops).
    times, pac_pts = track(lambda f, k: centre(f["pac"]))
    _, facings = track(lambda f, k: str(ANGLE[f["facing"]]))
    turns = list(zip([0.0] + times[1:], facings))
    alive = [(0, True)]
    for lv in levels:
        alive.append((lv["start"], True))
        if "next" in lv:
            alive.append((lv["next"] - JUMP, False))
    if died:
        alive.append((final["end"], False))
    chomp = 'dur="0.36s" repeatCount="indefinite" calcMode="discrete"'
    body = (f'<g>{tl.show(alive)}<g><animateTransform attributeName="transform" type="rotate" {tl.steps(turns)}/>'
            f'<g>{pixel_art(PACMAN_OPEN, "inherit")}<animate attributeName="opacity" values="1;0" {chomp}/></g>'
            f'<g>{pixel_art(PACMAN_SHUT, "inherit")}<animate attributeName="opacity" values="0;1" {chomp}/></g>'
            f'</g></g>')
    if died:
        step = DEATH / len(PACMAN_DEATH)
        body += "".join(
            f'<g opacity="0">{pixel_art(art, "inherit")}'
            f'{tl.show([(0, False), (final["end"] + j * step, True), (final["end"] + (j + 1) * step, False)])}</g>'
            for j, art in enumerate(PACMAN_DEATH))
    others = list(PAC_COLOURS[name])
    random.Random(seed).shuffle(others)
    colours = [accent] + others[:COLOUR_CYCLE - 1]
    recolour = (f'<animate attributeName="fill" values="{";".join(colours)}" '
                f'keyTimes="{";".join(f"{j / len(colours):.5f}" for j in range(len(colours)))}" '
                f'calcMode="discrete" dur="{dur * len(colours):.2f}s" repeatCount="indefinite"/>')
    out.append(f'<g fill="{accent}">{recolour}{tl.motion(times, pac_pts)}{body}</g>')

    # Signs under the ghost house, and the level number above the maze.
    hx = cell_xy(min(house["cells"]))[0] + HOUSE_W * COL // 2 - 2
    hy = cell_xy(max(house["cells"]))[1] + ROW + CELL_H // 2 + 4

    def sign(text: str, fill: str, shown: list[tuple[float, bool]]) -> str:
        w = len(text) * 7.2 + 12  # plate so the text sits cleanly over the maze
        return (f'<g opacity="0">{tl.show(shown)}'
                f'<rect x="{hx - w / 2:.0f}" y="{hy - 12}" width="{w:.0f}" height="16" fill="{bg}"/>'
                f'<text x="{hx}" y="{hy}" text-anchor="middle" font-size="12" font-weight="bold" '
                f'fill="{fill}">{text}</text></g>')

    ready = [(0, True)]
    for lv in levels:
        ready += [(lv["start"], True), (lv["play"], False)]
        out.append(f'<text x="{PAD + grid_w}" y="{grid_top - 9}" text-anchor="end" font-size="11" '
                   f'font-weight="bold" fill="{ink}" opacity="0">LEVEL {lv["number"]}'
                   f'{tl.show([(0, lv is levels[0]), (lv["start"], True), (lv["stop"], lv is final)])}</text>')
        if "next" in lv:
            out.append(sign(f"LEVEL {lv['number']} CLEAR!", accent, [(0, False), (lv["flash"][0], True), (lv["next"], False)]))
    out.append(sign("READY!", accent, ready))
    result, colour = {"over": ("GAME OVER", ink), "time": ("TIME UP", ink),
                      "clear": ("YOU WIN!", accent)}[outcome]
    out.append(sign(result, colour, [(0, False), (result_at, True)]))

    out.append("</svg>")
    summary = ", ".join(f"L{lv['number']} {lv['game']['outcome']} ({len(lv['game']['frames'])} ticks, "
                        f"{lv['game']['ghosts_eaten']} ghosts)" for lv in levels)
    print(f"{name}: {summary}; loop {dur:.0f}s, colours {colours}")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use a fake calendar")
    ap.add_argument("--seed", type=int, help="override the daily maze/game seed")
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

    # A new maze and game every day: the best of a dozen auditioned runs.
    seed = args.seed if args.seed is not None else pick_seed(weeks, today.toordinal())
    for name, theme in THEMES.items():
        path = ROOT / f"pacman_{name}.svg"
        path.write_text(render(name, theme, weeks, stats, seed), encoding="utf-8")
        print("wrote", path.name, f"({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
