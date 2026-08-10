"""Tests for the persistent Chromium media helper client."""

from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from whisper_typing import browser_media_bridge
from whisper_typing.browser_media_bridge import BrowserMediaBridge


@pytest.fixture(autouse=True)
def _never_spawn_the_real_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard the developer's own Chrome: the real helper clicks live windows."""

    def refuse(*_args: object, **_kwargs: object) -> None:
        msg = "tests must never start the real media helper"
        raise AssertionError(msg)

    monkeypatch.setattr(browser_media_bridge.subprocess, "Popen", refuse)


def _started_bridge(
    logger: Callable[[str], None] | None = None,
    *,
    debug: bool = False,
) -> tuple[BrowserMediaBridge, MagicMock]:
    """Return a bridge wired to a fake, already-running helper process."""
    bridge = BrowserMediaBridge(logger=logger, debug=debug)
    process = MagicMock()
    process.poll.return_value = None
    bridge._process = process  # noqa: SLF001
    return bridge, process


def test_the_helper_script_is_saved_as_utf8_with_a_bom() -> None:
    """Test PowerShell 5.1 cannot silently misread the helper as ANSI.

    Without the BOM it decodes the file in the system codepage: the Russian
    button names become mojibake, so a Russian Chrome never matches, and a
    UTF-8 dash decodes to a curly quote that PowerShell accepts as a string
    delimiter, which breaks the whole script at parse time.
    """
    script = Path(browser_media_bridge.__file__).with_name("browser_media_bridge.ps1")
    raw = script.read_bytes()

    assert raw.startswith(b"\xef\xbb\xbf")
    assert "приостановить" in raw.decode("utf-8-sig")


def test_a_late_response_from_a_previous_command_is_never_reused() -> None:
    """Test a timed-out pause cannot make the next command report its count."""
    bridge, _ = _started_bridge()
    bridge._next_id = 6  # noqa: SLF001
    bridge._responses.put({"ok": True, "id": 6, "paused": 3})  # stale  # noqa: SLF001
    bridge._responses.put({"ok": True, "id": 7, "paused": 1})  # noqa: SLF001

    assert bridge.pause_playing() == 1


def test_a_command_timeout_keeps_the_helper_and_its_leases_alive() -> None:
    """Test a slow pause no longer destroys the record of what to resume."""
    messages: list[str] = []
    bridge, process = _started_bridge(logger=messages.append)
    bridge._COMMAND_TIMEOUT_S = 0.01  # noqa: SLF001

    assert bridge.pause_playing() == 0

    assert bridge._process is process  # noqa: SLF001
    process.kill.assert_not_called()
    assert any("timed out" in message for message in messages)


def test_a_hung_helper_is_killed_hard_so_no_orphan_survives() -> None:
    """Test a PowerShell host stuck inside UI Automation is force-killed."""
    bridge, process = _started_bridge()
    process.poll.return_value = None  # ignores kill(), as a wedged host does

    with patch(
        "whisper_typing.browser_media_bridge.subprocess.run"
    ) as run:
        bridge._discard_process()  # noqa: SLF001

    process.kill.assert_called_once_with()
    assert run.call_args.args[0][:3] == ["taskkill", "/F", "/T"]
    assert bridge._process is None  # noqa: SLF001


def test_helper_diagnostics_reach_the_log_in_debug_mode() -> None:
    """Test the helper's own explanation of a failure is no longer discarded."""
    messages: list[str] = []
    bridge, _ = _started_bridge(logger=messages.append, debug=True)
    bridge._next_id = 0  # noqa: SLF001
    bridge._responses.put(  # noqa: SLF001
        {"ok": True, "id": 1, "resumed": 0, "leased": 1, "logs": ["lease vanished"]}
    )

    assert bridge.resume_paused() == (0, 1)
    assert any("lease vanished" in message for message in messages)


def test_a_repeated_failure_is_logged_again_after_the_quiet_window() -> None:
    """Test a permanently broken helper cannot go silent for the whole session."""
    messages: list[str] = []
    bridge, _ = _started_bridge(logger=messages.append)
    bridge._COMMAND_TIMEOUT_S = 0.01  # noqa: SLF001

    bridge.pause_playing()
    bridge.pause_playing()
    assert len(messages) == 1

    with patch("whisper_typing.browser_media_bridge.time.monotonic", return_value=1e6):
        bridge.pause_playing()

    expected_reports = 2
    assert len(messages) == expected_reports
