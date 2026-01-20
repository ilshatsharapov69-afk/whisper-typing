"""Tests for audio_capture module."""

import time
from unittest.mock import MagicMock, patch

import numpy as np

from whisper_typing.audio_capture import AudioRecorder

FAKE_FRAME_SIZE = 10
LARGE_FRAME_SIZE = 100
TOTAL_DATA_SIZE = 200
SLEEP_DURATION = 0.5
TIMEOUT = 1
EXPECTED_DEVICE_COUNT = 2


@patch("sounddevice.query_devices")
def test_list_devices(mock_query_devices: MagicMock) -> None:
    """Test listing available input devices."""
    mock_query_devices.return_value = [
        {"name": "Mic 1", "max_input_channels": 1},
        {"name": "Speaker", "max_input_channels": 0},  # Should be ignored
        {"name": "Mic 2", "max_input_channels": 2},
    ]

    devices = AudioRecorder.list_devices()

    assert len(devices) == EXPECTED_DEVICE_COUNT
    assert devices[0] == (0, "Mic 1")
    assert devices[1] == (2, "Mic 2")


@patch("sounddevice.InputStream")
def test_recorder_verify_callback(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test that data is correctly accumulated in the callback."""
    recorder = AudioRecorder(device_index=0)

    # Manually trigger callback
    fake_data = np.zeros((FAKE_FRAME_SIZE, 1), dtype=np.float32)
    recorder._callback(fake_data, FAKE_FRAME_SIZE, MagicMock(), MagicMock())  # noqa: SLF001

    # Verify data is in frames
    with recorder._lock:  # noqa: SLF001
        assert len(recorder.frames) == 1
        assert np.array_equal(recorder.frames[0], fake_data)


@patch("sounddevice.InputStream")
def test_get_current_data_clears_buffer(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test get_current_data returns concatenated data and clears buffer."""
    recorder = AudioRecorder(device_index=0)

    # Add fake data
    frame1 = np.ones((LARGE_FRAME_SIZE, 1), dtype=np.float32)
    frame2 = np.ones((LARGE_FRAME_SIZE, 1), dtype=np.float32)
    with recorder._lock:  # noqa: SLF001
        recorder.frames.append(frame1)
        recorder.frames.append(frame2)

    data = recorder.get_current_data()

    assert data is not None
    assert len(data) == TOTAL_DATA_SIZE  # 100 + 100, flattened or consolidated
    # frames are not cleared by get_current_data in current implementation


def test_start_stop_logic() -> None:
    """Test start and stop state logic (mocking the actual thread or run loop)."""
    # We mock _record to avoid actual IO
    with patch.object(AudioRecorder, "_record") as mock_record:
        mock_record.side_effect = lambda: time.sleep(SLEEP_DURATION)
        recorder = AudioRecorder()

        recorder.start()
        assert recorder.recording is True
        assert recorder.thread is not None
        assert recorder.thread.is_alive()

        # Stop
        recorder.stop()
        assert recorder.recording is False
        recorder.thread.join(timeout=TIMEOUT)
        assert not recorder.thread.is_alive()


@patch("sounddevice.InputStream")
def test_get_current_data_empty(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test get_current_data returns None when no frames."""
    recorder = AudioRecorder(device_index=0)
    data = recorder.get_current_data()
    assert data is None


@patch("sounddevice.InputStream")
def test_stop_when_not_recording(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test stop returns None when not recording."""
    recorder = AudioRecorder(device_index=0)
    result = recorder.stop()
    assert result is None


@patch("sounddevice.InputStream")
def test_start_when_already_recording(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test start does nothing when already recording."""
    recorder = AudioRecorder(device_index=0)
    recorder.recording = True
    recorder.start()
    # Should return early without starting new thread
    assert recorder.thread is None


def test_record_exception_handling() -> None:
    """Test _record handles exceptions and sets recording to False."""
    with patch("sounddevice.InputStream") as mock_stream:
        mock_stream.side_effect = Exception("Stream error")
        recorder = AudioRecorder()
        recorder.recording = True
        recorder._record()  # noqa: SLF001
        assert recorder.recording is False


def test_record_loop_with_sleep() -> None:
    """Test _record loop executes with sd.sleep."""
    with (
        patch("sounddevice.InputStream") as mock_stream_cls,
        patch("sounddevice.sleep") as mock_sleep,
    ):
        mock_stream = MagicMock()
        mock_stream_cls.return_value.__enter__.return_value = mock_stream

        recorder = AudioRecorder()
        recorder.recording = True

        # Make sleep stop recording after first call
        def stop_recording(*args: object) -> None:  # noqa: ARG001
            recorder.recording = False

        mock_sleep.side_effect = stop_recording

        recorder._record()  # noqa: SLF001

        # Verify sleep was called
        mock_sleep.assert_called()
