"""Main entry point for whisper-typing."""

import argparse

from dotenv import load_dotenv

from whisper_typing.app_controller import WhisperAppController
from whisper_typing.tui.app import WhisperTui


def main() -> None:
    """Run the whisper-typing application."""
    parser = argparse.ArgumentParser(
        description="Whisper Typing - Background Speech to Text"
    )
    parser.add_argument("--hotkey", help="Global hotkey to toggle recording")
    parser.add_argument("--type-hotkey", help="Global hotkey to type")
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
