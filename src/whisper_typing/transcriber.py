import torch
import numpy as np
from faster_whisper import WhisperModel
from .constants import WHISPER_NAME_MAP

class Transcriber:
    def __init__(self, model_id="openai/whisper-base", language=None, device="cpu", compute_type="auto"):
        self.model_name = WHISPER_NAME_MAP.get(model_id, model_id)
        self.language = language
        
        # Validate device
        if device.startswith("cuda") and not torch.cuda.is_available():
            print("Warning: CUDA requested but not available. Falling back to CPU.")
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
            
        print(f"Loading faster-whisper model '{self.model_name}' on {self.device} with {self.compute_type}...")
        
        self.model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type
        )

    def transcribe(self, audio_input: "str | np.ndarray") -> str:
        """Transcribe audio input (file path or numpy array) to text."""
        # Faster-whisper handles numpy arrays directly (float32, 16kHz)
        
        segments, info = self.model.transcribe(
            audio_input,
            beam_size=5,
            language=self.language,
            condition_on_previous_text=False # recommended for real-time/short clips
        )
        
        # Consolidate segments
        text = " ".join([segment.text for segment in segments]).strip()
        return text
