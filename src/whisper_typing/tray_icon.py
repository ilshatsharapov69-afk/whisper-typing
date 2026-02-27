"""System tray icon for whisper-typing."""

import threading
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

from whisper_typing.overlay import GRADIENTS, STYLES

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

    colors = {
        "recording": (220, 40, 40, 255),
        "processing": (240, 180, 20, 255),
    }
    bg = colors.get(state, (50, 160, 80, 255))
    mic = (255, 255, 255, 255) if state != "processing" else (60, 60, 60, 255)

    draw.ellipse([4, 4, 60, 60], fill=bg)
    draw.ellipse([22, 12, 42, 38], fill=mic)
    draw.rectangle([26, 36, 38, 48], fill=mic)
    draw.rectangle([20, 46, 44, 50], fill=mic)

    return img


class TrayManager:
    """Manages the system tray icon for whisper-typing."""

    def __init__(
        self,
        on_quit: "Callable[[], None] | None" = None,
        config: dict[str, Any] | None = None,
        on_config_toggle: "Callable[[str, bool], None] | None" = None,
        on_pause: "Callable[[], None] | None" = None,
    ) -> None:
        """Initialize the TrayManager.

        Args:
            on_quit: Callback when user clicks Quit in tray menu.
            config: Reference to the app config dict (for reading toggle states).
            on_config_toggle: Callback(key, new_value) when a config toggle is flipped.
            on_pause: Callback when user clicks Pause/Resume.

        """
        self._on_quit = on_quit
        self._config = config or {}
        self._on_config_toggle = on_config_toggle
        self._on_pause = on_pause
        self._icon: Icon | None = None
        self._thread: threading.Thread | None = None
        self._current_state = "ready"

    def _build_menu(self) -> Menu:
        """Build the context menu with current toggle states."""
        cfg = self._config

        # Build visualizer style submenu
        style_labels = {
            "bars": "Bars (Classic EQ)",
            "mirror": "Mirror (Symmetric)",
            "wave": "Wave (Smooth)",
            "circles": "Circles (Pulsing)",
            "blocks": "Blocks (LED Matrix)",
            "line": "Line (Minimal)",
        }
        style_items = []
        for s in STYLES:
            label = style_labels.get(s, s)
            style_items.append(
                MenuItem(
                    label,
                    self._make_style_callback(s),
                    checked=self._make_style_checker(s),
                )
            )

        # Build gradient submenu
        gradient_labels = {
            "green_red": "Green → Red",
            "cyan_purple": "Cyan → Purple",
            "blue_white": "Blue → White",
            "fire": "Fire",
            "neon": "Neon",
        }
        gradient_items = []
        for g in GRADIENTS:
            label = gradient_labels.get(g, g)
            gradient_items.append(
                MenuItem(
                    label,
                    self._make_gradient_callback(g),
                    checked=self._make_gradient_checker(g),
                )
            )

        return Menu(
            MenuItem("Whisper Typing", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                "AI Format",
                self._toggle_auto_format,
                checked=lambda _: cfg.get("auto_format", False),
            ),
            MenuItem(
                "Auto-Type",
                self._toggle_auto_type,
                checked=lambda _: cfg.get("auto_type", False),
            ),
            MenuItem(
                "Pause Media",
                self._toggle_pause_media,
                checked=lambda _: cfg.get("pause_media", True),
            ),
            MenuItem(
                "Hold-to-Record",
                self._toggle_hold_mode,
                checked=lambda _: cfg.get("record_mode") == "hold",
            ),
            Menu.SEPARATOR,
            MenuItem("Visualizer Style", Menu(*style_items)),
            MenuItem("Visualizer Color", Menu(*gradient_items)),
            Menu.SEPARATOR,
            MenuItem(
                "Pause",
                self._pause_clicked,
                checked=lambda _: self._current_state == "paused",
            ),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit_clicked),
        )

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

    def _toggle_auto_format(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        new_val = not self._config.get("auto_format", False)
        self._config["auto_format"] = new_val
        if self._on_config_toggle:
            self._on_config_toggle("auto_format", new_val)
        self._icon.menu = self._build_menu()

    def _toggle_auto_type(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        new_val = not self._config.get("auto_type", False)
        self._config["auto_type"] = new_val
        if self._on_config_toggle:
            self._on_config_toggle("auto_type", new_val)
        self._icon.menu = self._build_menu()

    def _toggle_pause_media(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        new_val = not self._config.get("pause_media", True)
        self._config["pause_media"] = new_val
        if self._on_config_toggle:
            self._on_config_toggle("pause_media", new_val)
        self._icon.menu = self._build_menu()

    def _toggle_hold_mode(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        new_val = "toggle" if self._config.get("record_mode") == "hold" else "hold"
        self._config["record_mode"] = new_val
        if self._on_config_toggle:
            self._on_config_toggle("record_mode", new_val)
        self._icon.menu = self._build_menu()

    def _make_style_callback(self, style: str) -> "Callable[[Any, Any], None]":
        def cb(icon: Any, item: Any) -> None:  # noqa: ANN401
            self._config["visualizer_style"] = style
            if self._on_config_toggle:
                self._on_config_toggle("visualizer_style", style)
            self._icon.menu = self._build_menu()
        return cb

    def _make_style_checker(self, style: str) -> "Callable[[Any], bool]":
        return lambda _: self._config.get("visualizer_style", "bars") == style

    def _make_gradient_callback(self, gradient: str) -> "Callable[[Any, Any], None]":
        def cb(icon: Any, item: Any) -> None:  # noqa: ANN401
            self._config["visualizer_gradient"] = gradient
            if self._on_config_toggle:
                self._on_config_toggle("visualizer_gradient", gradient)
            self._icon.menu = self._build_menu()
        return cb

    def _make_gradient_checker(self, gradient: str) -> "Callable[[Any], bool]":
        return lambda _: self._config.get("visualizer_gradient", "green_red") == gradient

    def _pause_clicked(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        if self._on_pause:
            self._on_pause()

    def _quit_clicked(self, icon: Any, item: Any) -> None:  # noqa: ANN401
        if self._on_quit:
            self._on_quit()
        self.stop()
