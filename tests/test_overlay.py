"""Tests for the recording and processing overlay states."""

import math
from unittest.mock import MagicMock

import numpy as np

from whisper_typing.overlay import (
    MODE_PROCESSING,
    MODE_RECORDING,
    PROCESSING_SIZE,
    AudioOverlay,
)


def test_processing_mode_uses_a_compact_square_spinner() -> None:
    """Test the processing indicator has stable circular dimensions."""
    overlay = AudioOverlay()

    overlay.show_processing()
    overlay._processing = True  # noqa: SLF001

    assert overlay._pending_mode == MODE_PROCESSING  # noqa: SLF001
    assert overlay._recorder is None  # noqa: SLF001
    assert overlay._get_dimensions() == (PROCESSING_SIZE, PROCESSING_SIZE)  # noqa: SLF001


def test_processing_mode_schedules_an_immediate_rebuild() -> None:
    """Test second-press feedback replaces the visualizer on the Tk thread."""
    overlay = AudioOverlay()
    root = MagicMock()
    overlay._root = root  # noqa: SLF001

    overlay.show_processing()

    root.after.assert_called_once_with(
        0,
        overlay._switch_mode,  # noqa: SLF001
        MODE_PROCESSING,
    )
    # The active canvas mode is untouched until the Tk callback runs, so an
    # in-flight animation frame can never see mismatched canvas items.
    assert overlay._processing is False  # noqa: SLF001


def test_blue_spinner_is_created_and_animated() -> None:
    """Test the processing state draws rotating blue arcs and a pulsing dot."""
    overlay = AudioOverlay()
    canvas = MagicMock()
    canvas.create_oval.side_effect = [1, 2, 3, 7]
    canvas.create_arc.side_effect = [4, 5, 6]
    overlay._canvas = canvas  # noqa: SLF001
    overlay._win_w = PROCESSING_SIZE  # noqa: SLF001
    overlay._win_h = PROCESSING_SIZE  # noqa: SLF001

    overlay._init_processing()  # noqa: SLF001
    overlay._frame_count = 7  # noqa: SLF001
    overlay._draw_processing()  # noqa: SLF001

    expected_arcs = 3
    assert canvas.create_arc.call_count == expected_arcs
    expected_spinner_items = 7
    assert len(overlay._canvas_items) == expected_spinner_items  # noqa: SLF001
    expected_animated_items = 4
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

    assert overlay._processing is True  # noqa: SLF001
    assert overlay._pending_mode == MODE_RECORDING  # noqa: SLF001
    assert overlay._recorder is recorder  # noqa: SLF001
    root.after.assert_called_once_with(
        0,
        overlay._switch_mode,  # noqa: SLF001
        MODE_RECORDING,
    )


def test_voice_audio_produces_a_real_frequency_equalizer() -> None:
    """Test a voiced signal drives distinct, visible spectrum bars."""
    sample_rate = 16000
    duration = 0.25
    times = np.arange(int(sample_rate * duration)) / sample_rate
    audio = (0.08 * np.sin(2 * math.pi * 440 * times)).astype(np.float32)

    levels = AudioOverlay._spectrum_levels(audio, sample_rate)  # noqa: SLF001

    assert len(levels) == 32  # noqa: PLR2004
    assert max(levels) > 0.5  # noqa: PLR2004
    assert max(levels) - min(levels) > 0.2  # noqa: PLR2004


def test_silence_keeps_equalizer_at_rest() -> None:
    """Test auto-normalization does not amplify silence into fake activity."""
    audio = np.zeros(4096, dtype=np.float32)

    levels = AudioOverlay._spectrum_levels(audio, 16000)  # noqa: SLF001

    assert levels == [0.0] * 32


def test_render_failure_rebuilds_and_keeps_animation_scheduled() -> None:
    """Test one bad canvas frame cannot permanently freeze the overlay."""
    overlay = AudioOverlay()
    root = MagicMock()
    overlay._root = root  # noqa: SLF001
    overlay._running = True  # noqa: SLF001
    overlay._visible = True  # noqa: SLF001
    overlay._processing = True  # noqa: SLF001
    overlay._draw_processing = MagicMock(side_effect=RuntimeError("bad frame"))  # type: ignore[method-assign]  # noqa: SLF001
    overlay._rebuild_canvas = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001

    overlay._update_loop()  # noqa: SLF001

    overlay._rebuild_canvas.assert_called_once_with()  # type: ignore[attr-defined]  # noqa: SLF001
    root.after.assert_called_once_with(33, overlay._update_loop)  # noqa: SLF001
