"""Generate the app icon (a microphone) used by the shortcut and the exe build.

    .venv\\Scripts\\python.exe -X utf8 tools\\make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisper_typing.tray_icon import draw_app_icon  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "src" / "whisper_typing" / "assets" / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> None:
    """Write a multi-resolution .ico from the same drawing the tray uses."""
    icon = draw_app_icon()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"{OUT}  ({OUT.stat().st_size // 1024} КБ, размеры: {SIZES})")


if __name__ == "__main__":
    main()
