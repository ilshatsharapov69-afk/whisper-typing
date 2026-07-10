"""Audio transcription using faster-whisper.

Heavy imports (faster_whisper, torch, ctranslate2) are deferred to first use
to avoid ~800MB RAM overhead at startup.
"""

from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

from whisper_typing.constants import WHISPER_NAME_MAP

if TYPE_CHECKING:
    import numpy as np

# Whisper hallucination patterns — phrases the model generates on silence/noise
_HALLUCINATION_PATTERNS: set[str] = {
    "thank you",
    "thanks",
    "thank you for watching",
    "thanks for watching",
    "thank you so much",
    "thank you very much",
    "you",
    "bye",
    "goodbye",
    "the end",
    "subscribers",
    "subscribe",
    "like and subscribe",
    "please subscribe",
    "thanks for listening",
    "thank you for listening",
    "subtitles by",
    "amara.org",
    # Russian hallucinations on silence/noise
    "продолжение следует",
    "субтитры подготовил",
    "субтитры подготовлены",
    "субтитры сделал",
    "субтитры создавал",
    "субтитры создал",
    "редактор субтитров",
    "корректор",
    "спасибо за просмотр",
    "спасибо за внимание",
    "всем спасибо",
}

# Regex: entire text is just repetitions of a short word/phrase separated by spaces/punctuation
_REPETITION_RE = re.compile(
    r"^(\b\w{1,12}\b)(?:[,.\s!?]+\1){2,}[,.\s!?]*$", re.IGNORECASE
)


class Transcriber:
    """Handles speech-to-text conversion using Whisper models."""

    def __init__(
        self,
        model_id: str = "openai/whisper-base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "auto",
        download_root: str | None = None,
        lazy: bool = False,
    ) -> None:
        """Initialize the Transcriber.

        Args:
            model_id: HuggingFace model ID or faster-whisper model name.
            language: Optional language code for transcription.
            device: Device to run the model on ('cpu' or 'cuda').
            compute_type: Quantization type for the model.
            download_root: Directory to download models to.
            lazy: If True, defer model loading until first transcribe() call.

        """
        self.download_root = download_root
        self.model_name = WHISPER_NAME_MAP.get(model_id, model_id)
        self.language = language
        self._requested_device = device
        self._requested_compute_type = compute_type

        # These get resolved when model actually loads
        self.device: str = "cuda" if device.startswith("cuda") else "cpu"
        if compute_type == "auto":
            self.compute_type = "float16" if self.device == "cuda" else "int8"
        else:
            self.compute_type = compute_type

        self.model: Any = None  # WhisperModel, but type deferred
        self._lock = threading.Lock()
        if not lazy:
            self._load_model()

    def _load_model(self) -> None:
        """Load the WhisperModel into memory (imports heavy deps here)."""
        from faster_whisper import WhisperModel

        # Validate CUDA at load time — try cuda, fall back to cpu on failure
        if self._requested_device.startswith("cuda"):
            try:
                self.model = WhisperModel(
                    self.model_name,
                    device="cuda",
                    compute_type=self.compute_type,
                    download_root=self.download_root,
                )
                self.device = "cuda"
                return
            except Exception:  # noqa: BLE001
                # CUDA not available — fall back to CPU
                self.device = "cpu"
                self.compute_type = "int8" if self._requested_compute_type == "auto" else self._requested_compute_type

        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
            download_root=self.download_root,
        )

    def _ensure_model(self) -> Any:  # noqa: ANN401
        """Ensure model is loaded, load lazily if needed."""
        if self.model is None:
            self._load_model()
        return self.model

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        """Check if transcribed text is a known Whisper hallucination."""
        normalized = text.strip().lower().rstrip(".,!?")
        if normalized in _HALLUCINATION_PATTERNS:
            return True
        if _REPETITION_RE.match(normalized):
            return True
        return False

    @staticmethod
    def _audio_is_silent(audio: np.ndarray, threshold: float = 0.002) -> bool:
        """Check if audio energy is below silence threshold.

        Lowered from 0.01 (≈−40 dBFS) to 0.002 (≈−54 dBFS) so far-mic /
        quiet speech is not dropped before Whisper sees it. True silence
        from a typical mic floors around 0.0001–0.0005, so this still
        rejects empty buffers.
        """
        import numpy as np

        rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
        return rms < threshold

    def transcribe(self, audio_input: str | np.ndarray) -> str:
        """Transcribe audio input (file path or numpy array) to text.

        Args:
            audio_input: File path to audio or numpy array of audio samples.

        Returns:
            The transcribed text, or empty string if silence/hallucination.

        """
        import numpy as np

        if isinstance(audio_input, np.ndarray) and self._audio_is_silent(audio_input):
            return ""

        with self._lock:
            model = self._ensure_model()
            segments, _info = model.transcribe(
                audio_input,
                beam_size=5,
                language=self.language,
                condition_on_previous_text=False,
                vad_filter=True,
                # 1000ms (vs live preview's 500ms) — VAD is less likely to
                # trim entire utterance when speech is quiet/far from mic.
                vad_parameters={"min_silence_duration_ms": 1000},
            )
            text = " ".join([segment.text for segment in segments]).strip()

        if self._is_hallucination(text):
            return ""

        return text

    def transcribe_fast(self, audio_input: str | np.ndarray) -> str:
        """Fast transcription for live preview (greedy decoding, with VAD).

        Uses beam_size=1 for minimal latency. Suitable for showing
        real-time preview text while recording.  Non-blocking: if the model
        is already busy (e.g. final transcription), returns empty immediately.

        Args:
            audio_input: File path to audio or numpy array of audio samples.

        Returns:
            The transcribed text, or empty string if silence/hallucination/busy.

        """
        import numpy as np

        if isinstance(audio_input, np.ndarray) and self._audio_is_silent(audio_input):
            return ""

        # Non-blocking: skip if model is busy with another transcription
        if not self._lock.acquire(blocking=False):
            return ""
        try:
            model = self._ensure_model()
            segments, _info = model.transcribe(
                audio_input,
                beam_size=1,
                language=self.language,
                condition_on_previous_text=False,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            text = " ".join([segment.text for segment in segments]).strip()
        finally:
            self._lock.release()

        if self._is_hallucination(text):
            return ""

        return text
