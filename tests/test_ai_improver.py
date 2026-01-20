"""Tests for ai_improver module."""

from unittest.mock import MagicMock, patch

from google.api_core import exceptions

from whisper_typing.ai_improver import AIImprover


@patch("google.genai.Client")
def test_initialization(mock_client_cls: MagicMock) -> None:
    """Test AIImprover initialization."""
    improver = AIImprover(api_key="fake-key")
    mock_client_cls.assert_called_with(api_key="fake-key")
    assert improver.client is not None


def test_initialization_no_key() -> None:
    """Test initialization without API key disables client."""
    improver = AIImprover(api_key="")
    assert improver.client is None


@patch("google.genai.Client")
def test_list_models(mock_client_cls: MagicMock) -> None:
    """Test listing models."""
    mock_client = mock_client_cls.return_value

    model1 = MagicMock()
    model1.name = "models/gemini-pro"
    model1.supported_actions = ["generateContent"]

    model2 = MagicMock()
    model2.name = "models/embedding-001"
    model2.supported_actions = ["embedContent"]  # Should filter out

    mock_client.models.list.return_value = [model1, model2]

    models = AIImprover.list_models(api_key="fake")
    assert "models/gemini-pro" in models
    assert "models/embedding-001" not in models


@patch("google.genai.Client")
def test_improve_text_success(mock_client_cls: MagicMock) -> None:
    """Test successful text improvement."""
    mock_client = mock_client_cls.return_value
    mock_response = MagicMock()
    mock_response.text = "Improved text"
    mock_client.models.generate_content.return_value = mock_response

    improver = AIImprover(api_key="fake")
    result = improver.improve_text("Bad text")

    assert result == "Improved text"
    mock_client.models.generate_content.assert_called()


def test_improve_text_no_client() -> None:
    """Test improve_text returns original text if no client."""
    improver = AIImprover(api_key="")
    assert improver.improve_text("Original") == "Original"


@patch("google.genai.Client")
def test_initialization_exception(mock_client_cls: MagicMock) -> None:
    """Test initialization handles client creation exception."""
    mock_client_cls.side_effect = Exception("API error")
    improver = AIImprover(api_key="fake-key")
    assert improver.client is None


def test_log_with_logger() -> None:
    """Test logging with a logger callback."""
    logged_messages = []
    improver = AIImprover(api_key="", logger=logged_messages.append)
    improver.log("Test message")
    assert "Test message" in logged_messages


@patch("google.genai.Client")
def test_list_models_exception(mock_client_cls: MagicMock) -> None:
    """Test list_models returns empty list on exception."""
    mock_client_cls.side_effect = Exception("API error")
    models = AIImprover.list_models(api_key="fake")
    assert models == []


@patch("google.genai.Client")
def test_improve_text_empty(mock_client_cls: MagicMock) -> None:  # noqa: ARG001
    """Test improve_text with empty string."""
    improver = AIImprover(api_key="fake")
    result = improver.improve_text("")
    assert result == ""


@patch("google.genai.Client")
def test_improve_text_debug_mode(mock_client_cls: MagicMock) -> None:
    """Test improve_text with debug logging enabled."""
    mock_client = mock_client_cls.return_value
    mock_response = MagicMock()
    mock_response.text = "Improved text"
    mock_client.models.generate_content.return_value = mock_response

    logged_messages = []
    improver = AIImprover(api_key="fake", debug=True, logger=logged_messages.append)
    result = improver.improve_text("Test")

    assert result == "Improved text"
    assert any("DEBUG" in msg for msg in logged_messages)


@patch("google.genai.Client")
def test_improve_text_custom_prompt(mock_client_cls: MagicMock) -> None:
    """Test improve_text with custom prompt template."""
    mock_client = mock_client_cls.return_value
    mock_response = MagicMock()
    mock_response.text = "Custom improved"
    mock_client.models.generate_content.return_value = mock_response

    improver = AIImprover(api_key="fake")
    result = improver.improve_text("Test", prompt_template="Fix this: {text}")

    assert result == "Custom improved"
    # Verify the custom prompt was used
    call_args = mock_client.models.generate_content.call_args
    assert "Fix this: Test" in str(call_args)


@patch("google.genai.Client")
def test_improve_text_resource_exhausted(mock_client_cls: MagicMock) -> None:
    """Test improve_text handles ResourceExhausted exception."""

    mock_client = mock_client_cls.return_value
    mock_client.models.generate_content.side_effect = exceptions.ResourceExhausted(
        "Quota exceeded"
    )

    logged_messages = []
    improver = AIImprover(api_key="fake", logger=logged_messages.append)
    result = improver.improve_text("Test")

    assert result == "Test"  # Returns original text
    assert any("quota" in msg.lower() for msg in logged_messages)


@patch("google.genai.Client")
def test_improve_text_general_exception(mock_client_cls: MagicMock) -> None:
    """Test improve_text handles general exceptions."""
    mock_client = mock_client_cls.return_value
    mock_client.models.generate_content.side_effect = Exception("Network error")

    logged_messages = []
    improver = AIImprover(api_key="fake", logger=logged_messages.append)
    result = improver.improve_text("Test")

    assert result == "Test"  # Returns original text
    assert any("Error during AI improvement" in msg for msg in logged_messages)
