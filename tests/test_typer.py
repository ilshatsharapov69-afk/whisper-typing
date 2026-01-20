"""Tests for typer module."""

import threading
from unittest.mock import MagicMock, call, patch

from whisper_typing.typer import Typer

DEFAULT_WPM = 40
FAST_WPM = 100
TEST_WPM = 60
PUNCTUATION_TEXT_LENGTH = 14
LONG_TEXT_LENGTH = 12


def test_typer_initialization() -> None:
    """Test Typer initialization with default and custom WPM."""
    typer = Typer()
    assert typer.wpm == DEFAULT_WPM

    typer_fast = Typer(wpm=FAST_WPM)
    assert typer_fast.wpm == FAST_WPM


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
def test_type_text_basic(mock_sleep: MagicMock, mock_controller_cls: MagicMock) -> None:
    """Test typing text calls the keyboard controller correctly."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard

    typer = Typer(wpm=TEST_WPM)
    text = "Hello"
    typer.type_text(text)

    assert mock_keyboard.type.call_count == len(text)
    mock_keyboard.type.assert_has_calls([call(char) for char in text])
    assert mock_sleep.called


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
def test_type_text_stop_event(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,
) -> None:
    """Test typing stops when stop_event is set."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard

    typer = Typer(wpm=TEST_WPM)
    stop_event = threading.Event()

    # Set stop event immediately
    stop_event.set()
    typer.type_text("Hello", stop_event=stop_event)

    mock_keyboard.type.assert_not_called()


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
def test_type_text_check_focus_failure(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,
) -> None:
    """Test typing stops when check_focus returns False."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard

    typer = Typer(wpm=TEST_WPM)

    # check_focus simply returns False
    typer.type_text("Hello", check_focus=lambda: False)

    mock_keyboard.type.assert_not_called()


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
def test_type_text_empty(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,  # noqa: ARG001
) -> None:
    """Test typing empty text does nothing."""
    typer = Typer(wpm=TEST_WPM)
    typer.type_text("")
    # Should return early without errors


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
@patch("random.uniform")
def test_type_text_with_punctuation(
    mock_uniform: MagicMock,
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,
) -> None:
    """Test typing text with punctuation adds delays."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard
    mock_uniform.return_value = 0.1

    typer = Typer(wpm=TEST_WPM)
    typer.type_text("Hi. Yes, okay!")

    # Verify typing occurred
    assert mock_keyboard.type.call_count == PUNCTUATION_TEXT_LENGTH


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
def test_type_text_exception_handling(
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,
) -> None:
    """Test typing handles exceptions gracefully."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard
    mock_keyboard.type.side_effect = Exception("Keyboard error")

    typer = Typer(wpm=TEST_WPM)
    # Should not raise exception
    typer.type_text("Hello")


@patch("whisper_typing.typer.Controller")
@patch("time.sleep")
@patch("random.randint")
@patch("random.uniform")
def test_type_text_pause_intervals(
    mock_uniform: MagicMock,
    mock_randint: MagicMock,
    mock_sleep: MagicMock,  # noqa: ARG001
    mock_controller_cls: MagicMock,
) -> None:
    """Test typing adds random pauses at intervals."""
    mock_keyboard = MagicMock()
    mock_controller_cls.return_value = mock_keyboard
    mock_uniform.return_value = 0.01
    mock_randint.return_value = 5  # Pause every 5 characters

    typer = Typer(wpm=TEST_WPM)
    # Type more than 5 characters to trigger pause
    typer.type_text("Hello World!")

    # Verify typing occurred
    assert mock_keyboard.type.call_count == LONG_TEXT_LENGTH
