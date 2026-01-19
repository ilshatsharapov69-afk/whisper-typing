import torch
import numpy as np
import os
os.environ["TRANSFORMERS_VERBOSITY"] = "error" #stop warning or informational messages
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1" #stop warning or informational messages
from transformers import pipeline

class Transcriber:
    def __init__(self, model_id="openai/whisper-base", language=None, device="cpu"):
        self.model_id = model_id
        self.language = language
        
        # Validate device
        if device.startswith("cuda") and not torch.cuda.is_available():
            print("Warning: CUDA requested but not available. Falling back to CPU.")
            device = "cpu"
            
        torch_dtype = torch.float16 if device.startswith("cuda") else torch.float32
        
        print(f"Loading model {model_id} on {device} with {torch_dtype}...")
        
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model=model_id,
            dtype=torch_dtype,
            device=device,
        )

    def transcribe(self, audio_input: "str | np.ndarray") -> str:
        """Transcribe audio input (file path or numpy array) to text."""
        input_type = "buffer" if issubclass(type(audio_input), (np.ndarray,)) else str(audio_input)
        print(f"Transcribing {input_type}...")
        
        generate_kwargs = {}
        if self.language:
            generate_kwargs["language"] = self.language

        result = self.pipe(
            audio_input,
            chunk_length_s=30,
            batch_size=8, # increased batch size for better GPU utilization
            generate_kwargs=generate_kwargs,
            return_timestamps=True,
            ignore_warning=True
        )
        
        text = result["text"].strip()
        return text
