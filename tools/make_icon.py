"""Generate the app icon (a microphone) used by the shortcut and the exe build.

    .venv\\Scripts\\python.exe -X utf8 tools\\make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "src" / "whisper_typing" / "assets" / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BASE = 256


def draw_icon() -> Image.Image:
    """Draw a mic on a rounded blue tile at 256 px."""
    image = Image.new("RGBA", (BASE, BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, BASE - 8, BASE - 8), radius=56, fill=(30, 94, 238, 255))
    draw.rounded_rectangle((10, 10, BASE - 10, 128), radius=54, fill=(58, 124, 255, 255))

    white = (255, 255, 255, 255)
    # capsule
    draw.rounded_rectangle((100, 52, 156, 150), radius=28, fill=white)
    # cradle
    draw.arc((76, 96, 180, 186), start=0, end=180, fill=white, width=14)
    # stem + base
    draw.rectangle((121, 178, 135, 200), fill=white)
    draw.rounded_rectangle((92, 198, 164, 212), radius=7, fill=white)
    return image


def main() -> None:
    """Write a multi-resolution .ico."""
    icon = draw_icon()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"{OUT}  ({OUT.stat().st_size // 1024} КБ, размеры: {SIZES})")


if __name__ == "__main__":
    main()
