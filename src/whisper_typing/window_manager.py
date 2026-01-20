"""Window management utilities for whisper-typing."""

import pygetwindow as gw


class WindowManager:
    """Manages window focus and retrieval operations."""

    def __init__(self) -> None:
        """Initialize the WindowManager."""

    def get_active_window(self) -> gw.Window | None:
        """Get the currently active window object."""
        try:
            # Returns the active window object
            window = gw.getActiveWindow()
            if window:
                return window
        except Exception:  # noqa: BLE001, S110
            pass
        return None

    def focus_window(self, window: gw.Window) -> bool:
        """Bring the specified window object to the foreground."""
        if not window:
            return False

        try:
            if window.isActive:
                return True

            # If minimized, restore it
            if window.isMinimized:
                window.restore()

            # Activate brings it to foreground
            window.activate()
        except Exception:  # noqa: BLE001
            return False
        else:
            return True
