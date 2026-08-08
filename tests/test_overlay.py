"""Tests for the recording and processing overlay states."""

import math
from unittest.mock import MagicMock, patch

import numpy as np

from whisper_typing.overlay import (
    BAR_COUNT,
    MODE_PROCESSING,
    MODE_RECORDING,
    PROCESSING_FRAME_COUNT,
    PROCESSING_FRAME_MS,
    PROCESSING_SIZE,
    VISUALIZER_ANALYSIS_INTERVAL_FRAMES,
    VISUALIZER_FRAME_MS,
    VISUALIZER_SAMPLE_COUNT,
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
    """Test the spinner is smooth, transparent, and visibly animated."""
    frames = _processing_pil_frames()

    assert len(frames) == PROCESSING_FRAME_COUNT
    assert PROCESSING_FRAME_COUNT == 30  # noqa: PLR2004
    assert PROCESSING_SIZE == 48  # noqa: PLR2004
    assert all(frame.size == (PROCESSING_SIZE, PROCESSING_SIZE) for frame in frames)
    alpha = np.asarray(frames[0].getchannel("A"))
    fully_opaque = 255
    assert np.any((alpha > 0) & (alpha < fully_opaque))
    assert alpha[0, 0] == 0
    assert alpha[PROCESSING_SIZE // 2, PROCESSING_SIZE // 2] == 0
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

    assert len(levels) == BAR_COUNT
    assert max(levels) > 0.5  # noqa: PLR2004
    assert max(levels) - min(levels) > 0.2  # noqa: PLR2004


def test_silence_keeps_equalizer_at_rest() -> None:
    """Test auto-normalization does not amplify silence into fake activity."""
    audio = np.zeros(4096, dtype=np.float32)

    levels = AudioOverlay._spectrum_levels(audio, 16000)  # noqa: SLF001

    assert levels == [0.0] * BAR_COUNT


def test_equalizer_uses_short_audio_window_for_responsive_motion() -> None:
    """Test visualizer avoids a sluggish quarter-second FFT window."""
    overlay = AudioOverlay()
    recorder = MagicMock()
    recorder.sample_rate = 16000
    recorder.get_recent_data.return_value = np.ones(1024, dtype=np.float32)
    overlay._recorder = recorder  # noqa: SLF001
    overlay._spectrum_levels = MagicMock(return_value=[0.5] * BAR_COUNT)  # type: ignore[method-assign]  # noqa: SLF001

    overlay._sample_audio()  # noqa: SLF001

    recorder.get_recent_data.assert_called_once_with(
        max_samples=VISUALIZER_SAMPLE_COUNT,
    )
    assert overlay._bar_heights == [0.0] * BAR_COUNT  # noqa: SLF001
    assert overlay._target_bar_heights == [0.5] * BAR_COUNT  # noqa: SLF001

    overlay._animate_levels()  # noqa: SLF001

    target_level = 0.5
    assert all(
        0.0 < level < target_level
        for level in overlay._bar_heights  # noqa: SLF001
    )


def test_recording_visualizer_uses_a_lightweight_frame_rate() -> None:
    """Test recording animation avoids a needless 60 FPS update loop."""
    overlay = AudioOverlay()
    root = MagicMock()
    overlay._root = root  # noqa: SLF001
    overlay._running = True  # noqa: SLF001

    overlay._update_loop()  # noqa: SLF001

    root.after.assert_called_once_with(
        VISUALIZER_FRAME_MS,
        overlay._update_loop,  # noqa: SLF001
    )
    assert VISUALIZER_FRAME_MS == 33  # noqa: PLR2004


def test_equalizer_analyzes_audio_less_often_than_it_animates() -> None:
    """Test expensive FFT sampling runs only on alternating visual frames."""
    overlay = AudioOverlay()
    root = MagicMock()
    overlay._root = root  # noqa: SLF001
    overlay._running = True  # noqa: SLF001
    overlay._visible = True  # noqa: SLF001
    overlay._recorder = MagicMock()  # noqa: SLF001
    overlay._sample_audio = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001
    overlay._animate_levels = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001
    overlay._draw = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001

    for _ in range(VISUALIZER_ANALYSIS_INTERVAL_FRAMES):
        overlay._update_loop()  # noqa: SLF001

    overlay._sample_audio.assert_called_once_with()  # type: ignore[attr-defined]  # noqa: SLF001
    assert overlay._animate_levels.call_count == 2  # type: ignore[attr-defined]  # noqa: PLR2004, SLF001
    assert overlay._draw.call_count == 2  # type: ignore[attr-defined]  # noqa: PLR2004, SLF001


def test_default_bars_use_one_canvas_item_per_frequency_band() -> None:
    """Test the default visualizer avoids separate glow and cap objects."""
    overlay = AudioOverlay()
    canvas = MagicMock()
    canvas.create_rectangle.side_effect = range(1, BAR_COUNT + 1)
    overlay._canvas = canvas  # noqa: SLF001
    overlay._win_h = 67  # noqa: SLF001

    overlay._init_bars()  # noqa: SLF001
    overlay._bar_heights = [0.5] * BAR_COUNT  # noqa: SLF001
    overlay._draw_bars()  # noqa: SLF001

    assert len(overlay._canvas_items) == BAR_COUNT  # noqa: SLF001
    canvas.create_oval.assert_not_called()
    assert canvas.coords.call_count == BAR_COUNT
    assert canvas.itemconfig.call_count == BAR_COUNT


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
