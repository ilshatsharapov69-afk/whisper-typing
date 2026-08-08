"""Tests for the recording and processing overlay states."""

import math
from unittest.mock import MagicMock, patch

import numpy as np

from whisper_typing.overlay import (
    MODE_PROCESSING,
    MODE_RECORDING,
    PROCESSING_FRAME_COUNT,
    PROCESSING_FRAME_MS,
    PROCESSING_SIZE,
    AudioOverlay,
    _processing_pil_frames,
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


def test_blue_spinner_uses_prerendered_frames() -> None:
    """Test processing swaps one image instead of drawing jagged Tk arcs."""
    overlay = AudioOverlay()
    canvas = MagicMock()
    frames = [MagicMock() for _ in range(PROCESSING_FRAME_COUNT)]
    overlay._canvas = canvas  # noqa: SLF001
    overlay._win_w = PROCESSING_SIZE  # noqa: SLF001
    overlay._win_h = PROCESSING_SIZE  # noqa: SLF001
    overlay._processing_frames = frames  # noqa: SLF001

    overlay._init_processing()  # noqa: SLF001
    overlay._frame_count = 7  # noqa: SLF001
    overlay._draw_processing()  # noqa: SLF001

    canvas.create_image.assert_called_once_with(
        PROCESSING_SIZE / 2,
        PROCESSING_SIZE / 2,
        image=frames[0],
    )
    canvas.itemconfig.assert_called_once_with(
        overlay._canvas_items[0],  # noqa: SLF001
        image=frames[7],
    )


def test_processing_frames_are_antialiased_and_visibly_animated() -> None:
    """Test high-resolution rendering produces smooth, changing RGBA frames."""
    frames = _processing_pil_frames()

    assert len(frames) == PROCESSING_FRAME_COUNT
    assert all(frame.size == (PROCESSING_SIZE, PROCESSING_SIZE) for frame in frames)
    alpha = np.asarray(frames[0].getchannel("A"))
    fully_opaque = 255
    assert np.any((alpha > 0) & (alpha < fully_opaque))
    assert frames[0].tobytes() != frames[1].tobytes()


def test_processing_frames_are_prepared_once() -> None:
    """Test all expensive rendering happens before the spinner is displayed."""
    overlay = AudioOverlay()
    overlay._root = MagicMock()  # noqa: SLF001
    rendered = [MagicMock(), MagicMock()]

    with (
        patch(
            "whisper_typing.overlay._processing_pil_frames",
            return_value=rendered,
        ) as render_frames,
        patch(
            "whisper_typing.overlay.ImageTk.PhotoImage",
            side_effect=[MagicMock(), MagicMock()],
        ) as photo_image,
    ):
        overlay._prepare_processing_frames()  # noqa: SLF001
        overlay._prepare_processing_frames()  # noqa: SLF001

    render_frames.assert_called_once_with()
    assert photo_image.call_count == len(rendered)


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
    root.after.assert_called_once_with(
        PROCESSING_FRAME_MS,
        overlay._update_loop,  # noqa: SLF001
    )
