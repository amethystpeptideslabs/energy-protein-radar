"""Generates the app icons: an original radar glyph (no brand logos). Run: python scripts/make_icons.py"""
from pathlib import Path

from PIL import Image, ImageDraw

BG = (18, 24, 31)          # night aisle
RING = (238, 242, 245)     # label white
SWEEP = (246, 199, 68)     # sale-tag yellow
BLIP = (255, 90, 78)       # clearance red
OUT = Path(__file__).resolve().parent.parent / "icons"


def draw(size: int, safe: float = 1.0) -> Image.Image:
    s = size * 4  # supersample
    img = Image.new("RGB", (s, s), BG)
    d = ImageDraw.Draw(img)
    c = s / 2
    r_max = s * 0.40 * safe
    w = max(2, int(s * 0.022))
    # sweep wedge
    d.pieslice([c - r_max, c - r_max, c + r_max, c + r_max], start=-90, end=-30, fill=SWEEP)
    for k in (1.0, 0.68, 0.36):
        r = r_max * k
        d.ellipse([c - r, c - r, c + r, c + r], outline=RING, width=w)
    d.line([c, c - r_max, c, c], fill=RING, width=w)
    # price-tag blip (rotated square with a hole) inside the sweep
    bx, by, br = c + r_max * 0.38, c - r_max * 0.55, r_max * 0.15
    d.polygon([(bx, by - br), (bx + br, by), (bx, by + br), (bx - br, by)], fill=BLIP)
    d.ellipse([bx - br * 0.28, by - br * 0.28, bx + br * 0.28, by + br * 0.28], fill=BG)
    d.ellipse([c - w * 1.6, c - w * 1.6, c + w * 1.6, c + w * 1.6], fill=RING)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    draw(192).save(OUT / "icon-192.png", optimize=True)
    draw(512).save(OUT / "icon-512.png", optimize=True)
    draw(512, safe=0.78).save(OUT / "icon-maskable-512.png", optimize=True)
    draw(180, safe=0.9).save(OUT / "apple-touch-icon.png", optimize=True)
    draw(32).save(OUT / "favicon-32.png", optimize=True)
    print("icons written to", OUT)
