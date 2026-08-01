"""Tests for audio_capture module."""

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
    with patch("sounddevice.InputStream"):
        recorder = AudioRecorder()

        recorder.start()
        assert recorder.recording is True
        assert recorder.thread is not None
        assert recorder.thread.is_alive()

        # Stop
        recorder.stop()
        assert recorder.recording is False
        # Thread should be cleaned up after stop
        assert recorder.thread is None


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


def test_stop_recovers_frames_after_stream_failure() -> None:
    """Test that buffered speech survives recording=False after a stream crash."""
    recorder = AudioRecorder(device_index=0)
    buffered = np.ones((FAKE_FRAME_SIZE, 1), dtype=np.float32)
    recorder.frames.append(buffered)
    recorder.recording = False

    result = recorder.stop()

    assert result is not None
    assert np.array_equal(result, buffered.flatten())


@patch("sounddevice.InputStream")
def test_start_when_already_recording(mock_input_stream: MagicMock) -> None:  # noqa: ARG001
    """Test start does nothing when already recording."""
    recorder = AudioRecorder(device_index=0)
    recorder.recording = True
    recorder.start()
    # Should return early without starting new thread
    assert recorder.thread is None


def test_record_exception_handling() -> None:
    """Test _record handles exceptions gracefully."""
    with patch("sounddevice.InputStream") as mock_stream:
        mock_stream.side_effect = Exception("Stream error")
        recorder = AudioRecorder()
        recorder.recording = True
        recorder._record()  # noqa: SLF001
        # After exception, recording should be False (set in finally)
        assert recorder.recording is False


def test_record_stops_on_event() -> None:
    """Test _record exits when stop event is set."""
    with patch("sounddevice.InputStream"):
        recorder = AudioRecorder()
        recorder.recording = True

        # Set stop event immediately — _record should exit
        recorder._stop_event.set()  # noqa: SLF001
        recorder._record()  # noqa: SLF001

        assert recorder.recording is False
