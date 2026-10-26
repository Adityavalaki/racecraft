"""
Generate the MSIX visual assets from the app icon.

MSIX needs square logos at a few sizes and a wide tile. Run once; the files
land in packaging/msix/Assets and are referenced by AppxManifest.xml.

    python packaging/make_msix_assets.py
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "src" / "racecraft" / "app" / "racecraft.png"
OUT = HERE / "msix" / "Assets"

SQUARES = {
    "Square44x44Logo.png": 44,
    "Square71x71Logo.png": 71,
    "Square150x150Logo.png": 150,
    "Square310x310Logo.png": 310,
    "StoreLogo.png": 50,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = Image.open(SOURCE).convert("RGBA")
    for name, size in SQUARES.items():
        icon.resize((size, size), Image.LANCZOS).save(OUT / name)
    # The wide tile: the square centred on a transparent 310x150 canvas.
    wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
    badge = icon.resize((140, 140), Image.LANCZOS)
    wide.paste(badge, ((310 - 140) // 2, (150 - 140) // 2), badge)
    wide.save(OUT / "Wide310x150Logo.png")
    print(f"wrote {len(SQUARES) + 1} assets to {OUT}")


if __name__ == "__main__":
    main()
