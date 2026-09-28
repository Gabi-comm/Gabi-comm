"""Render the weekly contribution graph: graph_dark.svg + graph_light.svg.

A year of GitHub contributions as one bar per week, in the WakaTime-dashboard
look of the other cards: stat tiles with a dithered strip, bars shaded with
1-bit dither levels by how busy the week was, dotted guide lines, tiny month
labels. The current week is outlined in orange.

Data is the public contribution calendar (the same one the Pac-Man grid uses;
no token needed).

Usage:
    python scripts/contrib_graph.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from pacman_grid import TZ, fetch_public_calendar, patterns
from profile_card import PAD, THEMES

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 900
TILE_H = 52
CHART_H = 170
AXIS_W = 30                # room for the y-axis numbers
BAR_GAP = 4


def week_totals(weeks: list[list[dict]]) -> list[dict]:
    return [{"start": w[0]["date"], "end": w[-1]["date"], "total": sum(d["count"] for d in w)} for w in weeks]


def stats(weeks: list[list[dict]], bars: list[dict]) -> list[tuple[str, str]]:
    days = [d for w in weeks for d in w]
    total = sum(d["count"] for d in days)
    best = max(bars, key=lambda b: b["total"])
    active = sum(1 for d in days if d["count"])
    longest = run = 0
    for d in days:
        run = run + 1 if d["count"] else 0
        longest = max(longest, run)
    return [
        (f"{total:,}", "Total"),
        (str(best["total"]), f"Best Week ({best['start']:%b %d})"),
        (f"{total / len(bars):.1f}", "Weekly Average"),
        (str(active), "Active Days"),
        (f"{longest}d", "Longest Streak"),
    ]


def nice_max(v: int) -> int:
    """Round the chart's top up to a friendly number."""
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v <= step * 4:
            return max(step, -(-v // step) * step)
    return v


def render(theme: dict, weeks: list[list[dict]], bars: list[dict], tiles: list[tuple[str, str]]) -> str:
    ink, bg, lit = theme["text"], theme["bg"], theme["key"]
    right = WIDTH - PAD
    out: list[str] = []
    y = PAD

    # Title and stat tiles.
    out.append(f'<text x="{PAD}" y="{y + 12}" font-size="15" font-weight="bold" fill="{lit}">Contribution Graph</text>'
               f'<text x="{right}" y="{y + 12}" text-anchor="end" font-size="10" fill="{ink}" opacity="0.6">'
               f'weekly &#183; last year</text>')
    y += 26
    tile_w = (right - PAD) / len(tiles)
    for i, (value, label) in enumerate(tiles):
        x = PAD + i * tile_w
        out.append(f'<rect x="{x:.0f}" y="{y + 4}" width="8" height="{TILE_H - 16}" fill="url(#l1)"/>'
                   f'<text x="{x + 16:.0f}" y="{y + 26}" font-size="24" fill="{ink}">{escape(value)}</text>'
                   f'<text x="{x + 16:.0f}" y="{y + 40}" font-size="11" fill="{ink}" opacity="0.8">{escape(label)}</text>')
    y += TILE_H + 24

    # Chart frame: y axis, dotted guide lines at 0 / half / top.
    top = nice_max(max(b["total"] for b in bars) or 1)
    cx0, cx1 = PAD + AXIS_W, right
    cy0, cy1 = y, y + CHART_H  # top, baseline
    for frac in (0, 0.5, 1):
        gy = round(cy1 - CHART_H * frac)
        out.append(f'<rect x="{cx0}" y="{gy}" width="{cx1 - cx0}" height="1" fill="url(#l0)"/>'
                   f'<text x="{cx0 - 8}" y="{gy + 4}" text-anchor="end" font-size="10" fill="{ink}" '
                   f'opacity="0.6">{round(top * frac)}</text>')

    # Bars: pitch rounded to 4px so the dither patterns line up bar to bar.
    pitch = (cx1 - cx0) / len(bars)
    bar_w = max(4, int((pitch - BAR_GAP) // 4 * 4))
    today = datetime.now(TZ).date()
    peak = max(b["total"] for b in bars) or 1
    for i, b in enumerate(bars):
        x = round((cx0 + i * pitch) / 4) * 4
        h = round(CHART_H * b["total"] / top)
        share = b["total"] / peak
        fill = ink if share >= 0.75 else "url(#l3)" if share >= 0.5 else "url(#l2)" if share >= 0.25 else "url(#l1)"
        tip = f'{b["start"]:%b %d} - {b["end"]:%b %d}: {b["total"]} contribution{"s" * (b["total"] != 1)}'
        out.append(f'<rect x="{x}" y="{cy0}" width="{bar_w}" height="{CHART_H}" fill="transparent"><title>{tip}</title></rect>')
        if h:
            out.append(f'<rect x="{x}" y="{cy1 - h}" width="{bar_w}" height="{h}" fill="{fill}"/>')
        else:
            out.append(f'<rect x="{x}" y="{cy1 - 2}" width="{bar_w}" height="2" fill="url(#l1)"/>')
        if b["start"] <= today <= b["start"] + timedelta(days=6):  # this week: orange outline
            out.append(f'<rect x="{x - 2}" y="{cy1 - max(h, 2) - 2}" width="{bar_w + 4}" height="{max(h, 2) + 4}" '
                       f'fill="none" stroke="{lit}" stroke-width="2"/>')

    # Month labels under the first week of each month; baseline rule.
    out.append(f'<rect x="{cx0}" y="{cy1}" width="{cx1 - cx0}" height="2" fill="{ink}" opacity="0.5"/>')
    seen = set()
    for i, b in enumerate(bars):
        first = next((d for d in (b["start"] + timedelta(days=k) for k in range(7)) if d.day == 1), None)
        if first and first <= b["end"] and first.month not in seen:
            seen.add(first.month)
            out.append(f'<text x="{round(cx0 + i * pitch)}" y="{cy1 + 16}" font-size="10" fill="{ink}" '
                       f'opacity="0.75">{first:%b}</text>')

    # Legend.
    ly = cy1 + 34
    out.append(f'<rect x="{right - 72}" y="{ly - 10}" width="10" height="10" fill="none" stroke="{lit}" stroke-width="2"/>'
               f'<text x="{right - 56}" y="{ly - 2}" font-size="10" fill="{ink}" opacity="0.75">this week</text>')
    height = ly + PAD - 10

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
           f'shape-rendering="crispEdges" font-family="Consolas, \'Courier New\', monospace">',
           f"<defs>{patterns(ink)}</defs>",
           f'<rect width="{WIDTH}" height="{height}" rx="15" fill="{bg}"/>',
           *out, "</svg>"]
    return "\n".join(svg) + "\n"


def main() -> None:
    try:
        weeks = fetch_public_calendar()
    except Exception as err:  # keep yesterday's graph rather than fail the workflow
        print("calendar fetch failed, leaving the graph as it is:", err)
        sys.exit(0)
    bars = week_totals(weeks)
    tiles = stats(weeks, bars)
    print(f"{len(bars)} weeks, {bars[0]['start']} to {bars[-1]['end']}; tiles: {tiles}")
    for name, theme in THEMES.items():
        path = ROOT / f"graph_{name}.svg"
        path.write_text(render(theme, weeks, bars, tiles), encoding="utf-8")
        print("wrote", path.name, f"({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
