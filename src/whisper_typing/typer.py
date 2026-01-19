import threading
import time
import pyperclip
from typing import Optional, Callable
from pynput.keyboard import Controller, Key

class Typer:
    def __init__(self, wpm: int = 40):
        self.keyboard = Controller()
        self.wpm = wpm

    def type_text(self, text: str, stop_event: Optional[threading.Event] = None, check_focus: Optional[Callable[[], bool]] = None):
        """Simulate human-like typing into the active window."""
        if not text:
            return

        print(f"Typing (at ~{self.wpm} WPM): {text[:50]}...")
        try:
            # WPM = Characters Per Minute (assuming 5 chars per word)
            # 60 seconds / (WPM * 5) characters = seconds per character
            base_char_delay = 60.0 / (float(self.wpm) * 5.0) 
            
            import random
            
            for i, char in enumerate(text):
                # Check for cancellation
                if stop_event and stop_event.is_set():
                    print("Typing cancelled via stop event.")
                    return
                
                if check_focus and not check_focus():
                    print("Typing stopped: window focus lost.")
                    return

                self.keyboard.type(char)
                
                # Base delay with jitter (70% - 130% of base)
                delay = base_char_delay * random.uniform(0.7, 1.3)
                
                # Slower after punctuation
                if char in ".!?":
                    delay += random.uniform(0.3, 0.6)
                elif char in ",;:":
                    delay += random.uniform(0.1, 0.3)
                
                time.sleep(delay)
                
                # Extra random pauses for detection avoidance (every 15-30 chars)
                if i > 0 and i % random.randint(15, 30) == 0:
                    long_pause = random.uniform(0.2, 0.8)
                    time.sleep(long_pause)
                    
        except Exception as e:
            print(f"Error during simulated typing: {e}")
            # Emergency fallback removed to respect cancellation/focus rules
