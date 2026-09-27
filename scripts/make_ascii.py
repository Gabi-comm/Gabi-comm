
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "me.jpg"
MASK = ROOT / "assets" / "me_mask.png"
OUT = ROOT / "assets" / "portrait.txt"


RAMP = " `.:~;=+?|)]oX#%&@"
DENSITY = [0, .06, .10, .17, .24, .27, .30, .33, .35, .37, .40, .47, .53, .60, .67, .72, .81, 1.0]


CELL_ASPECT = 0.52


BOX = (290, 190, 690, 590)


def load_mask(img):
    import cv2

    if MASK.exists():
        return cv2.imread(str(MASK), cv2.IMREAD_GRAYSCALE)
    from PIL import Image
    from rembg import new_session, remove

    pil = Image.open(SRC).convert("RGB")
    mask = remove(pil, session=new_session("u2net_human_seg"), only_mask=True)
    mask.save(MASK)
    return cv2.imread(str(MASK), cv2.IMREAD_GRAYSCALE)


def convert(cols: int, box=BOX, gamma: float = 0.8, clahe: float = 2.0, sharpen: float = 0.3) -> list[str]:
    import cv2
    import numpy as np

    img = cv2.imread(str(SRC))
    mask = load_mask(img)
    x0, y0, x1, y1 = box
    img, mask = img[y0:y1, x0:x1], mask[y0:y1, x0:x1]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=clahe, tileGridSize=(3, 3)).apply(gray)
    blur = cv2.GaussianBlur(gray, (0, 0), 3)
    gray = cv2.addWeighted(gray, 1 + sharpen, blur, -sharpen, 0)  # unsharp mask

    rows = round(cols * gray.shape[0] / gray.shape[1] * CELL_ASPECT)
    small = cv2.resize(gray, (cols, rows), interpolation=cv2.INTER_AREA).astype(float)
    alpha = cv2.resize(mask, (cols, rows), interpolation=cv2.INTER_AREA) / 255.0

    subject = alpha > 0.5
    lo, hi = np.percentile(small[subject], 1), np.percentile(small[subject], 99.5)
    norm = np.clip((small - lo) / (hi - lo), 0, 1) ** gamma
    density = np.array(DENSITY[1:])
    target = density[0] + norm * (density[-1] - density[0])
    idx = 1 + np.abs(target[..., None] - density).argmin(axis=-1)
    idx[~subject] = 0
    lines = ["".join(RAMP[i] for i in row).rstrip() for row in idx]
    while lines and not lines[-1]:
        lines.pop()
    return lines


def preview(lines: list[str], path: Path) -> None:
    """Render the ASCII the way the dark card shows it, for eyeballing."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype("consola.ttf", 12)
    cw, lh = 6.6, 12.7
    w = int(max(map(len, lines)) * cw) + 20
    im = Image.new("RGB", (w, int(len(lines) * lh) + 20), "#161b22")
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        d.text((10, 10 + i * lh), line, font=font, fill="#c9d1d9")
    im.save(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cols", type=int, default=80)
    ap.add_argument("--box", type=int, nargs=4, default=BOX, metavar=("X0", "Y0", "X1", "Y1"))
    ap.add_argument("--gamma", type=float, default=0.8, help="<1 lifts shadows (the face)")
    ap.add_argument("--clahe", type=float, default=2.0, help="local contrast clip limit")
    ap.add_argument("--sharpen", type=float, default=0.3)
    ap.add_argument("--preview", type=Path, help="also render a PNG preview here")
    args = ap.parse_args()
    lines = convert(args.cols, tuple(args.box), args.gamma, args.clahe, args.sharpen)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(lines)} rows x {max(map(len, lines))} cols -> {OUT.relative_to(ROOT)}")
    if args.preview:
        preview(lines, args.preview)


if __name__ == "__main__":
    main()
