"""
Draw Racecraft's application icon.

The output, `src/racecraft/app/racecraft.ico`, is committed, so the app never
needs Pillow at runtime; run this only to change the design.

The mark is the interface's own: the orange of the RACECRAFT wordmark on the
dark of its panels, a heavy R with a speed line through the foot of it. It is
drawn at 1024 px and scaled down per size, because an icon drawn at 16 px
directly is a smudge and one scaled from a large master is merely small.

    python scripts/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "src" / "racecraft" / "app" / "racecraft.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
MASTER = 1024

GROUND = (12, 16, 21, 255)       # --ground
PANEL = (26, 34, 43, 255)        # --panel-2
SIGNAL = (255, 122, 51, 255)     # --signal
FONTS = ["C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf"]


def master() -> Image.Image:
    image = Image.new("RGBA", (MASTER, MASTER), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius = int(MASTER * 0.2)
    draw.rounded_rectangle([0, 0, MASTER - 1, MASTER - 1], radius=radius, fill=GROUND)
    inset = int(MASTER * 0.035)
    draw.rounded_rectangle([inset, inset, MASTER - 1 - inset, MASTER - 1 - inset],
                           radius=radius - inset, outline=PANEL, width=int(MASTER * 0.02))

    font = next((ImageFont.truetype(path, int(MASTER * 0.72)) for path in FONTS if Path(path).exists()),
                None) or ImageFont.load_default()
    box = draw.textbbox((0, 0), "R", font=font)
    width, height = box[2] - box[0], box[3] - box[1]
    x = (MASTER - width) / 2 - box[0] - MASTER * 0.02
    y = (MASTER - height) / 2 - box[1] - MASTER * 0.03
    draw.text((x, y), "R", font=font, fill=SIGNAL)

    # A speed line under the letter, left to right, so the mark reads as motion
    # rather than as a monogram.
    stripe_y = int(MASTER * 0.80)
    thickness = int(MASTER * 0.055)
    draw.rounded_rectangle([int(MASTER * 0.16), stripe_y, int(MASTER * 0.84), stripe_y + thickness],
                           radius=thickness // 2, fill=SIGNAL)
    return image


def main() -> None:
    big = master()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    big.save(OUT, format="ICO", sizes=[(size, size) for size in SIZES])
    big.resize((256, 256), Image.LANCZOS).save(OUT.with_suffix(".png"))
    print(f"wrote {OUT} ({', '.join(str(size) for size in SIZES)} px)")


if __name__ == "__main__":
    main()
