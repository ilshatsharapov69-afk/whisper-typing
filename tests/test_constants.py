"""Tests for constants module."""

from whisper_typing.constants import WHISPER_NAME_MAP


def test_whisper_name_map() -> None:
    """Test that the whisper name map contains expected keys and values."""
    assert "openai/whisper-tiny" in WHISPER_NAME_MAP
    assert WHISPER_NAME_MAP["openai/whisper-tiny"] == "tiny"
    assert "openai/whisper-large-v3" in WHISPER_NAME_MAP
    assert WHISPER_NAME_MAP["openai/whisper-large-v3"] == "large-v3"
