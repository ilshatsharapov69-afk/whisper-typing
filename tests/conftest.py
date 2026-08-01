"""Shared test fixtures."""

import logging

import pytest

from whisper_typing import diagnostics


@pytest.fixture(autouse=True)
def _isolate_diagnostics(tmp_path, monkeypatch):  # noqa: ANN001, ANN202
    """Keep tests away from the real _app.log / history.json / _audio_backup.

    Without this, controller tests write mock stack traces into the
    production log and could clobber the user's real transcription history.
    """
    monkeypatch.setattr(diagnostics, "HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(diagnostics, "HISTORY_HTML_PATH", tmp_path / "history.html")
    monkeypatch.setattr(diagnostics, "APP_DIR", tmp_path)
    monkeypatch.setattr(diagnostics, "AUDIO_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(diagnostics, "LOG_PATH", tmp_path / "app.log")
    monkeypatch.setattr(diagnostics, "_logger", None)
    logger = logging.getLogger("whisper_typing")
    saved_handlers = logger.handlers[:]
    logger.handlers = []
    yield
    logger.handlers = saved_handlers
