"""Render the contribution-activity timeline: activity_dark.svg + activity_light.svg.

The same "Contribution activity" GitHub shows on the profile (commits per repo,
repositories created, pull requests...), month by month for the last few
months, drawn in the WakaTime-dashboard look of the other cards: 1-bit dithered
bars, stat tiles with a dithered strip, tiny labels. A pixel Mario climbs the
timeline's vertical line from the oldest month to the newest, lighting each
month up as he passes it, and reaches the flag at the top, where he gets hit:
the classic Super Mario Bros. hop and fall off the bottom. Then he climbs again.

Data comes from the public activity fragment of github.com/<user> (what
visitors see; no token needed).

Usage:
    python scripts/activity.py
"""
import calendar
import html
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from pacman_grid import TZ, Timeline, patterns, pixel_art
from profile_card import PAD, THEMES, USER

ROOT = Path(__file__).resolve().parent.parent
MONTHS = 4                 # most recent months shown
MAX_ROWS = 5               # rows per activity item before "+N more"
WIDTH = 900

# Layout (px).
TILE_H = 52
LINE_X = PAD + 30          # the timeline / Mario's pole
TEXT_X = LINE_X + 22      # month names; item boxes sit here too, clear of the line
ITEM_X = TEXT_X + 18       # "Created ..." summaries, right of their box
ROW_X = ITEM_X + 14        # repo rows under a summary
HEADER_H = 30
SUMMARY_H = 24
ROW_H = 18
BAR_W = 150
MONTH_GAP = 10

# Mario: climbs at CLIMB px/s, pauses at each month and at the flag, then gets
# hit: freezes, hops up HOP px and falls under GRAVITY off the bottom of the card.
CLIMB = 45
PAUSE = 1.2
FLAG_PAUSE = 1.2
HIT_FREEZE = 0.5
HOP, HOP_TIME = 28, 0.35
GRAVITY = 1400             # px/s^2
STEP = 0.18                # s per climbing frame
MARIO_PX = 2
# Mario wears the card's own palette, laid out like the NES original: cap (C)
# and overalls (B) in the orange the months light up in, shirt and sleeves (R)
# in muted grey, hair/eyes/moustache/shoes (H) in ink, skin (S) a faint ink
# tone. Each part: (palette colour, opacity).
MARIO_PARTS = {"C": ("lit", 1.0), "B": ("lit", 1.0), "R": ("grey", 1.0),
               "H": ("ink", 1.0), "S": ("ink", 0.35)}
MARIO_CLIMB = [
    # Small Mario hugging the pole on his right, two climbing frames.
    ["....CCCCC...", "...CCCCCCCCC", "...HHHSSHS..", "..HSHSSSHSSS", "..HSHHSSSHSS",
     "..HHSSSSHHH.", "....SSSSSSS.", "...RRBRRRSS.", "..RRRBRRBSS.", "..RRRBBBBR..",
     "..SSRBBBBB..", "..SSBBBBBB..", "...BBBBBB...", "...BBB.BBB..", "..HHH..HHH..",
     ".HHHH...HHH."],
    ["....CCCCC...", "...CCCCCCCCC", "...HHHSSHS..", "..HSHSSSHSSS", "..HSHHSSSHSS",
     "..HHSSSSHHH.", "....SSSSSSSS", "...RRBRRR.SS", "..RRRBRRB...", ".SRRRBBBBR..",
     ".SSRBBBBBB..", "..SBBBBBBB..", "...BBBBBB...", "..BBB..BBB..", ".HHH...HHH..",
     ".HHHH...HHH."],
]
MARIO_HIT = [  # facing us, arms flung up: the Super Mario Bros. "hit" pose
    ".SS......SS.", ".SS.CCCC.SS.", "..CCCCCCCC..", "..HHSHHSHH..", ".HSSHSSHSSH.",
    ".HSSSSSSSSH.", "..SSHHHHSS..", "...SSSSSS...", "..RRBRRBRR..", ".RRRBBBBRRR.",
    ".RRBBBBBBRR.", "..BBBBBBBB..", "..BBB..BBB..", "..BBB..BBB..", ".HHH....HHH.",
    "HHHH....HHHH"]
FLAG = ["#####", "####.", "###..", "##...", "#...."]

# GitHub's muted grey, for Mario's overalls.
MUTED = {"dark": "#8b949e", "light": "#6e7781"}


# ---------------------------------------------------------------- data

