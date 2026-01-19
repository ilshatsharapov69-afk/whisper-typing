from pynput.keyboard import Controller, Key
import time

class Typer:
    def __init__(self):
        self.keyboard = Controller()

    def type_text(self, text: str):
        """Type text into active window."""
        if not text:
            return
            
        print(f"Typing: {text}")
        
        # Add a small buffer space before typing if needed, 
        # or just type straight away.
        # self.keyboard.type(' ') 
        
        for char in text:
            self.keyboard.type(char)
            time.sleep(0.005) # Tiny delay to look more natural/prevent buffer overflow
