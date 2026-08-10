"""Tests for app_controller module."""

import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from whisper_typing.app_controller import (
    DEFAULT_CONFIG,
    WhisperAppController,
    load_config,
    save_config,
)


@pytest.fixture
def mock_dependencies() -> Generator[dict[str, Any]]:
    """Mock all external dependencies for the controller."""
    with (
        patch("whisper_typing.app_controller.AudioRecorder") as mock_recorder,
        patch("whisper_typing.app_controller.Transcriber") as mock_transcriber,
        patch("whisper_typing.app_controller.AIImprover") as mock_improver,
        patch("whisper_typing.app_controller.WindowManager") as mock_window_manager,
        patch("whisper_typing.app_controller.AudioOverlay") as mock_overlay,
        patch("whisper_typing.app_controller.MediaController") as mock_media,
        patch("whisper_typing.app_controller.BrowserMediaBridge"),
        patch("pynput.keyboard.GlobalHotKeys") as mock_hotkeys,
        patch("whisper_typing.app_controller.sd") as mock_sd,
    ):
        yield {
            "recorder": mock_recorder,
            "transcriber": mock_transcriber,
            "improver": mock_improver,
            "window_manager": mock_window_manager,
            "overlay": mock_overlay,
            "media": mock_media,
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
    assert "<f9>" not in hotkey_map


def test_legacy_f9_config_cannot_restore_manual_typing_hotkey(
    mock_dependencies: dict[str, Any],
) -> None:
    """Test that a stale type_hotkey value is deliberately ignored."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {
        "gemini_api_key": "fake",
        "type_hotkey": "<f9>",
    }
    controller.initialize_components()

    controller.start_listener()

    args, _ = mock_dependencies["hotkeys"].call_args
    assert "<f9>" not in args[0]


def test_numpad_enter_is_consumed_by_the_windows_hook() -> None:
    """Test that the PTT key cannot activate a focused PiP control."""
    controller = WhisperAppController()
    controller.config = {
        "hotkey": "numpad_enter",
        "extra_hotkeys": [],
        "record_mode": "hold",
    }

    with (
        patch("whisper_typing.app_controller.keyboard.Listener") as listener_cls,
        patch.object(controller, "_record_key_down") as record_key_down,
    ):
        controller._setup_hold_listener()  # noqa: SLF001
        listener = listener_cls.return_value
        event_filter = listener_cls.call_args.kwargs["win32_event_filter"]
        key_data = MagicMock(vkCode=0x0D, flags=0x01)

        assert event_filter(0x0100, key_data) is False

    record_key_down.assert_called_once_with("numpad_enter")
    listener.suppress_event.assert_called_once_with()


def test_main_enter_is_not_consumed_by_the_numpad_hook() -> None:
    """Test that the ordinary Enter key remains unaffected."""
    controller = WhisperAppController()
    controller.config = {
        "hotkey": "numpad_enter",
        "extra_hotkeys": [],
        "record_mode": "hold",
    }

    with (
        patch("whisper_typing.app_controller.keyboard.Listener") as listener_cls,
        patch.object(controller, "_record_key_down") as record_key_down,
    ):
        controller._setup_hold_listener()  # noqa: SLF001
        listener = listener_cls.return_value
        event_filter = listener_cls.call_args.kwargs["win32_event_filter"]
        key_data = MagicMock(vkCode=0x0D, flags=0)

        assert event_filter(0x0100, key_data) is True

    record_key_down.assert_not_called()
    listener.suppress_event.assert_not_called()


def test_toggle_numpad_enter_debounces_repeat_until_key_up() -> None:
    """Test first physical press starts and the next physical press stops."""
    controller = WhisperAppController()
    controller.config = {
        "hotkey": "numpad_enter",
        "extra_hotkeys": [],
        "record_mode": "toggle",
    }

    with patch.object(controller, "_queue_record_toggle") as queue_toggle:
        controller._record_key_down("numpad_enter")  # noqa: SLF001
        controller._record_key_down("numpad_enter")  # noqa: SLF001  # auto-repeat
        controller._record_key_up("numpad_enter")  # noqa: SLF001
        controller._record_key_down("numpad_enter")  # noqa: SLF001

    expected_physical_presses = 2
    assert queue_toggle.call_count == expected_physical_presses


def test_toggle_numpad_enter_is_not_registered_as_a_generic_hotkey(
    mock_dependencies: dict[str, Any],
) -> None:
    """Test numpad Enter stays distinguishable from the ordinary Enter key."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {
        "gemini_api_key": "fake",
        "hotkey": "numpad_enter",
        "record_mode": "toggle",
    }
    controller.initialize_components()

    with patch("whisper_typing.app_controller.keyboard.Listener") as listener_cls:
        controller.start_listener()

    args, _ = mock_dependencies["hotkeys"].call_args
    assert "numpad_enter" not in args[0]
    listener_cls.assert_called_once()
    controller.stop()


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

    def stop_recorder() -> None:
        mock_recorder.recording = False

    mock_recorder.stop.side_effect = stop_recorder
    controller.stop_live_transcribe = threading.Event()

    # Trigger toggle (Stop)
    controller.on_record_toggle()

    mock_recorder.stop.assert_called_once()
    assert controller.stop_live_transcribe.is_set()
    controller.overlay.show_processing.assert_called_once_with()
    controller.overlay.hide.assert_called_once_with()


