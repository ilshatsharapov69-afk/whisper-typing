"""Tests for exact, state-aware Windows media control."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

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
    playing.get_playback_info.side_effect = [
        MagicMock(playback_status=4),
        MagicMock(playback_status=5),
        MagicMock(playback_status=5),
    ]

    paused = asyncio.run(controller._async_pause_all())  # noqa: SLF001
    resumed = asyncio.run(controller._async_resume_sessions(paused))  # noqa: SLF001

    assert paused == [playing]
    assert resumed == 1
    playing.try_play_async.assert_awaited_once()
    already_paused.try_play_async.assert_not_awaited()


def test_unavailable_smtc_never_sends_an_unverified_play_command() -> None:
    """Test that a broken SMTC service leaves paused media unchanged."""
    messages: list[str] = []
    controller = MediaController(logger=messages.append)
    controller._async_pause_all = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        side_effect=OSError("service unavailable")
    )

    assert controller.pause_if_playing() is False
    controller.resume()

    assert any("state left unchanged" in message for message in messages)


def test_nonplaying_session_is_never_marked_for_resume() -> None:
    """Test that a failed pause does not create a resume lease."""
    session = _session(4, pause_result=False)
    controller = MediaController()
    controller._get_sessions = AsyncMock(return_value=[session])  # type: ignore[method-assign]  # noqa: SLF001

    paused = asyncio.run(controller._async_pause_all())  # noqa: SLF001

    assert paused == []


def test_accepted_but_unconfirmed_pause_is_never_resumed() -> None:
    """Test that request acceptance alone cannot create a PLAY lease."""
    session = _session(4)
    controller = MediaController()
    controller._STATE_CONFIRM_ATTEMPTS = 2  # noqa: SLF001
    controller._STATE_CONFIRM_DELAY_S = 0  # noqa: SLF001
    controller._get_sessions = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        return_value=[session]
    )

    paused = asyncio.run(controller._async_pause_all())  # noqa: SLF001
    resumed = asyncio.run(controller._async_resume_sessions(paused))  # noqa: SLF001

    assert paused == []
    assert resumed == 0
    session.try_pause_async.assert_awaited_once()
    session.try_play_async.assert_not_awaited()
    assert session.get_playback_info.call_args_list == [call(), call(), call()]


def test_resume_never_restarts_a_session_that_is_no_longer_paused() -> None:
    """Test that stopped or closed media cannot be restarted on key release."""
    session = _session(3)
    controller = MediaController()

    resumed = asyncio.run(controller._async_resume_sessions([session]))  # noqa: SLF001

    assert resumed == 0
    session.try_play_async.assert_not_awaited()
