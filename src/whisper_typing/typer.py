"""Human-like typing simulation."""

import random
import threading
import time
from collections.abc import Callable

from pynput.keyboard import Controller


class Typer:
    """Simulates realistic human typing behavior."""

    # Typing behavior constants
    CHARS_PER_WORD: float = 5.0
    SECONDS_PER_MINUTE: float = 60.0

    # Jitter and pause constants
    JITTER_MIN: float = 0.7
    JITTER_MAX: float = 1.3

    PUNCTUATION_PAUSE_MIN: float = 0.3
    PUNCTUATION_PAUSE_MAX: float = 0.6

    MINOR_PAUSE_MIN: float = 0.1
    MINOR_PAUSE_MAX: float = 0.3

    LONG_PAUSE_MIN: float = 0.2
    LONG_PAUSE_MAX: float = 0.8

    PAUSE_INTERVAL_MIN: int = 15
    PAUSE_INTERVAL_MAX: int = 30

    def __init__(self, wpm: int = 40) -> None:
        """Initialize the Typer with a specific words per minute.

        Args:
            wpm: Targeted typing speed in words per minute.

        """
        self.keyboard = Controller()
        self.wpm = wpm

    def type_text(
        self,
        text: str,
        stop_event: threading.Event | None = None,
        check_focus: Callable[[], bool] | None = None,
    ) -> None:
        """Simulate human-like typing into the active window.

        Args:
            text: The text to type.
            stop_event: Optional event to stop typing midway.
            check_focus: Optional callback to check if window still has focus.

        """
        if not text:
            return

        try:
            # WPM = Characters Per Minute (assuming 5 chars per word)
            # 60 seconds / (WPM * 5) characters = seconds per character
            base_char_delay = self.SECONDS_PER_MINUTE / (
                float(self.wpm) * self.CHARS_PER_WORD
            )

            for i, char in enumerate(text):
                # Check for cancellation
                if stop_event and stop_event.is_set():
                    return

                if check_focus and not check_focus():
                    return

                self.keyboard.type(char)

                delay = base_char_delay * random.uniform(  # noqa: S311
                    self.JITTER_MIN, self.JITTER_MAX
                )

                # Slower after punctuation
                if char in ".!?":
                    delay += random.uniform(  # noqa: S311
                        self.PUNCTUATION_PAUSE_MIN, self.PUNCTUATION_PAUSE_MAX
                    )
                elif char in ",;:":
                    delay += random.uniform(self.MINOR_PAUSE_MIN, self.MINOR_PAUSE_MAX)  # noqa: S311

                time.sleep(delay)

                # Extra random pauses for detection avoidance (every 15-30 chars)
                pause_interval = random.randint(  # noqa: S311
                    self.PAUSE_INTERVAL_MIN, self.PAUSE_INTERVAL_MAX
                )
                if i > 0 and i % pause_interval == 0:
                    long_pause = random.uniform(  # noqa: S311
                        self.LONG_PAUSE_MIN, self.LONG_PAUSE_MAX
                    )
                    time.sleep(long_pause)

        except Exception:  # noqa: BLE001, S110
            # Emergency fallback removed to respect cancellation/focus rules
            pass