def test_toggle_stop_keeps_auto_type_behavior(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test toggle mode uses the same transcribe-and-type path as hold mode."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {
        "gemini_api_key": "fake",
        "auto_type": True,
    }
    controller.initialize_components()
    assert controller.recorder is not None
    controller.recorder.recording = True

    with patch.object(controller, "_stop_recording_and_type") as stop_and_type:
        controller.on_record_toggle()

    stop_and_type.assert_called_once_with()


def test_toggle_start_is_not_swallowed_while_previous_take_processes(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test a new recording may start while prior transcription finishes."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {"gemini_api_key": "fake"}
    controller.initialize_components()
    assert controller.recorder is not None
    controller.recorder.recording = False
    controller.is_processing = True
    controller._processing_start_time = time.time()  # noqa: SLF001

    controller.on_record_toggle()

    controller.recorder.start.assert_called_once_with()


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


def test_processing_counter_tracks_overlapping_jobs(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test that one completed take cannot hide a second active job."""
    controller = WhisperAppController()

    controller._begin_processing()  # noqa: SLF001
    controller._begin_processing()  # noqa: SLF001
    controller._finish_processing()  # noqa: SLF001

    assert controller.is_processing is True
    controller._finish_processing()  # noqa: SLF001
    assert controller.is_processing is False


def test_processing_spinner_stays_until_every_job_finishes(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test an earlier transcription cannot hide a newer processing spinner."""
    controller = WhisperAppController()

    controller._begin_processing()  # noqa: SLF001
    controller._begin_processing()  # noqa: SLF001
    controller._finish_processing()  # noqa: SLF001
    controller._hide_overlay_if_idle()  # noqa: SLF001

    controller.overlay.hide.assert_not_called()

    controller._finish_processing()  # noqa: SLF001
    controller._hide_overlay_if_idle()  # noqa: SLF001

    controller.overlay.hide.assert_called_once_with()


def test_open_history_exports_and_launches_report(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Test tray history opens a visible standalone report."""
    controller = WhisperAppController()
    report = tmp_path / "history.html"
    history = controller._persistent_history  # noqa: SLF001
    with (
        patch.object(history, "export_html", return_value=report),
        patch("whisper_typing.app_controller.os.startfile") as mock_startfile,
    ):
        controller.open_history()

    mock_startfile.assert_called_once_with(report)


def test_config_round_trip_is_atomic_and_unicode_safe(tmp_path: Path) -> None:
    """Test that Russian prompts survive configuration writes."""
    path = tmp_path / "config.json"
    config = {"format_prompt": "ну, типа — без mojibake"}

    save_config(config, str(path))

    assert load_config(str(path)) == config
    assert not path.with_suffix(".json.tmp").exists()


def test_media_resumes_only_after_the_microphone_is_closed(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test the tail of a take can never record the video's own audio."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {"gemini_api_key": "fake", "auto_type": True}
    controller.initialize_components()
    assert controller.recorder is not None
    controller.recorder.recording = True
    # No transcriber: the background job must not reach the real clipboard and
    # fire Ctrl+V into whatever window the developer has focused.
    controller.transcriber = None
    order: list[str] = []

    def stop_recorder() -> str:
        order.append("microphone-closed")
        controller.recorder.recording = False
        return "audio"

    controller.recorder.stop.side_effect = stop_recorder

    with (
        patch.object(
            controller,
            "_queue_media_resume",
            side_effect=lambda: order.append("media-resumed"),
        ),
        patch("whisper_typing.app_controller.save_audio_backup", return_value=None),
    ):
        controller.on_record_toggle()

    assert order == ["microphone-closed", "media-resumed"]


def test_a_pause_queued_by_an_already_finished_take_is_dropped(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test a quick tap cannot leave media paused with no resume behind it."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {"gemini_api_key": "fake"}
    controller.initialize_components()
    media = MagicMock()
    controller._media = media  # noqa: SLF001

    controller._ptt_gen = 1  # noqa: SLF001
    controller._queue_media_pause()  # noqa: SLF001
    # The take ended before the worker reached the job.
    controller._ptt_gen = 2  # noqa: SLF001
    controller._media_queue.put(None)  # noqa: SLF001
    controller._media_worker()  # noqa: SLF001

    media.pause_if_playing.assert_not_called()


def test_media_commands_run_in_the_order_the_keys_were_pressed(
    mock_dependencies: dict[str, Any],  # noqa: ARG001
) -> None:
    """Test a slow pause can no longer land after the resume that undoes it."""
    controller = WhisperAppController()
    controller.config = DEFAULT_CONFIG | {"gemini_api_key": "fake"}
    controller.initialize_components()
    order: list[str] = []
    media = MagicMock()
    media.resume.side_effect = lambda: order.append("resume")
    media.pause_if_playing.side_effect = lambda: order.append("pause")
    controller._media = media  # noqa: SLF001

    controller._queue_media_resume()  # end of the previous take  # noqa: SLF001
    controller._queue_media_pause()  # start of the next one  # noqa: SLF001
    controller._media_queue.put(None)  # noqa: SLF001
    controller._media_worker()  # noqa: SLF001

    assert order == ["resume", "pause"]


def test_windows_match_prefers_native_handle() -> None:
    """Test safe focus comparison for separate wrappers of one HWND."""
    first = MagicMock()
    second = MagicMock()
    first._hWnd = 42  # noqa: SLF001
    second._hWnd = 42  # noqa: SLF001

    assert WhisperAppController._windows_match(first, second) is True  # noqa: SLF001
