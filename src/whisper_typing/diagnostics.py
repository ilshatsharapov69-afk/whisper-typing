"""Diagnostics: file logging, audio backups, persistent history.

Decoupled from the TUI so failures remain visible (and recoverable) even
when the TUI window is hidden (whisper-typing-silent.vbs case).
"""

from __future__ import annotations

import html
import json
import logging
import logging.handlers
import os
import re
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
HISTORY_HTML_PATH: Path = APP_DIR / "_history.html"

# Keep last N audio backups on disk
AUDIO_BACKUP_KEEP: int = 100
# Keep last N transcription entries
HISTORY_KEEP: int = 1000

_LEGACY_TRANSCRIPTION_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[INFO\] Transcribed: (.+)$"
)


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

        # Older releases only kept ten entries in memory and fifty on disk,
        # while the rotating log retained many successful transcriptions.
        # Import those once (deduplicated) so the new History view can recover
        # text the user thought was gone.
        if self._merge_legacy_log_entries():
            self._save()

    def _merge_legacy_log_entries(self) -> bool:
        """Recover successful transcriptions from rotating legacy logs."""
        existing = {
            (entry.get("timestamp", ""), entry.get("text", ""))
            for entry in self._entries
        }
        recovered: list[dict[str, str]] = []
        log_paths = sorted(APP_DIR.glob("_app.log*"), key=lambda path: path.name)
        for path in log_paths:
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        match = _LEGACY_TRANSCRIPTION_RE.match(line.rstrip("\r\n"))
                        if not match:
                            continue
                        key = (match.group(1), match.group(2))
                        if key in existing:
                            continue
                        existing.add(key)
                        recovered.append(
                            {
                                "timestamp": key[0],
                                "text": key[1],
                                "status": "ok",
                            }
                        )
            except OSError as exc:
                get_logger().warning(
                    "history log recovery failed for %s: %s", path, exc
                )

        if not recovered:
            return False
        self._entries.extend(recovered)
        self._entries.sort(key=lambda entry: entry.get("timestamp", ""))
        self._entries = self._entries[-HISTORY_KEEP:]
        get_logger().info(
            "Recovered %s transcription(s) from legacy logs.", len(recovered)
        )
        return True

    def _save(self) -> None:
        try:
            # Atomic write: a process kill mid-save must never leave a
            # truncated history.json behind.
            tmp = HISTORY_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._entries, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
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

    def entries(self, n: int | None = None) -> list[dict[str, str]]:
        """Return a defensive copy of raw entries, newest first."""
        with self._lock:
            source = self._entries if n is None else self._entries[-n:]
            return [entry.copy() for entry in reversed(source)]

    def export_html(self, path: Path | None = None) -> Path:
        """Write a searchable, copy-friendly local history report."""
        if path is None:
            path = HISTORY_HTML_PATH
        cards: list[str] = []
        for index, entry in enumerate(self.entries(), 1):
            timestamp = html.escape(entry.get("timestamp", ""))
            status = entry.get("status", "ok")
            text = entry.get("text", "")
            error = entry.get("error", "")
            audio_path = entry.get("audio_path", "")
            badge = {"ok": "Saved", "empty": "No speech", "error": "Failed"}.get(
                status,
                status,
            )
            details = ""
            if error:
                details += f'<div class="error">{html.escape(error)}</div>'
            if audio_path:
                audio = Path(audio_path)
                if audio.exists():
                    audio_uri = html.escape(audio.resolve().as_uri(), quote=True)
                    details += (
                        '<audio controls preload="none" src="'
                        + audio_uri
                        + '"></audio>'
                    )
                else:
                    details += '<div class="missing">Audio backup expired</div>'
            cards.append(
                f'<article class="entry status-{html.escape(status)}">'
                f"<header><b>#{index}</b><time>{timestamp}</time>"
                f"<span>{html.escape(badge)}</span></header>"
                f"<textarea readonly>{html.escape(text)}</textarea>"
                '<div class="actions">'
                '<button class="copy-one">Copy text</button>'
                "</div>"
                f"{details}</article>"
            )

        empty_state = '<p class="empty-state">No transcriptions yet.</p>'
        body = "\n".join(cards) if cards else empty_state
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Whisper Typer History</title>
<style>
:root{{
  --bg:#10131a;--panel:#191e29;--text:#eef2ff;--muted:#9ca8bf;
  --accent:#70d6ff;--ok:#63d89c;--warn:#ffd166;--bad:#ff6b7a;
}}
*{{box-sizing:border-box}}
body{{
  margin:0;background:var(--bg);color:var(--text);
  font:15px/1.45 system-ui,sans-serif;
}}
main{{width:min(1100px,94vw);margin:32px auto 80px}}
h1{{margin:0 0 4px;font-size:28px}}
.sub{{color:var(--muted);margin:0 0 22px}}
.toolbar{{
  position:sticky;top:0;z-index:2;display:flex;gap:10px;padding:12px 0;
  background:linear-gradient(var(--bg) 75%,transparent);
}}
input{{flex:1;min-width:140px}}
input,button{{
  border:1px solid #35405a;border-radius:9px;background:#202738;
  color:var(--text);padding:10px 12px;
}}
button{{cursor:pointer}}
button:hover{{border-color:var(--accent)}}
.entry{{
  margin:14px 0;padding:16px;border:1px solid #2d374d;
  border-radius:14px;background:var(--panel);
}}
header{{display:flex;gap:12px;align-items:center;margin-bottom:10px}}
time{{color:var(--muted)}}
header span{{margin-left:auto;color:var(--ok)}}
.status-empty header span{{color:var(--warn)}}
.status-error header span,.error{{color:var(--bad)}}
textarea{{
  width:100%;min-height:92px;resize:vertical;border:0;border-radius:9px;
  background:#111620;color:var(--text);padding:12px;
  font:15px/1.45 system-ui,sans-serif;
}}
.actions{{margin-top:9px}}
audio{{width:100%;margin-top:10px}}
.missing,.empty-state{{color:var(--muted)}}
@media(max-width:600px){{
  main{{margin-top:18px}} .toolbar{{flex-wrap:wrap}} input{{flex-basis:100%}}
}}
</style></head><body><main><h1>Whisper Typer History</h1>
<p class="sub">Newest first · {len(cards)} saved entries · audio is kept
for the most recent recordings</p>
<div class="toolbar">
<input id="search" type="search" placeholder="Search transcriptions…">
<button id="copy-latest">Copy latest</button>
<button id="copy-all">Copy all</button>
</div>
<section id="entries">{body}</section></main>
<script>
async function copyText(text){{
  try{{await navigator.clipboard.writeText(text)}}catch(_e){{
    const t=document.createElement('textarea');t.value=text;
    document.body.appendChild(t);t.select();document.execCommand('copy');t.remove();
  }}
}}
document.querySelectorAll('.copy-one').forEach(b=>b.onclick=()=>
  copyText(b.closest('.entry').querySelector('textarea').value));
document.getElementById('copy-latest').onclick=()=>{{
  const t=document.querySelector('.entry textarea');if(t)copyText(t.value);
}};
document.getElementById('copy-all').onclick=()=>copyText(
  [...document.querySelectorAll('.entry textarea')]
    .map(t=>t.value).filter(Boolean).join('\n\n---\n\n'));
document.getElementById('search').oninput=e=>{{
  const q=e.target.value.toLowerCase();
  document.querySelectorAll('.entry').forEach(
    x=>x.hidden=!x.innerText.toLowerCase().includes(q));
}};
</script></body></html>"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(document, encoding="utf-8")
        tmp.replace(path)
        return path
