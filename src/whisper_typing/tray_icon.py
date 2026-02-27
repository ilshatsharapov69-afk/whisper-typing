"""System tray icon for whisper-typing."""

import threading
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFont
from pystray import Icon, Menu, MenuItem

if TYPE_CHECKING:
    from collections.abc import Callable


def _create_icon_image(state: str = "ready") -> Image.Image:
    """Create a tray icon image based on current state.

    Args:
        state: One of 'ready', 'recording', 'processing'.

    Returns:
        A PIL Image for the tray icon.

    """
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state == "recording":
        # Red circle = recording
        draw.ellipse([4, 4, 60, 60], fill=(220, 40, 40, 255))
        # White mic shape
        draw.ellipse([22, 12, 42, 38], fill=(255, 255, 255, 255))
        draw.rectangle([26, 36, 38, 48], fill=(255, 255, 255, 255))
        draw.rectangle([20, 46, 44, 50], fill=(255, 255, 255, 255))
    elif state == "processing":
        # Yellow circle = processing
        draw.ellipse([4, 4, 60, 60], fill=(240, 180, 20, 255))
        # Dark mic
        draw.ellipse([22, 12, 42, 38], fill=(60, 60, 60, 255))
        draw.rectangle([26, 36, 38, 48], fill=(60, 60, 60, 255))
        draw.rectangle([20, 46, 44, 50], fill=(60, 60, 60, 255))
    else:
        # Green circle = ready
        draw.ellipse([4, 4, 60, 60], fill=(50, 160, 80, 255))
        # White mic
        draw.ellipse([22, 12, 42, 38], fill=(255, 255, 255, 255))
        draw.rectangle([26, 36, 38, 48], fill=(255, 255, 255, 255))
        draw.rectangle([20, 46, 44, 50], fill=(255, 255, 255, 255))

    return img


class TrayManager:
    """Manages the system tray icon for whisper-typing."""

    def __init__(self, on_quit: "Callable[[], None] | None" = None) -> None:
        """Initialize the TrayManager.

        Args:
            on_quit: Callback when user clicks Quit in tray menu.

        """
        self._on_quit = on_quit
        self._icon: Icon | None = None
        self._thread: threading.Thread | None = None
        self._current_state = "ready"

    def start(self) -> None:
        """Start the tray icon in a background thread."""
        menu = Menu(
            MenuItem("Whisper Typing", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit_clicked),
        )
        self._icon = Icon(
            "Whisper Typing",
            icon=_create_icon_image("ready"),
            title="Whisper Typing - Ready",
            menu=menu,
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

        if "Recording" in status:
            new_state = "recording"
            tooltip = "Whisper Typing - Recording..."
        elif "Processing" in status or "Loading" in status or "Typing" in status:
            new_state = "processing"
            tooltip = "Whisper Typing - Processing..."
        else:
            new_state = "ready"
            tooltip = "Whisper Typing - Ready"

        if new_state != self._current_state:
            self._current_state = new_state
            self._icon.icon = _create_icon_image(new_state)
            self._icon.title = tooltip

    def stop(self) -> None:
        """Stop and remove the tray icon."""
        if self._icon:
            self._icon.stop()

    def _quit_clicked(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        """Handle quit menu item click."""
        if self._on_quit:
            self._on_quit()
        self.stop()
