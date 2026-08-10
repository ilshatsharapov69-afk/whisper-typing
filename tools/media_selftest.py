"""Acceptance check for the media pause/resume subsystem.

Run it with a video playing (and, ideally, a second video deliberately paused
by hand). It performs exactly what a recording does — pause, hold, resume —
and prints what each channel actually did, so a regression is visible without
guessing from _app.log.

    .venv\\Scripts\\python.exe -X utf8 tools\\media_selftest.py

It clicks real browser controls, so run it on purpose, not by habit.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from whisper_typing.app_controller import MediaController  # noqa: E402
from whisper_typing.browser_media_bridge import BrowserMediaBridge  # noqa: E402

HOLD_S = 4.0
STATUS_NAMES = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


def log(message: str) -> None:
    """Print a timestamped line."""
    print(f"{time.strftime('%H:%M:%S')}  {message}")  # noqa: T201


def smtc_snapshot() -> list[str]:
    """List every Windows media session and its playback status."""

    async def collect() -> list[str]:
        from winrt.windows.media.control import (  # noqa: PLC0415
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
        )

        manager = await Mgr.request_async()
        rows = []
        for session in manager.get_sessions():
            try:
                status = session.get_playback_info().playback_status
                app = session.source_app_user_model_id
            except Exception as exc:  # noqa: BLE001
                rows.append(f"    <unreadable session: {exc}>")
                continue
            rows.append(f"    {app} -> {STATUS_NAMES.get(status, status)}")
        return rows

    try:
        return asyncio.run(collect())
    except Exception as exc:  # noqa: BLE001
        return [f"    <SMTC unavailable: {exc}>"]


def main() -> int:
    """Run one pause/resume cycle and report both channels."""
    bridge = BrowserMediaBridge(logger=log, debug=True)
    controller = MediaController(logger=log, browser_bridge=bridge)

    log("starting the PowerShell helper...")
    started = time.monotonic()
    if not bridge.start():
        log("FAIL: helper did not start")
        return 1
    log(f"helper ready in {time.monotonic() - started:.2f}s")
    if not bridge.ping():
        log("FAIL: helper does not answer ping")
        return 1

    log("media sessions BEFORE:")
    for row in smtc_snapshot():
        log(row)

    started = time.monotonic()
    paused = controller.pause_if_playing()
    log(f"pause_if_playing() -> {paused} in {time.monotonic() - started:.2f}s")
    log("media sessions WHILE PAUSED:")
    for row in smtc_snapshot():
        log(row)

    log(f"holding for {HOLD_S:.0f}s — nothing should start playing by itself")
    time.sleep(HOLD_S)
    log("media sessions AFTER THE HOLD (must be identical to the previous block):")
    for row in smtc_snapshot():
        log(row)

    started = time.monotonic()
    controller.resume()
    log(f"resume() finished in {time.monotonic() - started:.2f}s")
    time.sleep(1.0)
    log("media sessions AFTER RESUME (must match the BEFORE block):")
    for row in smtc_snapshot():
        log(row)

    controller.stop()
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
