"""Tests for window_manager module."""

from unittest.mock import MagicMock, patch

from whisper_typing.window_manager import WindowManager


def test_get_active_window() -> None:
    """Test retrieving the active window."""
    with patch("pygetwindow.getActiveWindow") as mock_get_active:
        mock_window = MagicMock()
        mock_get_active.return_value = mock_window
        wm = WindowManager()
        assert wm.get_active_window() == mock_window


def test_focus_window_success() -> None:
    """Test successfully focusing a window."""
    wm = WindowManager()
    mock_window = MagicMock()
    mock_window.isActive = False
    mock_window.isMinimized = False

    # Simulate successful activation
    mock_window.activate.return_value = None

    assert wm.focus_window(mock_window) is True
    mock_window.activate.assert_called_once()


def test_focus_window_failure() -> None:
    """Test failure when focusing a window."""
    wm = WindowManager()
    mock_window = MagicMock()
    mock_window.isActive = False

    # Simulate exception during activation
    mock_window.activate.side_effect = Exception("Focus error")

    assert wm.focus_window(mock_window) is False


def test_get_active_window_exception() -> None:
    """Test get_active_window when exception occurs."""
    with patch("pygetwindow.getActiveWindow") as mock_get_active:
        mock_get_active.side_effect = Exception("Window error")
        wm = WindowManager()
        assert wm.get_active_window() is None


def test_get_active_window_none() -> None:
    """Test get_active_window when no window is active."""
    with patch("pygetwindow.getActiveWindow") as mock_get_active:
        mock_get_active.return_value = None
        wm = WindowManager()
        assert wm.get_active_window() is None


def test_focus_window_none() -> None:
    """Test focus_window with None window."""
    wm = WindowManager()
    assert wm.focus_window(None) is False


def test_focus_window_already_active() -> None:
    """Test focus_window when window is already active."""
    wm = WindowManager()
    mock_window = MagicMock()
    mock_window.isActive = True

    assert wm.focus_window(mock_window) is True
    mock_window.activate.assert_not_called()


def test_focus_window_minimized() -> None:
    """Test focus_window when window is minimized."""
    wm = WindowManager()
    mock_window = MagicMock()
    mock_window.isActive = False
    mock_window.isMinimized = True

    assert wm.focus_window(mock_window) is True
    mock_window.restore.assert_called_once()
    mock_window.activate.assert_called_once()
