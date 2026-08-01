"""Tests for transcriber module."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np

# Pre-mock faster_whisper to prevent heavy import chain (ctranslate2 → torch)
_mock_fw = MagicMock()
sys.modules.setdefault("faster_whisper", _mock_fw)

from whisper_typing.transcriber import Transcriber  # noqa: E402

DUMMY_AUDIO_SIZE = 10


def _loud_audio(size: int = DUMMY_AUDIO_SIZE) -> np.ndarray:
    """Create a non-silent dummy audio array that passes silence detection."""
    return np.full(size, 0.5, dtype=np.float32)


def _make_transcriber(**kwargs: object) -> Transcriber:
    """Create a Transcriber with mocked WhisperModel."""
    with patch.object(_mock_fw, "WhisperModel") as mock_model:
        t = Transcriber(**kwargs)
        t._mock_model_cls = mock_model  # noqa: SLF001
    return t


def test_transcriber_initialization_cpu() -> None:
    """Test Transcriber initialization on CPU."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        transcriber = Transcriber(device="cpu", compute_type="int8")

    assert transcriber.device == "cpu"
    assert transcriber.compute_type == "int8"
    mock_wm.assert_called_once()


def test_transcriber_initialization_cuda_auto() -> None:
    """Test Transcriber initialization on CUDA with auto compute type."""
    with patch.object(_mock_fw, "WhisperModel"):
        transcriber = Transcriber(device="cuda", compute_type="auto")

    assert transcriber.device == "cuda"
    assert transcriber.compute_type == "float16"


def test_transcribe_success() -> None:
    """Test successful transcription."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Hello world"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Hello world"


def test_transcribe_multiple_segments() -> None:
    """Test transcription with multiple segments."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        seg1 = MagicMock()
        seg1.text = "Hello"
        seg2 = MagicMock()
        seg2.text = "world"
        mock_instance.transcribe.return_value = ([seg1, seg2], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Hello world"


def test_transcriber_cuda_fallback_to_cpu() -> None:
    """Test Transcriber falls back to CPU when CUDA model load fails."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        # First call (cuda) raises, second call (cpu) succeeds
        mock_wm.side_effect = [RuntimeError("CUDA not available"), MagicMock()]
        transcriber = Transcriber(device="cuda", compute_type="float16")

    assert transcriber.device == "cpu"


def test_transcriber_download_root() -> None:
    """Test Transcriber passes download_root to WhisperModel."""
    test_root = "/custom/path/to/models"
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        Transcriber(download_root=test_root)
        _, kwargs = mock_wm.call_args
        assert kwargs["download_root"] == test_root


def test_transcriber_lazy_loading() -> None:
    """Test lazy loading defers model creation until first use."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        transcriber = Transcriber(lazy=True)

        # Model should not be loaded yet
        mock_wm.assert_not_called()
        assert transcriber.model is None

        # First transcribe triggers load
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "test"
        mock_instance.transcribe.return_value = ([segment], None)

        result = transcriber.transcribe(_loud_audio())

    assert result == "test"
    assert transcriber.model is not None


def test_transcribe_fast() -> None:
    """Test fast transcription uses beam_size=1."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "fast text"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe_fast(_loud_audio())

    assert result == "fast text"
    _, kwargs = mock_instance.transcribe.call_args
    assert kwargs["beam_size"] == 1


def test_transcribe_silent_audio_returns_empty() -> None:
    """Test that silent audio returns empty string without calling model."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        transcriber = Transcriber()
        result = transcriber.transcribe(np.zeros(DUMMY_AUDIO_SIZE, dtype=np.float32))

    assert result == ""
    mock_instance.transcribe.assert_not_called()


def test_transcribe_filters_hallucination_thank_you() -> None:
    """Test that 'thank you' hallucination is filtered out."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Thank you."
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == ""


def test_transcribe_filters_repetition() -> None:
    """Test that repetitive text like 'you you you you' is filtered."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "you you you you"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == ""


def test_transcribe_allows_legitimate_text() -> None:
    """Test that legitimate text containing 'thank' is not filtered."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Thank you for the information about the project"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Thank you for the information about the project"


def test_transcribe_strips_hallucinated_outro_from_valid_text() -> None:
    """Test that a known outro suffix does not spoil a long transcription."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Это нормальная длинная диктовка. Продолжение следует..."
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Это нормальная длинная диктовка."


def test_transcribe_strips_variable_subtitle_credit_suffix() -> None:
    """Test that variable subtitle-credit hallucinations are removed."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Полезный текст. Субтитры сделал DimaTorzok"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Полезный текст."


def test_transcribe_keeps_outro_words_in_the_middle() -> None:
    """Test that only a final hallucinated suffix is removed."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "Фраза «продолжение следует» иногда появляется, и это проблема."
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        result = transcriber.transcribe(_loud_audio())

    assert result == "Фраза «продолжение следует» иногда появляется, и это проблема."


def test_transcribe_vad_filter_enabled() -> None:
    """Test that VAD filter is passed to model.transcribe."""
    with patch.object(_mock_fw, "WhisperModel") as mock_wm:
        mock_instance = mock_wm.return_value
        segment = MagicMock()
        segment.text = "test"
        mock_instance.transcribe.return_value = ([segment], None)

        transcriber = Transcriber()
        transcriber.transcribe(_loud_audio())

    _, kwargs = mock_instance.transcribe.call_args
    assert kwargs["vad_filter"] is True
