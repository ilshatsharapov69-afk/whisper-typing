import queue
import tempfile
import threading
import wave
from datetime import datetime

import numpy as np
import sounddevice as sd


class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.recording = False
        self.frames = queue.Queue()
        self.thread = None

    def _callback(self, indata, frames, time, status):
        """Callback for sounddevice."""
        if status:
            print(f"Status: {status}")
        self.frames.put(indata.copy())

    def _record(self):
        """Internal recording loop."""
        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            callback=self._callback
        ):
            while self.recording:
                sd.sleep(100)

    def start(self):
        """Start recording."""
        if self.recording:
            return
        
        self.recording = True
        self.frames = queue.Queue() # Clear queue
        self.thread = threading.Thread(target=self._record)
        self.thread.start()
        print("Recording started...")

    def stop(self) -> str:
        """Stop recording and save to a temporary WAV file. Returns file path."""
        if not self.recording:
            return None

        self.recording = False
        self.thread.join()
        
        # Collect all frames
        data = []
        while not self.frames.empty():
            data.append(self.frames.get())
        
        if not data:
            return None
            
        recording = np.concatenate(data, axis=0)
        
        # Save to temp file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_filename = tempfile.mktemp(prefix=f"whisper_audio_{timestamp}_", suffix=".wav")
        
        with wave.open(temp_filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(self.sample_rate)
            # Convert float32 to int16
            audio_int16 = (recording * 32767).astype(np.int16)
            wf.writeframes(audio_int16.tobytes())
            
        print(f"Recording stopped. Saved to {temp_filename}")
        return temp_filename
