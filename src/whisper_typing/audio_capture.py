import queue
import threading

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

    def stop(self) -> np.ndarray:
        """Stop recording and return audio data as numpy array (float32)."""
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
            
        # Concatenate and flatten to 1D array for mono
        recording = np.concatenate(data, axis=0)
        if self.channels == 1:
            recording = recording.flatten()
            
        print(f"Recording stopped. Captured {len(recording)} samples.")
        return recording
