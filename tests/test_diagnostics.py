"""Tests for persistent diagnostics and history recovery."""

from pathlib import Path

import pytest

from whisper_typing import diagnostics
from whisper_typing.diagnostics import PersistentHistory


def test_history_recovers_transcriptions_from_rotating_logs(tmp_path: Path) -> None:
    """Test migration of entries that old history retention discarded."""
    legacy_log = tmp_path / "_app.log.1"
    legacy_log.write_text(
        "2026-07-31 10:00:00 [INFO] Recording started...\n"
        "2026-07-31 10:00:05 [INFO] Transcribed: Восстановленный текст\n",
        encoding="utf-8",
    )

    history = PersistentHistory()

    assert history.entries() == [
        {
            "timestamp": "2026-07-31 10:00:05",
            "text": "Восстановленный текст",
            "status": "ok",
        }
    ]
    assert diagnostics.HISTORY_PATH.exists()


def test_history_log_recovery_is_deduplicated(tmp_path: Path) -> None:
    """Test that restarting does not duplicate migrated log entries."""
    (tmp_path / "_app.log").write_text(
        "2026-07-31 10:00:05 [INFO] Transcribed: Один текст\n",
        encoding="utf-8",
    )

    PersistentHistory()
    reloaded = PersistentHistory()

    assert len(reloaded.entries()) == 1


def test_history_exports_searchable_escaped_html(tmp_path: Path) -> None:
    """Test local report content, escaping, copy controls, and audio link."""
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF")
    history = PersistentHistory()
    history.add('<script>alert("x")</script>', audio_path=str(audio))

    report = history.export_html()
    content = report.read_text(encoding="utf-8")

    assert report == diagnostics.HISTORY_HTML_PATH
    assert "&lt;script&gt;" in content
    assert '<script>alert("x")</script>' not in content
    assert audio.resolve().as_uri() in content
    assert 'id="search"' in content
    assert "Copy latest" in content
    assert not report.with_suffix(report.suffix + ".tmp").exists()


def test_history_retention_keeps_newest_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that expanded retention still prunes deterministically."""
    monkeypatch.setattr(diagnostics, "HISTORY_KEEP", 3)
    history = PersistentHistory()
    for text in ("one", "two", "three", "four"):
        history.add(text)

    assert [entry[1] for entry in history.recent(10)] == ["four", "three", "two"]
