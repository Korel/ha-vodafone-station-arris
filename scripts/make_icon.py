"""Render brand/icon.png (256) and brand/icon@2x.png (512).

    uv run --with pillow python -I scripts/make_icon.py

Original artwork (router tower + Wi-Fi arcs); deliberately not Vodafone's logo.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "custom_components" / "vodafone_station_arris" / "brand"
S = 2048  # draw at 4x the largest output, then downsample for anti-aliasing

TILE = "#1f2329"
FRONT = "#eceff3"
SIDE = "#aeb5bf"
FOOT = "#7d8590"
ARC = "#ff5a4e"
LED = "#3ddc84"


def p(*values: float) -> list[float]:
    return [v * S for v in values]


def render() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(p(0, 0, 1, 1), radius=0.22 * S, fill=TILE)

    # Slim upright router: side face, front face, foot, status LED.
    d.polygon([tuple(p(0.47, 0.24)), tuple(p(0.53, 0.20)), tuple(p(0.53, 0.78)), tuple(p(0.47, 0.82))], fill=SIDE)
    d.rounded_rectangle(p(0.27, 0.24, 0.48, 0.82), radius=0.035 * S, fill=FRONT)
    d.rounded_rectangle(p(0.30, 0.82, 0.50, 0.86), radius=0.02 * S, fill=FOOT)
    d.ellipse(p(0.355, 0.735, 0.395, 0.775), fill=LED)

    # Wi-Fi arcs radiating up-right from the router's top corner.
    cx, cy = 0.60, 0.44
    for r in (0.11, 0.19, 0.27):
        d.arc(p(cx - r, cy - r, cx + r, cy + r), start=-80, end=-10, fill=ARC, width=int(0.045 * S))
    d.ellipse(p(cx - 0.03, cy - 0.03, cx + 0.03, cy + 0.03), fill=ARC)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img = render()
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        img.resize((size, size), Image.Resampling.LANCZOS).save(OUT / name, optimize=True)
        print(OUT / name)


if __name__ == "__main__":
    main()
