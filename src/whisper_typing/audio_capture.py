"""Audio recording utilities using sounddevice."""

import threading
from typing import Final

import numpy as np
import sounddevice as sd


class AudioRecorder:
    """Handles audio capture from input devices."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device_index: int | str | None = None,
    ) -> None:
        """Initialize the AudioRecorder.

        Args:
            sample_rate: Audio sampling rate in Hz.
            channels: Number of audio channels.
            device_index: Index or name of the input device.

        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.device_index = device_index
        self.recording = False
        # Use list for easier access to current buffer
        self.frames: list[np.ndarray] = []
        self.thread: threading.Thread | None = None
        self._lock: Final[threading.Lock] = threading.Lock()
        self._stop_event = threading.Event()
        # Last exception raised inside _record() — exposes silent failures
        # (USB hiccup, driver error, exclusive-mode conflict) to callers.
        self.last_error: str | None = None

    @staticmethod
    def list_devices() -> list[tuple[int, str]]:
        """List all available input devices.

        Returns:
            A list of tuples containing device index and name.

        """
        devices = sd.query_devices()
        input_devices = []
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                input_devices.append((i, dev["name"]))
        return input_devices

    # Max samples to keep in buffer (30 minutes at 16kHz ≈ 115MB float32).
    # Anything longer silently loses its beginning — keep this generous.
    _MAX_SAMPLES: int = 16000 * 1800
    _total_samples: int = 0

    def _callback(
        self,
        indata: np.ndarray,
        _frames: int,
        _time: sd.RawInputStream,
        status: sd.CallbackFlags,
    ) -> None:
        """Handle audio data from sounddevice callback.

        Args:
            indata: The captured audio data.
            _frames: Missing from signature but provided by sounddevice.
            _time: Missing from signature but provided by sounddevice.
            status: Callback flags.

        """
        if status:
            # Optionally log status here
            pass
        with self._lock:
            self.frames.append(indata.copy())
            self._total_samples += len(indata)
            # Prevent unbounded memory growth — trim oldest frames past _MAX_SAMPLES
            while self._total_samples > self._MAX_SAMPLES and len(self.frames) > 1:
                removed = self.frames.pop(0)
                self._total_samples -= len(removed)

    def _record(self) -> None:
        """Run the internal recording loop."""
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                device=self.device_index,
                callback=self._callback,
            ):
                # Wait on event instead of polling — wakes up instantly on stop()
                self._stop_event.wait()
        except Exception as e:  # noqa: BLE001
            # Record so the caller can see WHY recording stopped silently.
            self.last_error = f"{type(e).__name__}: {e}"
            try:
                import logging

                logging.getLogger("whisper_typing").exception(
                    "AudioRecorder._record crashed"
                )
            except Exception:  # noqa: BLE001, S110
                pass
        finally:
            self.recording = False

    def start(self) -> None:
        """Start recording."""
        if self.recording:
            return

        # Ensure previous recording thread is fully dead before starting new one
        if self.thread is not None and self.thread.is_alive():
            self._stop_event.set()
            self.recording = False
            self.thread.join(timeout=2.0)
            self.thread = None

        self._stop_event.clear()
        self.recording = True
        self.last_error = None
        with self._lock:
            self.frames = []  # Clear frames
            self._total_samples = 0
        self.thread = threading.Thread(target=self._record, daemon=True)
        self.thread.start()

    def get_current_data(self) -> np.ndarray | None:
        """Get the current accumulated audio data as a numpy array.

        Returns:
            The accumulated audio data as a 1D numpy array, or None if no data.

        """
        with self._lock:
            if not self.frames:
                return None
            data = list(self.frames)  # Copy list

        if not data:
            return None

        # Concatenate and flatten to 1D array for mono
        recording = np.concatenate(data, axis=0)
        if self.channels == 1:
            recording = recording.flatten()
        return recording

    def get_recent_data(self, max_samples: int = 8000) -> np.ndarray | None:
        """Get only the most recent audio samples (lightweight, for visualizer).

        Args:
            max_samples: Maximum number of samples to return.

        Returns:
            The recent audio data as a 1D numpy array, or None if no data.

        """
        with self._lock:
            if not self.frames:
                return None
            # Walk backwards through frames to collect enough samples
            collected: list[np.ndarray] = []
            total = 0
            for frame in reversed(self.frames):
                collected.append(frame)
                total += len(frame)
                if total >= max_samples:
                    break

        collected.reverse()
        chunk = np.concatenate(collected, axis=0)
        if self.channels == 1:
            chunk = chunk.flatten()
        return chunk[-max_samples:]

    def stop(self) -> np.ndarray | None:
        """Stop recording and return audio data as numpy array (float32).

        Returns:
            The complete audio data as a 1D numpy array, or None if not recording.

        """
        # A PortAudio/USB failure sets ``recording`` to False in _record's
        # finally block.  The old early return threw away every frame captured
        # before that failure, which made a long dictation appear to vanish.
        # Always stop/join and return any recoverable buffered audio.
        self.recording = False
        self._stop_event.set()
        if self.thread:
            self.thread.join(timeout=3.0)
            self.thread = None

        return self.get_current_data()