def fetch_month(year: int, month: int) -> list[dict]:
    """The activity items GitHub lists for one month on the profile."""
    last = calendar.monthrange(year, month)[1]
    url = (f"https://github.com/{USER}?action=show&controller=profiles&tab=contributions"
           f"&from={year}-{month:02d}-01&to={year}-{month:02d}-{last}&user_id={USER}")
    req = urllib.request.Request(url, headers={"X-Requested-With": "XMLHttpRequest",
                                               "User-Agent": "profile-readme"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        page = resp.read().decode("utf-8")
    start = page.find("contribution-activity-listing")
    if start < 0:
        raise RuntimeError("activity section not found; the profile page layout may have changed")
    end = page.find("Show more activity", start)
    section = page[start:end if end > 0 else None]

    def text(fragment: str) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()

    items = []
    for block in re.split(r'class="TimelineItem"', section)[1:]:
        head = (re.search(r"<summary[^>]*>\s*<span[^>]*>(.*?)</span>", block, re.S)
                or re.search(r"<h4[^>]*>(.*?)</h4>", block, re.S))
        summary = text(head.group(1)) if head else "Activity"
        summary = re.sub(r"\s+Public$", "", summary)
        rows = []
        for li in re.findall(r"<li\b.*?</li>", block, re.S):
            repo = re.search(r'data-hovercard-type="repository"[^>]*href="/([^"]+)"', li)
            if not repo:
                continue
            count = re.search(r">\s*(\d+) commits?\s*<", li)
            lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', li)
            when = re.search(r"This contribution was made on ([A-Z][a-z]{2} \d+)", li)
            rows.append({"repo": repo.group(1), "count": int(count.group(1)) if count else None,
                         "lang": lang.group(1).strip() if lang else None,
                         "date": when.group(1) if when else None})
        if not rows:  # e.g. a pull request item: the repo is only in the summary
            repo = re.search(r'data-hovercard-type="repository"[^>]*href="/([^"]+)"', block)
            if repo and repo.group(1) not in summary:
                rows.append({"repo": repo.group(1), "count": None, "lang": None, "date": None})
        items.append({"summary": summary, "rows": rows})
    return items


def recent_months(today) -> list[tuple[int, int]]:
    y, m = today.year, today.month
    out = []
    for _ in range(MONTHS):
        out.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    return out


def totals(months: list[dict]) -> list[tuple[str, str]]:
    commits = repos_made = prs = 0
    active = set()
    for mo in months:
        for it in mo["items"]:
            s = it["summary"].lower()
            if "commit" in s:
                commits += sum(r["count"] or 0 for r in it["rows"])
                active |= {r["repo"] for r in it["rows"]}
            elif s.startswith("created") and "repositor" in s:
                n = re.search(r"created (\d+) repositor", s)
                repos_made += int(n.group(1)) if n else 1
            elif "pull request" in s and "first" not in s:
                prs += 1
    return [(str(commits), "Commits"), (str(len(active)), "Active Repos"),
            (str(repos_made), "Repos Created"), (str(prs), "Pull Requests")]


# ---------------------------------------------------------------- drawing

def mario_art(rows: list[str], palette: dict, px: int = MARIO_PX) -> str:
    """Mario's pixel art in the card palette, anchored at its bottom-right corner."""
    h, w = len(rows), len(rows[0])
    rects: dict[str, list[str]] = {}
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in MARIO_PARTS:
                rects.setdefault(ch, []).append(
                    f'<rect x="{(x - w) * px}" y="{(y - h) * px}" width="{px}" height="{px}"/>')
    return "".join(f'<g fill="{palette[MARIO_PARTS[c][0]]}" fill-opacity="{MARIO_PARTS[c][1]}">{"".join(r)}</g>'
                   for c, r in rects.items())


def short(repo: str, owner: str = USER) -> str:
    name = repo.split("/", 1)[1] if repo.startswith(owner + "/") else repo
    return name if len(name) <= 34 else name[:33] + "…"


def render(name: str, theme: dict, months: list[dict], stats: list[tuple[str, str]]) -> str:
    ink, bg, pole, lit = theme["text"], theme["bg"], theme["value"], theme["key"]
    palette = {"ink": ink, "lit": lit, "grey": MUTED[name]}
    right = WIDTH - PAD
    out: list[str] = []
    y = PAD

    # Title and stat tiles.
    out.append(f'<text x="{PAD}" y="{y + 12}" font-size="15" font-weight="bold" fill="{lit}">Contribution Activity</text>'
               f'<text x="{right}" y="{y + 12}" text-anchor="end" font-size="10" fill="{ink}" opacity="0.6">'
               f'last {MONTHS} months</text>')
    y += 26
    tile_w = (right - PAD) / len(stats)
    for i, (value, label) in enumerate(stats):
        x = PAD + i * tile_w
        out.append(f'<rect x="{x:.0f}" y="{y + 4}" width="8" height="{TILE_H - 16}" fill="url(#l1)"/>'
                   f'<text x="{x + 16:.0f}" y="{y + 26}" font-size="24" fill="{ink}">{escape(value)}</text>'
                   f'<text x="{x + 16:.0f}" y="{y + 40}" font-size="11" fill="{ink}" opacity="0.8">{escape(label)}</text>')
    y += TILE_H + 40  # headroom for the flag at the top of the pole

    # Timeline: month headers, activity items, rows with dithered bars.
    nodes = []  # (y of each month's node, month index)
    body: list[str] = []
    for mi, mo in enumerate(months):
        ny = y + HEADER_H // 2
        nodes.append(ny)
        label = f'{calendar.month_name[mo["month"]].upper()} {mo["year"]}'
        lw = len(label) * 7.4
        body.append(f'<g data-month="{mi}"><text class="m{mi}" x="{TEXT_X}" y="{ny + 4}" font-size="11" '
                    f'font-weight="bold" fill="{ink}">{label}</text></g>'
                    f'<rect x="{TEXT_X + lw + 10:.0f}" y="{ny}" width="{right - TEXT_X - lw - 10:.0f}" height="2" fill="url(#l1)"/>')
        y += HEADER_H
        if not mo["items"]:
            body.append(f'<text x="{ITEM_X}" y="{y + 14}" font-size="11" fill="{ink}" opacity="0.6">'
                        f'No activity this month</text>')
            y += SUMMARY_H
        for it in mo["items"]:
            by = y + SUMMARY_H // 2
            body.append(f'<rect x="{TEXT_X}" y="{by - 5}" width="10" height="10" fill="url(#l2)"/>'
                        f'<text x="{ITEM_X}" y="{by + 4}" font-size="12.5" fill="{ink}">{escape(it["summary"])}</text>')
            y += SUMMARY_H
            rows = it["rows"]
            top = max((r["count"] or 0) for r in rows) if rows else 0
            total = sum(r["count"] or 0 for r in rows)
            for r in rows[:MAX_ROWS]:
                ry = y + ROW_H // 2 + 4
                body.append(f'<text x="{ROW_X}" y="{ry}" font-size="11" fill="{pole}">{escape(short(r["repo"]))}</text>')
                if r["count"] is not None:
                    share = r["count"] / total if total else 0
                    fill = ink if share >= 0.4 else "url(#l3)" if share >= 0.2 else "url(#l2)" if share >= 0.1 else "url(#l1)"
                    bw = max(4, round(BAR_W * r["count"] / top / 4) * 4)
                    body.append(f'<text x="{right - BAR_W - 10}" y="{ry}" text-anchor="end" font-size="11" '
                                f'fill="{ink}" opacity="0.75">{r["count"]} commit{"s" * (r["count"] != 1)}</text>'
                                f'<rect x="{right - BAR_W}" y="{ry - 9}" width="{BAR_W}" height="10" fill="url(#l0)"/>'
                                f'<rect x="{right - BAR_W}" y="{ry - 9}" width="{bw}" height="10" fill="{fill}"/>')
                else:
                    meta = " &#183; ".join(escape(v) for v in (r["lang"], r["date"]) if v)
                    if meta:
                        body.append(f'<text x="{right}" y="{ry}" text-anchor="end" font-size="11" '
                                    f'fill="{ink}" opacity="0.75">{meta}</text>')
                y += ROW_H
            if len(rows) > MAX_ROWS:
                body.append(f'<text x="{ROW_X}" y="{y + ROW_H // 2 + 4}" font-size="11" fill="{ink}" '
                            f'opacity="0.6">+{len(rows) - MAX_ROWS} more</text>')
                y += ROW_H
            y += 4
        y += MONTH_GAP
    bottom = y - MONTH_GAP
    height = bottom + PAD

    # Mario's climb: from the bottom of the pole up through each month's node
    # (oldest first), pausing at each, to the flag above the newest.
    pole_top = nodes[0] - 34
    stops = sorted(nodes, reverse=True) + [pole_top + 10]
    t, pos = 0.0, bottom
    keys = [(0.0, bottom)]
    reached = {}
    climbing = []  # (start, end) windows while moving
    for i, sy in enumerate(stops):
        dt = (pos - sy) / CLIMB
        climbing.append((t, t + dt))
        t += dt
        keys.append((t, sy))
        if i < len(nodes):
            reached[len(nodes) - 1 - i] = t  # month index this node belongs to
        t += FLAG_PAUSE if i == len(stops) - 1 else PAUSE
        keys.append((t, sy))
        pos = sy
    flag_at = keys[-2][0]

    # Hit at the flag: freeze, hop up, then fall (accelerating) off the card.
    top = stops[-1]
    hit_at = t
    t += HIT_FREEZE
    keys.append((t, top))
    t += HOP_TIME
    keys.append((t, top - HOP))
    drop = height + 40 - (top - HOP)  # until he's below the card's bottom edge
    fall_time = (2 * drop / GRAVITY) ** 0.5
    for j in range(1, 9):  # sample the parabola so the fall speeds up
        dt = fall_time * j / 8
        keys.append((t + dt, top - HOP + 0.5 * GRAVITY * dt * dt))
    t += fall_time
    dur = t + 0.6  # a beat off-screen before he climbs again
    tl = Timeline(dur)

    # Months light up orange as Mario reaches them, until the loop restarts.
    for mi, at in reached.items():
        old = f'<text class="m{mi}"'
        i = next(j for j, b in enumerate(body) if old in b)
        label_el = re.search(r'<text class="m%d".*?</text>' % mi, body[i]).group(0)
        lit_el = (label_el.replace(f'fill="{ink}"', f'fill="{lit}" opacity="0"')
                  .replace("</text>", tl.show([(0, False), (at, True)]) + "</text>"))
        body[i] = body[i].replace(label_el, label_el + lit_el)

    frames = []
    for j, art in enumerate(MARIO_CLIMB):
        changes = [(0.0, j == 0)]
        for a, b in climbing:
            k = 0
            while a + k * STEP < b:
                changes.append((a + k * STEP, k % 2 == j))
                k += 1
            changes.append((b, j == 0))
        changes.append((hit_at, False))  # the hit pose takes over at the flag
        frames.append(f'<g opacity="0">{tl.show(changes)}{mario_art(art, palette)}</g>')
    # Hit pose, centred on the pole (the climbing sprites hug it from the left).
    frames.append(f'<g opacity="0">{tl.show([(0, False), (hit_at, True), (t, False)])}'
                  f'<g transform="translate({len(MARIO_HIT[0]) * MARIO_PX // 2},0)">'
                  f'{mario_art(MARIO_HIT, palette)}</g></g>')
    motion = tl.motion([k for k, _ in keys], [(LINE_X + 1, v + 16) for _, v in keys])

    flag_y = pole_top
    flag = (f'<g transform="translate({LINE_X + 2},{flag_y})">{pixel_art(FLAG, pole, 3)}</g>'
            f'<g transform="translate({LINE_X + 2},{flag_y})" opacity="0">'
            f'{tl.show([(0, False), (flag_at, True), (dur, True)])}{pixel_art(FLAG, ink, 3)}</g>')

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" '
        f'shape-rendering="crispEdges" font-family="Consolas, \'Courier New\', monospace">',
        f"<defs>{patterns(ink)}</defs>",
        f'<rect width="{WIDTH}" height="{height}" rx="15" fill="{bg}"/>',
        *out,
        f'<rect x="{LINE_X - 1}" y="{pole_top}" width="2" height="{bottom - pole_top}" fill="{pole}"/>',
        f'<rect x="{LINE_X - 3}" y="{pole_top - 4}" width="6" height="6" fill="{pole}"/>',
        flag,
        *(f'<rect x="{LINE_X - 4}" y="{ny - 4}" width="8" height="8" fill="{ink}"/>' for ny in nodes),
        *body,
        f"<g>{motion}{''.join(frames)}</g>",
        "</svg>",
    ]
    return "\n".join(svg) + "\n"


def main() -> None:
    today = datetime.now(TZ).date()
    try:
        months = [{"year": y, "month": m, "items": fetch_month(y, m)} for y, m in recent_months(today)]
    except Exception as err:  # keep yesterday's card rather than fail the workflow
        print("activity fetch failed, leaving the cards as they are:", err)
        sys.exit(0)
    for mo in months:
        print(f'{mo["year"]}-{mo["month"]:02d}:', "; ".join(i["summary"] for i in mo["items"]) or "no activity")
    stats = totals(months)
    print("tiles:", stats)
    for name, theme in THEMES.items():
        path = ROOT / f"activity_{name}.svg"
        path.write_text(render(name, theme, months, stats), encoding="utf-8")
        print("wrote", path.name, f"({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
