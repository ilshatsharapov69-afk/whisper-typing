"""Background browser/Picture-in-Picture media control for Windows."""

from __future__ import annotations

import contextlib
import json
import queue
import shutil
import subprocess
import threading
import time
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

    Every command carries an id. A slow response is dropped by id instead of
    killing the helper: the helper process *is* the lease store, so tearing it
    down on a timeout used to leave the user's video paused with nothing left
    that knew how to restart it.
    """

    # Loading UIAutomation plus compiling the inline C# costs ~0.7 s on a warm
    # machine and several seconds on a loaded one.
    _START_TIMEOUT_S = 20.0
    # A pause pass clicks and verifies every player it finds (~1.5 s each).
    _COMMAND_TIMEOUT_S = 10.0
    _PING_TIMEOUT_S = 5.0
    _ERROR_REPEAT_S = 300.0
    _CREATE_NO_WINDOW = 0x08000000

    def __init__(
        self,
        logger: Callable[[str], None] | None = None,
        *,
        debug: bool = False,
    ) -> None:
        """Create a lazy, thread-safe bridge."""
        self._log = logger or (lambda _: None)
        self._debug = debug
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | None = None
        self._responses: queue.Queue[dict[str, Any]] = queue.Queue()
        self._last_error: str | None = None
        self._last_error_at: float = 0.0
        self._next_id: int = 0

    def pause_playing(self) -> int:
        """Pause browser media that is currently playing and return its count."""
        response = self._request("pause")
        return int(response.get("paused", 0)) if response else 0

    def start(self) -> bool:
        """Warm up the hidden helper so the first recording pauses promptly."""
        with self._lock:
            return self._ensure_started()

    def ping(self) -> bool:
        """Check the helper is alive and answering (used by the watchdog)."""
        return self._request("ping", timeout=self._PING_TIMEOUT_S) is not None

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
                    self._next_id += 1
                    process.stdin.write(f"{self._next_id} stop\n")
                    process.stdin.flush()
                    process.wait(timeout=5.0)
            except Exception:  # noqa: BLE001, S110
                pass
            finally:
                self._discard_process()

    def _request(
        self,
        command: str,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Send one serialized helper command and return its JSON response."""
        deadline_s = timeout if timeout is not None else self._COMMAND_TIMEOUT_S
        with self._lock:
            if not self._ensure_started():
                return None
            process = self._process
            self._next_id += 1
            request_id = self._next_id
            try:
                if process is None or process.stdin is None:
                    msg = "browser media helper has no input pipe"
                    raise RuntimeError(msg)  # noqa: TRY301
                process.stdin.write(f"{request_id} {command}\n")
                process.stdin.flush()
            except Exception as exc:  # noqa: BLE001
                self._report_error(f"{command} write failed", exc)
                self._discard_process()
                return None

            response = self._await_response(request_id, deadline_s)
            if response is None:
                # Deliberately keep the helper alive: it still owns the leases,
                # and a late response is discarded by id on the next command.
                self._report_error(
                    f"{command} timed out after {deadline_s:.0f}s",
                    TimeoutError(command),
                )
                if process.poll() is not None:
                    self._discard_process()
                return None
            if not response.get("ok", False):
                self._report_error(
                    command,
                    RuntimeError(str(response.get("error", "unknown helper error"))),
                )
                return None
            self._last_error = None
            return response

    def _await_response(
        self,
        request_id: int,
        timeout_s: float,
    ) -> dict[str, Any] | None:
        """Wait for the response matching ``request_id``, dropping stale ones."""
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                response = self._responses.get(timeout=remaining)
            except queue.Empty:
                return None
            self._drain_helper_logs(response)
            if int(response.get("id", 0)) == request_id:
                return response

    def _drain_helper_logs(self, response: dict[str, Any]) -> None:
        """Surface the helper's own diagnostics; they used to be discarded."""
        if not self._debug:
            return
        entries = response.get("logs") or []
        if isinstance(entries, str):
            entries = [entries]
        for entry in entries:
            self._log(f"[media helper] {entry}")

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
                stderr=subprocess.PIPE,
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
            if self._process.stderr is not None:
                threading.Thread(
                    target=self._read_errors,
                    args=(self._process.stderr,),
                    name="browser-media-stderr",
                    daemon=True,
                ).start()
            ready = self._responses.get(timeout=self._START_TIMEOUT_S)
            if ready.get("ready") is not True:
                msg = str(ready.get("error", "helper did not become ready"))
                raise RuntimeError(msg)  # noqa: TRY301
            self._last_error = None
            return True  # noqa: TRY300
        except Exception as exc:  # noqa: BLE001
            self._report_error("startup", exc)
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

    def _read_errors(self, stderr: Any) -> None:  # noqa: ANN401
        """Forward helper stderr instead of discarding the real failure cause."""
        for line in stderr:
            text = line.strip()
            if text:
                self._log(f"[media helper stderr] {text}")

    def _report_error(self, stage: str, exc: Exception) -> None:
        """Log a failure without spamming, but never silence it forever."""
        message = f"{stage}: {type(exc).__name__}: {exc}"
        now = time.monotonic()
        quiet_window = now - self._last_error_at < self._ERROR_REPEAT_S
        repeated_recently = message == self._last_error and quiet_window
        if not repeated_recently:
            self._log(f"Browser media fallback unavailable ({message}).")
            self._last_error = message
            self._last_error_at = now

    def _discard_process(self) -> None:
        """Close local pipes and hard-kill an unusable helper (no orphans)."""
        process = self._process
        self._process = None
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2.0)
            except Exception:  # noqa: BLE001, S110
                pass
            if process.poll() is None:
                # A PowerShell host stuck inside a UI Automation call can
                # outlive kill(); orphans then keep clicking nothing forever.
                with contextlib.suppress(Exception):
                    subprocess.run(  # noqa: S603
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],  # noqa: S607
                        check=False,
                        capture_output=True,
                        creationflags=self._CREATE_NO_WINDOW,
                        timeout=5.0,
                    )
        while True:
            try:
                self._responses.get_nowait()
            except queue.Empty:
                break
