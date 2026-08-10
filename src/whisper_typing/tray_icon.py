"""System tray icon for whisper-typing."""

import threading
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem


if TYPE_CHECKING:
    from collections.abc import Callable


ICON_BASE = 256
STATE_TILES = {
    "ready": ((30, 94, 238, 255), (58, 124, 255, 255)),
    "recording": ((196, 32, 46, 255), (232, 62, 74, 255)),
    "processing": ((196, 128, 8, 255), (240, 172, 24, 255)),
}


def draw_app_icon(size: int = ICON_BASE, state: str = "ready") -> Image.Image:
    """Draw the microphone mark used by the tray, the shortcut and the exe.

    One drawing for every surface, so the tray icon and the Desktop shortcut
    are visibly the same app; only the tile colour reports the state.
    """
    deep, light = STATE_TILES.get(state, STATE_TILES["ready"])
    image = Image.new("RGBA", (ICON_BASE, ICON_BASE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, ICON_BASE - 8, ICON_BASE - 8), radius=56, fill=deep)
    draw.rounded_rectangle((10, 10, ICON_BASE - 10, 128), radius=54, fill=light)

    white = (255, 255, 255, 255)
    draw.rounded_rectangle((100, 52, 156, 150), radius=28, fill=white)
    draw.arc((76, 96, 180, 186), start=0, end=180, fill=white, width=14)
    draw.rectangle((121, 178, 135, 200), fill=white)
    draw.rounded_rectangle((92, 198, 164, 212), radius=7, fill=white)

    if size != ICON_BASE:
        image = image.resize((size, size), Image.Resampling.LANCZOS)
    return image


def _create_icon_image(state: str = "ready") -> Image.Image:
    """Create a tray icon image for the current state."""
    return draw_app_icon(64, state)


class TrayManager:
    """Manages the system tray icon for whisper-typing."""

    def __init__(
        self,
        on_quit: "Callable[[], None] | None" = None,
        on_pause: "Callable[[], None] | None" = None,
        on_dashboard: "Callable[[str], None] | None" = None,
    ) -> None:
        """Initialize the TrayManager.

        Args:
            on_quit: Callback when the user clicks Выход.
            on_pause: Callback when the user clicks Пауза.
            on_dashboard: Callback(tab) when the user picks a panel page.

        """
        self._on_quit = on_quit
        self._on_pause = on_pause
        self._on_dashboard = on_dashboard
        self._icon: Icon | None = None
        self._thread: threading.Thread | None = None
        self._current_state = "ready"

    def _build_menu(self) -> Menu:
        """Build the context menu.

        Every setting lives in the panel now. The tray keeps only what a menu
        does better: opening the right page, pausing, and quitting. The old
        Visualizer submenus were a second place to change the same values.
        """
        return Menu(
            MenuItem("Панель", self._open("loader"), default=True),
            Menu.SEPARATOR,
            MenuItem("Загрузка", self._open("loader")),
            MenuItem("Стиль и цвет", self._open("eq")),
            MenuItem("История", self._open("history")),
            MenuItem("Настройки", self._open("settings")),
            Menu.SEPARATOR,
            MenuItem(
                "Пауза",
                self._pause_clicked,
                checked=lambda _: self._current_state == "paused",
            ),
            MenuItem("Выход", self._quit_clicked),
        )

    def _open(self, tab: str) -> "Callable[[Any, Any], None]":
        """Return a menu callback that opens the panel on one tab."""

        def clicked(icon: Any, item: Any) -> None:  # noqa: ANN401, ARG001
            if self._on_dashboard:
                self._on_dashboard(tab)

        return clicked

    def start(self) -> None:
        """Start the tray icon in a background thread."""
        self._icon = Icon(
            "Whisper Typing",
            icon=_create_icon_image("ready"),
            title="Whisper Typing - Ready",
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def update_state(self, status: str) -> None:
        """Update tray icon based on app status string.

        Args:
            status: Status string from the controller.

        """
        if not self._icon:
            return

        if "Paused" in status:
            new_state = "paused"
            tooltip = "Whisper Typing - Paused"
        elif "Recording" in status:
            new_state = "recording"
            tooltip = "Whisper Typing - Recording..."
        elif "Processing" in status or "Loading" in status or "Typing" in status or "Formatting" in status:
            new_state = "processing"
            tooltip = f"Whisper Typing - {status}"
        else:
            new_state = "ready"
            tooltip = "Whisper Typing - Ready"

        icon_state = "ready" if new_state == "paused" else new_state
        if new_state != self._current_state:
            self._current_state = new_state
            self._icon.icon = _create_icon_image(icon_state)
        self._icon.title = tooltip
        self._icon.menu = self._build_menu()

    def stop(self) -> None:
        """Stop and remove the tray icon."""
        if self._icon:
            self._icon.stop()

    def _pause_clicked(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        if self._on_pause:
            self._on_pause()

    def _quit_clicked(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        if self._on_quit:
            self._on_quit()
        self.stop()
