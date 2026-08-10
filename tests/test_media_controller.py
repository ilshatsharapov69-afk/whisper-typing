"""Tests for exact, state-aware Windows media control."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

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


def test_browser_fallback_pauses_and_resumes_an_exact_verified_lease() -> None:
    """Test Chromium fallback participates when Windows exposes no session."""
    bridge = MagicMock()
    bridge.pause_playing.return_value = 1
    bridge.resume_paused.return_value = (1, 1)
    controller = MediaController(browser_bridge=bridge)
    controller._async_pause_all = AsyncMock(return_value=[])  # type: ignore[method-assign]  # noqa: SLF001

    assert controller.pause_if_playing() is True
    controller.resume()

    bridge.pause_playing.assert_called_once_with()
    bridge.resume_paused.assert_called_once_with()


def test_browser_fallback_never_creates_a_lease_for_prepaused_media() -> None:
    """Test a browser video already showing Play stays paused on resume."""
    bridge = MagicMock()
    bridge.pause_playing.return_value = 0
    bridge.resume_paused.return_value = (0, 0)
    controller = MediaController(browser_bridge=bridge)
    controller._async_pause_all = AsyncMock(return_value=[])  # type: ignore[method-assign]  # noqa: SLF001

    assert controller.pause_if_playing() is False
    controller.resume()

    bridge.resume_paused.assert_called_once_with()


def test_a_carried_lease_is_never_played_just_to_be_paused_again() -> None:
    """Test a new take does not restart media left paused by a failed take."""
    stranded = _session(5)
    controller = MediaController()
    controller._paused_sessions = [stranded]  # noqa: SLF001
    controller._get_sessions = AsyncMock(return_value=[])  # type: ignore[method-assign]  # noqa: SLF001

    assert controller.pause_if_playing() is True

    stranded.try_play_async.assert_not_awaited()
    assert controller._paused_sessions == [stranded]  # noqa: SLF001


def test_a_carried_lease_restarted_by_the_user_is_paused_again() -> None:
    """Test media the user resumed by hand is re-paused, not silently dropped."""
    restarted = _session(4)
    controller = MediaController()
    controller._get_sessions = AsyncMock(return_value=[restarted])  # type: ignore[method-assign]  # noqa: SLF001
    restarted.get_playback_info.side_effect = [
        MagicMock(playback_status=4),  # carried check: playing again
        MagicMock(playback_status=4),  # fresh scan: playing
        MagicMock(playback_status=5),  # pause confirmed
    ]

    paused = asyncio.run(controller._async_pause_all([restarted]))  # noqa: SLF001

    assert paused == [restarted]
    restarted.try_pause_async.assert_awaited_once()


def test_an_smtc_failure_does_not_forget_media_it_already_paused() -> None:
    """Test a broken SMTC scan keeps the lease instead of stranding the video."""
    stranded = _session(5)
    controller = MediaController()
    controller._paused_sessions = [stranded]  # noqa: SLF001
    controller._async_pause_all = AsyncMock(  # type: ignore[method-assign]  # noqa: SLF001
        side_effect=OSError("service unavailable")
    )

    controller.pause_if_playing()

    assert controller._paused_sessions == [stranded]  # noqa: SLF001


def test_browser_fallback_waits_for_chromium_after_an_smtc_pause() -> None:
    """Test the fallback never reads an accessibility name SMTC just invalidated."""
    bridge = MagicMock()
    bridge.pause_playing.return_value = 0
    controller = MediaController(browser_bridge=bridge)
    controller._async_pause_all = AsyncMock(return_value=[_session(5)])  # type: ignore[method-assign]  # noqa: SLF001

    with patch("whisper_typing.app_controller.time.sleep") as sleep:
        controller.pause_if_playing()

    sleep.assert_called_once_with(MediaController._BROWSER_SETTLE_S)  # noqa: SLF001


def test_browser_fallback_is_not_delayed_when_smtc_paused_nothing() -> None:
    """Test the settle delay is only paid when it can actually prevent a race."""
    bridge = MagicMock()
    bridge.pause_playing.return_value = 1
    controller = MediaController(browser_bridge=bridge)
    controller._async_pause_all = AsyncMock(return_value=[])  # type: ignore[method-assign]  # noqa: SLF001

    with patch("whisper_typing.app_controller.time.sleep") as sleep:
        assert controller.pause_if_playing() is True

    sleep.assert_not_called()
