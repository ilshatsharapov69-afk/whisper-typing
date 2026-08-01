"""Main entry point for whisper-typing."""

import argparse
import sys

from dotenv import load_dotenv

from whisper_typing.app_controller import WhisperAppController
from whisper_typing.diagnostics import get_logger
from whisper_typing.tui.app import WhisperTui

# Kept alive for the process lifetime so the single-instance mutex isn't released.
_INSTANCE_MUTEX: int | None = None


def _acquire_single_instance() -> bool:
    """Return True if this is the only running instance.

    Uses a Windows named mutex, which the OS auto-releases when the process
    exits — so it never goes stale the way a lock file can after a crash.
    Returns False if another instance already holds it.
    """
    if sys.platform != "win32":
        return True

    import ctypes

    global _INSTANCE_MUTEX
    kernel32 = ctypes.windll.kernel32
    error_already_exists = 183
    # Never CloseHandle'd — the mutex lives until this process exits.
    _INSTANCE_MUTEX = kernel32.CreateMutexW(None, False, "WhisperTyping_SingleInstance")
    return kernel32.GetLastError() != error_already_exists


def main() -> None:
    """Run the whisper-typing application."""
    if not _acquire_single_instance():
        get_logger().warning(
            "Another whisper-typing instance is already running — exiting."
        )
        return

    parser = argparse.ArgumentParser(
        description="Whisper Typing - Background Speech to Text"
    )
    parser.add_argument("--hotkey", help="Global hotkey to toggle recording")
    parser.add_argument("--improve-hotkey", help="Global hotkey to improve text")
    parser.add_argument("--model", help="Whisper model ID")
    parser.add_argument("--language", help="Language code")
    parser.add_argument("--api-key", help="Gemini API Key")
    args = parser.parse_args()

    load_dotenv(override=True)

    # Initialize Controller
    controller = WhisperAppController()
    controller.load_configuration(args)

    # Start TUI
    # The TUI will handle component initialization and starting the listener
    app = WhisperTui(controller)
    app.run()


if __name__ == "__main__":
    main()
