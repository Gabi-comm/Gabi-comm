"""Convert assets/portrait_source.jpg into an ASCII portrait (assets/portrait.txt).

The source is a screenshot of ASCII art on a 160x80 character grid. We measure
the ink in each grid cell, merge `--scale` x `--scale` blocks of cells, and
re-map that brightness onto a glyph ramp, so the result keeps the original's
shape at a size that fits the profile card.

Usage: python scripts/make_ascii.py [--scale 2]
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "portrait_source.jpg"
OUT = ROOT / "assets" / "portrait.txt"

# Grid measured from the source (Fourier fit of row/column ink profiles).
ORIGIN_X, ORIGIN_Y = 29.0, 23.0
CELL_W, CELL_H = 12.425, 23.795
COLS, ROWS = 160, 80

# Sparse -> dense. The card background is dark, so bright cells get dense glyphs.
RAMP = " .`:-=+*#%@"


def cell_ink(img):
    import numpy as np

    ink = np.zeros((ROWS, COLS))
    for r in range(ROWS):
        y0, y1 = round(ORIGIN_Y + r * CELL_H), round(ORIGIN_Y + (r + 1) * CELL_H)
        for c in range(COLS):
            x0, x1 = round(ORIGIN_X + c * CELL_W), round(ORIGIN_X + (c + 1) * CELL_W)
            ink[r, c] = img[y0:y1, x0:x1].mean()
    return ink


def convert(scale: int, gamma: float) -> list[str]:
    # Imported here so profile_card.py can reuse RAMP without numpy/Pillow installed.
    import numpy as np
    from PIL import Image

    img = np.asarray(Image.open(SRC).convert("L"), dtype=float)
    ink = cell_ink(img)
    h, w = ROWS // scale, COLS // scale
    ink = ink[: h * scale, : w * scale].reshape(h, scale, w, scale).mean(axis=(1, 3))
    lo, hi = np.percentile(ink, 1), np.percentile(ink, 99.5)
    norm = np.clip((ink - lo) / (hi - lo), 0, 1) ** gamma
    idx = np.rint(norm * (len(RAMP) - 1)).astype(int)
    return ["".join(RAMP[i] for i in row) for row in idx]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=2, help="source cells merged per output cell")
    ap.add_argument("--gamma", type=float, default=1.0)
    args = ap.parse_args()
    lines = convert(args.scale, args.gamma)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
