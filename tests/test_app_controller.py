"""Tests for app_controller module."""

import threading
from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest

from whisper_typing.app_controller import DEFAULT_CONFIG, WhisperAppController


@pytest.fixture
def mock_dependencies() -> Generator[dict[str, Any]]:
    """Mock all external dependencies for the controller."""
    with (
        patch("whisper_typing.app_controller.AudioRecorder") as mock_recorder,
        patch("whisper_typing.app_controller.Transcriber") as mock_transcriber,
        patch("whisper_typing.app_controller.Typer") as mock_typer,
        patch("whisper_typing.app_controller.AIImprover") as mock_improver,
        patch("whisper_typing.app_controller.WindowManager") as mock_window_manager,
        patch("pynput.keyboard.GlobalHotKeys") as mock_hotkeys,
        patch("whisper_typing.app_controller.sd") as mock_sd,
    ):
        yield {
            "recorder": mock_recorder,
            "transcriber": mock_transcriber,
            "typer": mock_typer,
            "improver": mock_improver,
            "window_manager": mock_window_manager,
            "hotkeys": mock_hotkeys,
            "sd": mock_sd,
        }

    mock_sd.query_devices.return_value = []


def test_initialization(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test controller initialization."""
    controller = WhisperAppController()
    assert controller.config == {}

    # Components should be None until initialized
    assert controller.recorder is None
    assert controller.transcriber is None


def test_initialize_components(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test initializing components."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    success = controller.initialize_components()

    assert success is True
    assert controller.recorder is not None
    assert controller.transcriber is not None
    assert controller.typer is not None
    assert controller.improver is not None
    assert controller.window_manager is not None


def test_start_listener(mock_dependencies: dict[str, Any]) -> None:
    """Test starting the global hotkey listener."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    controller.initialize_components()

    controller.start_listener()

    expected_hotkeys = mock_dependencies["hotkeys"]
    expected_hotkeys.assert_called_once()

    # Check hotkey map creation (simplified check)
    args, _ = expected_hotkeys.call_args
    hotkey_map = args[0]
    assert controller.config["hotkey"] in hotkey_map
    assert controller.config["type_hotkey"] in hotkey_map


def test_on_record_toggle_start(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test starting recording."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    controller.initialize_components()
    mock_wm = controller.window_manager
    mock_recorder = controller.recorder
    mock_recorder.recording = False

    # Simulate window handle
    mock_wm.get_active_window.return_value = "WindowHandle"

    # Trigger toggle (Start)
    controller.on_record_toggle()

    assert controller.window_manager is not None
    mock_wm.get_active_window.assert_called()

    assert controller.target_window_handle == "WindowHandle"
    mock_recorder.start.assert_called_once()


def test_on_record_toggle_stop(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test stopping recording."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    controller.initialize_components()
    mock_recorder = controller.recorder
    # Set to recording state
    mock_recorder.recording = True
    controller.stop_live_transcribe = threading.Event()

    # Trigger toggle (Stop)
    controller.on_record_toggle()

    mock_recorder.stop.assert_called_once()
    assert controller.stop_live_transcribe.is_set()


def test_on_type_confirm(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test typing confirmation."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    controller.initialize_components()

    controller.pending_text = "Hello World"

    # Mock threading to run synchronously for test or just assert it was started
    # Here we simulate the logic inside the thread or check if thread started
    with patch("threading.Thread") as mock_thread:
        controller.on_type_confirm()
        mock_thread.assert_called_once()
        # You could introspect the target of the thread if needed,
        # but verifying the thread creation is usually sufficient for this level.


def test_on_improve_text(mock_dependencies: dict[str, Any]) -> None:  # noqa: ARG001
    """Test AI improvement trigger."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG.copy()
    controller.config["gemini_api_key"] = "fake"
    controller.initialize_components()

    controller.pending_text = "Bad text"

    with patch("threading.Thread") as mock_thread:
        controller.on_improve_text()
        mock_thread.assert_called_once()
