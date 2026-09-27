"""Render the animated contribution grid: pacman_dark.svg + pacman_light.svg.

WakaTime-dashboard look: 1-bit dithered cells on tall rectangles, stat tiles
with a dithered strip, tiny month labels. A pixel-art Pac-Man snakes through
the year eating every day that has contributions, two dithered ghosts in
pursuit. Pure SVG + SMIL, so it animates inside a GitHub README <img>.

Usage:
    GITHUB_TOKEN=... python scripts/pacman_grid.py
    python scripts/pacman_grid.py --offline      # fake calendar, no network
"""
import argparse
import os
import random
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
COL, ROW = 16, 28          # pitch
TILE_H = 56
TILES_GAP = 20
MONTH_H = 22
SPEED = 360                # Pac-Man, px per second
PAUSE = 2.5                # s at the end before the loop restarts
GHOST_LAG = (0.9, 1.7)     # s behind Pac-Man

LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2,
          "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

CALENDAR_QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date weekday contributionCount contributionLevel } }
      }
    }
  }
}
"""

PACMAN_OPEN = ["..###..", ".#####.", "####...", "###....", "####...", ".#####.", "..###.."]
PACMAN_SHUT = ["..###..", ".#####.", "#######", "#######", "#######", ".#####.", "..###.."]
GHOST = ["..###..", ".#####.", "#.##.##", "#######", "#######", "#######", "#.#.#.#"]


# ---------------------------------------------------------------- data

def fetch_calendar(token: str) -> list[list[dict]]:
    data = graphql(token, CALENDAR_QUERY, {"login": USER})
    weeks = data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return [[{"date": date.fromisoformat(d["date"]), "weekday": d["weekday"],
              "count": d["contributionCount"], "level": LEVELS[d["contributionLevel"]]}
             for d in w["contributionDays"]] for w in weeks]


def fake_calendar(today: date) -> list[list[dict]]:
    rng = random.Random(7)
    start = today - timedelta(days=364 + (today.weekday() + 1) % 7)
    weeks, week = [], []
    d = start
    while d <= today:
        busy = rng.random() < (0.55 if d.weekday() < 5 else 0.25)
        count = rng.choice([1, 2, 3, 5, 8, 13]) if busy else 0
        level = 0 if not count else min(4, 1 + count // 4)
        week.append({"date": d, "weekday": (d.weekday() + 1) % 7, "count": count, "level": level})
        if len(week) == 7 or d == today:
            weeks.append(week)
            week = []
        d += timedelta(days=1)
    return weeks


def tiles(weeks: list[list[dict]], today: date) -> list[tuple[str, str]]:
    days = {d["date"]: d["count"] for w in weeks for d in w}

    def total(start: date, end: date = today) -> int:
        return sum(c for day, c in days.items() if start <= day <= end)

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


# ---------------------------------------------------------------- drawing

def pixel_art(rows: list[str], fill: str) -> str:
    """Centre a '#' bitmap on (0, 0) as crisp 2px squares."""
    off = len(rows) * PX / 2
    return "".join(
        f'<rect x="{x * PX - off}" y="{y * PX - off}" width="{PX}" height="{PX}"/>'
        for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "#"
    ).join([f'<g fill="{fill}">', "</g>"])


def patterns(ink: str) -> str:
    """Level 0-4 dither fills. 4x4 tiles of 2px 'pixels' (level 0 is a faint 1px dot)."""
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
    return ink if level == 4 else f"url(#l{level})"


def snake(weeks: list[list[dict]]) -> list[tuple[int, dict]]:
    """Visit order: down even columns, up odd ones."""
    order = []
    for w, week in enumerate(weeks):
        days = sorted(week, key=lambda d: d["weekday"], reverse=w % 2 == 1)
        order += [(w, d) for d in days]
    return order


def render(theme: dict, weeks: list[list[dict]], stats: list[tuple[str, str]]) -> str:
    ink, bg, accent = theme["text"], theme["bg"], theme["key"]
    grid_w = len(weeks) * COL - (COL - CELL_W)
    width = PAD * 2 + grid_w
    tiles_top = PAD
    grid_top = tiles_top + 2 * TILE_H + TILES_GAP
    height = grid_top + 7 * ROW + MONTH_H + PAD // 2

    def centre(w: int, d: dict) -> tuple[int, int]:
        return PAD + w * COL + CELL_W // 2, grid_top + d["weekday"] * ROW + CELL_H // 2

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
        y = tiles_top + (i // 5) * TILE_H
        out.append(
            f'<rect x="{x:.0f}" y="{y + 4}" width="8" height="{TILE_H - 16}" fill="url(#l1)"/>'
            f'<text x="{x + 16:.0f}" y="{y + 26}" font-size="24" fill="{ink}">{escape(value)}</text>'
            f'<text x="{x + 16:.0f}" y="{y + 40}" font-size="11" fill="{ink}" opacity="0.8">{escape(label)}</text>'
        )

    # Path + timing: Pac-Man moves at constant speed; each pellet vanishes
    # the moment he reaches it.
    order = snake(weeks)
    points = [centre(w, d) for w, d in order]
    dist = [0.0]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        dist.append(dist[-1] + ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    travel = dist[-1] / SPEED
    dur = travel + PAUSE
    run = travel / dur  # fraction of the loop spent moving
    path = "M" + " L".join(f"{x},{y}" for x, y in points)

    # Grid: faint empty texture everywhere, pellets on top that get eaten.
    cells, pellets = [], []
    for i, (w, d) in enumerate(order):
        cx, cy = points[i]
        x, y = cx - CELL_W // 2, cy - CELL_H // 2
        title = f"<title>{d['date']:%b %d}: {d['count']} contribution{'s' * (d['count'] != 1)}</title>"
        cells.append(f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="url(#l0)">{title}</rect>')
        if d["level"]:
            t = dist[i] / dist[-1] * run
            pellets.append(
                f'<rect x="{x}" y="{y}" width="{CELL_W}" height="{CELL_H}" fill="{fill_for(d["level"], ink)}">'
                f'<animate attributeName="opacity" values="1;0" keyTimes="0;{t:.4f}" calcMode="discrete" '
                f'dur="{dur:.2f}s" repeatCount="indefinite"/></rect>'
            )
    out += cells + pellets

    # Month labels under the first column of each month.
    seen = set()
    for w, week in enumerate(weeks):
        first = min(week, key=lambda d: d["date"])["date"]
        month = next((d["date"] for d in week if d["date"].day == 1), None)
        if month is None and w == 0 and first.day <= 7:
            month = first  # grid opens early in a month: label it anyway
        if month and month.month not in seen:
            seen.add(month.month)
            out.append(f'<text x="{PAD + w * COL}" y="{grid_top + 7 * ROW + 12}" font-size="10" '
                       f'fill="{ink}" opacity="0.75">{month:%b}</text>')

    motion = (f'dur="{dur:.2f}s" repeatCount="indefinite" path="{path}" '
              f'keyPoints="0;1;1" keyTimes="0;{run:.4f};1" calcMode="linear"')

    # Ghosts trail Pac-Man along the same path, hidden until they set off.
    for lag, pattern in zip(GHOST_LAG, ("l3", "l2")):
        out.append(
            f'<g opacity="0"><set attributeName="opacity" to="1" begin="{lag}s"/>'
            f'{pixel_art(GHOST, f"url(#{pattern})")}'
            f'<animateMotion {motion} begin="{lag}s"/></g>'
        )

    # Pac-Man: two frames swapping for the chomp; rotate="auto" faces travel.
    chomp = 'dur="0.3s" repeatCount="indefinite" calcMode="discrete"'
    out.append(
        f'<g>'
        f'<g>{pixel_art(PACMAN_OPEN, accent)}<animate attributeName="opacity" values="1;0" {chomp}/></g>'
        f'<g>{pixel_art(PACMAN_SHUT, accent)}<animate attributeName="opacity" values="0;1" {chomp}/></g>'
        f'<animateMotion {motion} rotate="auto"/></g>'
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="use a fake calendar")
    args = ap.parse_args()
    today = datetime.now(TZ).date()

    if args.offline:
        weeks = fake_calendar(today)
    else:
        weeks = fetch_calendar(os.environ.get("ACCESS_TOKEN") or os.environ["GITHUB_TOKEN"])
    stats = tiles(weeks, today)
    print("tiles:", stats)

    for name, theme in THEMES.items():
        path = ROOT / f"pacman_{name}.svg"
        path.write_text(render(theme, weeks, stats), encoding="utf-8")
        print("wrote", path.name, f"({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
