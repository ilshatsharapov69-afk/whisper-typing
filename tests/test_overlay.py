"""Tests for the recording and processing overlay states."""

from unittest.mock import MagicMock

from whisper_typing.overlay import PROCESSING_SIZE, AudioOverlay


def test_processing_mode_uses_a_compact_square_spinner() -> None:
    """Test the processing indicator has stable circular dimensions."""
    overlay = AudioOverlay()

    overlay.show_processing()

    assert overlay._processing is True  # noqa: SLF001
    assert overlay._recorder is None  # noqa: SLF001
    assert overlay._get_dimensions() == (PROCESSING_SIZE, PROCESSING_SIZE)  # noqa: SLF001


def test_processing_mode_schedules_an_immediate_rebuild() -> None:
    """Test second-press feedback replaces the visualizer on the Tk thread."""
    overlay = AudioOverlay()
    root = MagicMock()
    overlay._root = root  # noqa: SLF001

    overlay.show_processing()

    root.after.assert_called_once_with(0, overlay._rebuild_and_show)  # noqa: SLF001


def test_blue_spinner_is_created_and_animated() -> None:
    """Test the processing state draws rotating blue arcs and a pulsing dot."""
    overlay = AudioOverlay()
    canvas = MagicMock()
    canvas.create_oval.side_effect = [1, 2, 5]
    canvas.create_arc.side_effect = [3, 4]
    overlay._canvas = canvas  # noqa: SLF001
    overlay._win_w = PROCESSING_SIZE  # noqa: SLF001
    overlay._win_h = PROCESSING_SIZE  # noqa: SLF001

    overlay._init_processing()  # noqa: SLF001
    overlay._frame_count = 7  # noqa: SLF001
    overlay._draw_processing()  # noqa: SLF001

    expected_arcs = 2
    assert canvas.create_arc.call_count == expected_arcs
    assert len(overlay._canvas_items) == 5  # noqa: SLF001, PLR2004
    expected_animated_items = 3
    assert canvas.itemconfig.call_count >= expected_animated_items
    canvas.coords.assert_called_once()


def test_new_recording_replaces_processing_mode() -> None:
    """Test a newly started take owns the overlay instead of an older spinner."""
    overlay = AudioOverlay()
    root = MagicMock()
    recorder = MagicMock()
    overlay._root = root  # noqa: SLF001
    overlay._processing = True  # noqa: SLF001

    overlay.show(recorder)

    assert overlay._processing is False  # noqa: SLF001
    assert overlay._recorder is recorder  # noqa: SLF001
    root.after.assert_called_once_with(0, overlay._rebuild_and_show)  # noqa: SLF001
