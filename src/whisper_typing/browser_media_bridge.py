"""Background browser/Picture-in-Picture media control for Windows."""

from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class BrowserMediaBridge:
    """Talk to the persistent PowerShell UI Automation media helper.

    Chrome does not always publish YouTube or Picture-in-Picture playback to
    Windows SMTC. The helper identifies visible browser pause buttons, clicks
    them through background window messages, verifies the state change, and
    remembers only controls it actually paused so pre-paused videos stay put.
    """

    _START_TIMEOUT_S = 5.0
    _COMMAND_TIMEOUT_S = 3.0
    _CREATE_NO_WINDOW = 0x08000000

    def __init__(self, logger: Callable[[str], None] | None = None) -> None:
        """Create a lazy, thread-safe bridge."""
        self._log = logger or (lambda _: None)
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._last_error: str | None = None

    def pause_playing(self) -> int:
        """Pause browser media that is currently playing and return its count."""
        response = self._request("pause")
        return int(response.get("paused", 0)) if response else 0

    def start(self) -> bool:
        """Warm up the hidden helper so the first recording pauses promptly."""
        with self._lock:
            return self._ensure_started()

    def resume_paused(self) -> tuple[int, int]:
        """Resume only the media paused by this helper.

        Returns:
            A ``(resumed, leased)`` pair.

        """
        response = self._request("resume")
        if not response:
            return (0, 0)
        return (int(response.get("resumed", 0)), int(response.get("leased", 0)))

    def stop(self) -> None:
        """Restore leased media and stop the helper process."""
        with self._lock:
            process = self._process
            if process is None:
                return
            try:
                if process.poll() is None and process.stdin:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                    process.wait(timeout=2.0)
            except Exception:  # noqa: BLE001, S110
                pass
            finally:
                self._discard_process()

    def _request(self, command: str) -> dict[str, Any] | None:
        """Send one serialized helper command and return its JSON response."""
        with self._lock:
            if not self._ensure_started():
                return None
            process = self._process
            try:
                if process is None or process.stdin is None:
                    msg = "browser media helper has no input pipe"
                    raise RuntimeError(msg)  # noqa: TRY301
                process.stdin.write(command + "\n")
                process.stdin.flush()
                response = self._responses.get(timeout=self._COMMAND_TIMEOUT_S)
                if response.get("ok", False):
                    self._last_error = None
                    return response
                msg = str(response.get("error", "unknown helper error"))
                raise RuntimeError(msg)  # noqa: TRY301
            except Exception as exc:  # noqa: BLE001
                self._report_error(exc)
                self._discard_process()
                return None

    def _ensure_started(self) -> bool:
        """Start the hidden persistent helper and wait for its ready message."""
        if self._process is not None and self._process.poll() is None:
            return True
        self._discard_process()
        script = Path(__file__).with_name("browser_media_bridge.ps1")
        try:
            executable = shutil.which("powershell.exe")
            if executable is None:
                msg = "powershell.exe was not found"
                raise FileNotFoundError(msg)  # noqa: TRY301
            self._process = subprocess.Popen(  # noqa: S603
                [
                    executable,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=self._CREATE_NO_WINDOW,
            )
            stdout = self._process.stdout
            if stdout is None:
                msg = "browser media helper has no output pipe"
                raise RuntimeError(msg)  # noqa: TRY301
            threading.Thread(
                target=self._read_responses,
                args=(stdout,),
                name="browser-media-reader",
                daemon=True,
            ).start()
            ready = self._responses.get(timeout=self._START_TIMEOUT_S)
            if ready.get("ready") is not True:
                msg = str(ready.get("error", "helper did not become ready"))
                raise RuntimeError(msg)  # noqa: TRY301
            self._last_error = None
            return True  # noqa: TRY300
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)
            self._discard_process()
            return False

    def _read_responses(self, stdout: Any) -> None:  # noqa: ANN401
        """Decode newline-delimited JSON emitted by the helper."""
        for line in stdout:
            try:
                decoded = json.loads(line)
                if isinstance(decoded, dict):
                    self._responses.put(decoded)
            except (json.JSONDecodeError, TypeError):
                continue

    def _report_error(self, exc: Exception) -> None:
        """Log a changed failure once so recording itself remains unaffected."""
        message = f"{type(exc).__name__}: {exc}"
        if message != self._last_error:
            self._log(f"Browser media fallback unavailable ({message}).")
            self._last_error = message

    def _discard_process(self) -> None:
        """Close local pipes and terminate an unusable helper."""
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=1.0)
            except Exception:  # noqa: BLE001, S110
                pass
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                break
