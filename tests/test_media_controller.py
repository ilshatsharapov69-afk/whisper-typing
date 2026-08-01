"""Tests for exact and fallback Windows media control."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from whisper_typing.app_controller import MediaController


def _session(status: int, *, pause_result: bool = True) -> MagicMock:
    """Create a mocked SMTC session."""
    session = MagicMock()
    session.get_playback_info.return_value.playback_status = status
    session.try_pause_async = AsyncMock(return_value=pause_result)
    session.try_play_async = AsyncMock(return_value=True)
    return session


def test_pause_tracks_exact_playing_session_objects() -> None:
    """Test that duplicate application IDs cannot resume an untouched tab."""
    playing = _session(4)
    already_paused = _session(5)
    playing.source_app_user_model_id = "chrome.exe"
    already_paused.source_app_user_model_id = "chrome.exe"
    controller = MediaController()
    controller._get_sessions = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        return_value=[playing, already_paused]
    )

    paused = asyncio.run(controller._async_pause_all())  # noqa: SLF001
    resumed = asyncio.run(controller._async_resume_sessions(paused))  # noqa: SLF001

    assert paused == [playing]
    assert resumed == 1
    playing.try_play_async.assert_awaited_once()
    already_paused.try_play_async.assert_not_awaited()


def test_pause_uses_pip_fallback_when_smtc_is_unavailable() -> None:
    """Test that Picture-in-Picture pause survives a broken SMTC service."""
    messages: list[str] = []
    controller = MediaController(logger=messages.append)
    controller._async_pause_all = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        side_effect=OSError("service unavailable")
    )
    controller._send_picture_in_picture_command = MagicMock(  # type: ignore[method-assign]  # noqa: SLF001
        return_value=[123]
    )
    controller._send_global_command = MagicMock(  # type: ignore[method-assign]  # noqa: SLF001
        return_value=None
    )

    assert controller.pause_if_playing() is True
    assert controller._pip_windows == [123]  # noqa: SLF001
    assert any("using fallback" in message for message in messages)


def test_nonplaying_session_is_never_marked_for_resume() -> None:
    """Test that a failed pause does not create a resume lease."""
    session = _session(4, pause_result=False)
    controller = MediaController()
    controller._get_sessions = AsyncMock(return_value=[session])  # type: ignore[method-assign]  # noqa: SLF001

    paused = asyncio.run(controller._async_pause_all())  # noqa: SLF001

    assert paused == []
