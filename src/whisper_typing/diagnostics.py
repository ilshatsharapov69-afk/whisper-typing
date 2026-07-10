"""Diagnostics: file logging, audio backups, persistent history.

Decoupled from the TUI so failures remain visible (and recoverable) even
when the TUI window is hidden (whisper-typing-silent.vbs case).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import threading
import time
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


APP_DIR: Path = Path(__file__).resolve().parents[2]
LOG_PATH: Path = APP_DIR / "_app.log"
AUDIO_BACKUP_DIR: Path = APP_DIR / "_audio_backup"
HISTORY_PATH: Path = APP_DIR / "history.json"

# Keep last N audio backups on disk
AUDIO_BACKUP_KEEP: int = 30
# Keep last N transcription entries
HISTORY_KEEP: int = 50


_logger: logging.Logger | None = None


def get_logger() -> logging.Logger:
    """Return a rotating file logger. Idempotent."""
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("whisper_typing")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            LOG_PATH,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    _logger = logger
    return logger


def save_audio_backup(audio: np.ndarray, sample_rate: int = 16000) -> Path | None:
    """Persist raw audio to a WAV file so the user can recover it later.

    Returns the path written, or None on failure. Best-effort: never raises.
    """
    try:
        import numpy as np

        AUDIO_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).astimezone().strftime("%Y-%m-%d_%H-%M-%S")
        # Include ms to avoid collisions on rapid re-records
        ms = int((time.time() % 1) * 1000)
        path = AUDIO_BACKUP_DIR / f"{ts}_{ms:03d}.wav"

        # Convert float32 [-1, 1] → int16 PCM
        if audio.dtype != np.int16:
            clipped = np.clip(audio, -1.0, 1.0)
            pcm = (clipped * 32767.0).astype(np.int16)
        else:
            pcm = audio

        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())

        _prune_audio_backups()
        return path
    except Exception as e:  # noqa: BLE001
        get_logger().warning("audio backup failed: %s", e)
        return None


def _prune_audio_backups() -> None:
    """Keep only the most recent AUDIO_BACKUP_KEEP backups."""
    try:
        files = sorted(
            AUDIO_BACKUP_DIR.glob("*.wav"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in files[AUDIO_BACKUP_KEEP:]:
            old.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001, S110
        pass


class PersistentHistory:
    """Append-only history of transcriptions, persisted to disk.

    Each entry: {timestamp, text, status, audio_path, error}
    status: "ok" | "empty" | "error"
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict[str, str]] = []
        self._load()

    def _load(self) -> None:
        try:
            if HISTORY_PATH.exists():
                with HISTORY_PATH.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._entries = data[-HISTORY_KEEP:]
        except Exception as e:  # noqa: BLE001
            get_logger().warning("history load failed: %s", e)
            self._entries = []
            # Preserve the unreadable file for manual recovery instead of
            # silently overwriting it on the next save.
            try:
                HISTORY_PATH.replace(HISTORY_PATH.with_suffix(".json.corrupt"))
            except Exception:  # noqa: BLE001, S110
                pass

    def _save(self) -> None:
        try:
            # Atomic write: a process kill mid-save must never leave a
            # truncated history.json behind.
            tmp = HISTORY_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=2)
            tmp.replace(HISTORY_PATH)
        except Exception as e:  # noqa: BLE001
            get_logger().warning("history save failed: %s", e)

    def add(
        self,
        text: str,
        status: str = "ok",
        audio_path: str | None = None,
        error: str | None = None,
    ) -> None:
        ts = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        entry: dict[str, str] = {
            "timestamp": ts,
            "text": text,
            "status": status,
        }
        if audio_path:
            entry["audio_path"] = audio_path
        if error:
            entry["error"] = error
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > HISTORY_KEEP:
                self._entries = self._entries[-HISTORY_KEEP:]
            self._save()

    def recent(self, n: int = 10) -> list[tuple[str, str]]:
        """Return last n entries as (timestamp, displayable_text) — newest first.

        For backward compat with the existing TUI HistoryScreen which expects
        (timestamp, text) tuples.
        """
        with self._lock:
            tail = list(reversed(self._entries[-n:]))
        out: list[tuple[str, str]] = []
        for e in tail:
            ts = e.get("timestamp", "")
            status = e.get("status", "ok")
            text = e.get("text", "") or ""
            if status == "error":
                err = e.get("error", "unknown error")
                wav = e.get("audio_path", "")
                marker = f"[FAILED: {err}]"
                if wav:
                    marker += f" wav: {wav}"
                display = f"{marker}\n{text}" if text else marker
            elif status == "empty":
                wav = e.get("audio_path", "")
                marker = "[NO SPEECH DETECTED]"
                if wav:
                    marker += f" wav: {wav}"
                display = marker
            else:
                display = text
            out.append((ts, display))
        return out
