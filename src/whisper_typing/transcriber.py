"""Audio transcription using faster-whisper."""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from faster_whisper import WhisperModel

from whisper_typing.constants import WHISPER_NAME_MAP

if TYPE_CHECKING:
    import numpy as np


class Transcriber:
    """Handles speech-to-text conversion using Whisper models."""

    def __init__(
        self,
        model_id: str = "openai/whisper-base",
        language: str | None = None,
        device: str = "cpu",
        compute_type: str = "auto",
    ) -> None:
        """Initialize the Transcriber.

        Args:
            model_id: HuggingFace model ID or faster-whisper model name.
            language: Optional language code for transcription.
            device: Device to run the model on ('cpu' or 'cuda').
            compute_type: Quantization type for the model.

        """
        self.model_name = WHISPER_NAME_MAP.get(model_id, model_id)
        self.language = language

        # Validate device
        if device.startswith("cuda") and not torch.cuda.is_available():
            device = "cpu"

        # Faster-whisper device names are simpler
        self.device = "cuda" if device.startswith("cuda") else "cpu"

        # Select compute type if auto
        if compute_type == "auto":
            # GPU: float16 is standard, CPU: int8 is faster
            if self.device == "cuda":
                self.compute_type = "float16"
            else:
                self.compute_type = "int8"
        else:
            self.compute_type = compute_type

        self.model = WhisperModel(
            self.model_name, device=self.device, compute_type=self.compute_type
        )

    def transcribe(self, audio_input: str | np.ndarray) -> str:
        """Transcribe audio input (file path or numpy array) to text.

        Args:
            audio_input: File path to audio or numpy array of audio samples.

        Returns:
            The transcribed text.

        """
        # Faster-whisper handles numpy arrays directly (float32, 16kHz)

        segments, _info = self.model.transcribe(
            audio_input,
            beam_size=5,
            language=self.language,
            condition_on_previous_text=False,  # recommended for real-time/short clips
        )

        # Consolidate segments
        return " ".join([segment.text for segment in segments]).strip()
