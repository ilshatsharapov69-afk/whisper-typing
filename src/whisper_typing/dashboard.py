"""Local control panel for whisper-typing.

Serves a small web UI on 127.0.0.1 that reads and writes the live app: the
processing animation, the recording visualizer, the toggles and the history.
It runs inside the app process, so a change applies immediately instead of
waiting for a restart.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.parse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, Any

from whisper_typing.overlay import ASSETS, GRADIENTS, PROCESSING_ASSET, STYLES

if TYPE_CHECKING:
    from pathlib import Path

    from whisper_typing.app_controller import WhisperAppController

LOADERS_DIR = ASSETS / "loaders"
UI_DIR = ASSETS / "dashboard"
DEFAULT_PORT = 8770
PORT_ATTEMPTS = 12
ANIMATION_PX = 96
CREATE_NO_WINDOW = 0x08000000

GROUP_LABELS = {
    "bazed": "Base.apk",
    "markaryan": "Маркарян",
    "emotes": "Мемы",
    "parrots": "Party Parrot",
}
MEDIA_TYPES = {
    ".webm": "video/webm",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".png": "image/png",
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
}
TOGGLE_KEYS = {"auto_type", "auto_format", "pause_media", "debug", "refocus_window"}
CHOICE_KEYS = {"record_mode", "visualizer_style", "visualizer_gradient"}


def list_loaders() -> list[dict[str, str]]:
    """List every bundled loader as {id, group, name, kind}."""
    items: list[dict[str, str]] = []
    if not LOADERS_DIR.is_dir():
        return items
    for group_dir in sorted(LOADERS_DIR.iterdir()):
        if not group_dir.is_dir():
            continue
        for path in sorted(group_dir.iterdir(), key=lambda p: p.name.lower()):
            if path.suffix.lower() not in {".webm", ".webp", ".gif", ".png"}:
                continue
            items.append({
                "id": f"{group_dir.name}/{path.name}",
                "group": group_dir.name,
                "name": path.stem,
                "kind": "video" if path.suffix.lower() == ".webm" else "image",
            })
    return items


def install_loader(loader_id: str) -> str:
    """Make one bundled loader the live processing animation.

    Everything is normalised to an animated PNG so the overlay only ever has
    one file to read; a copy is the fallback when ffmpeg is unavailable.
    """
    source = _safe_loader_path(loader_id)
    if source is None:
        msg = f"unknown loader {loader_id!r}"
        raise ValueError(msg)
    try:
        subprocess.run(  # noqa: S603
            [  # noqa: S607
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-vf", f"scale={ANIMATION_PX}:{ANIMATION_PX}:flags=lanczos:"
                       "force_original_aspect_ratio=decrease",
                "-plays", "0", "-f", "apng", str(PROCESSING_ASSET),
            ],
            check=True,
            capture_output=True,
            timeout=120,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        # PIL sniffs the real format from the bytes, so the extension may lie.
        shutil.copyfile(source, PROCESSING_ASSET)
    return loader_id


def _safe_loader_path(loader_id: str) -> Path | None:
    """Resolve a loader id, refusing anything outside the loaders folder."""
    candidate = (LOADERS_DIR / loader_id).resolve()
    root = LOADERS_DIR.resolve()
    if root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


class DashboardServer:
    """Serve the control panel for a running controller."""

    def __init__(
        self,
        controller: WhisperAppController,
        port: int = DEFAULT_PORT,
    ) -> None:
        """Bind the panel to one controller instance."""
        self._controller = controller
        self._wanted_port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    @property
    def url(self) -> str:
        """Return the panel address."""
        return f"http://127.0.0.1:{self.port or self._wanted_port}/"

    def start(self) -> str:
        """Start the panel, choosing a free port. Never raises."""
        if self._server is not None:
            return self.url
        handler = partial(_Handler, self._controller)
        for offset in range(PORT_ATTEMPTS):
            port = self._wanted_port + offset
            try:
                # 127.0.0.1 only: this API can change settings, so it must not
                # be reachable from the network.
                self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
            except OSError:
                continue
            self.port = port
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="dashboard",
                daemon=True,
            )
            self._thread.start()
            return self.url
        return self.url

    def stop(self) -> None:
        """Shut the panel down."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


class _Handler(BaseHTTPRequestHandler):
    """Route the panel's requests. Read/write only the local app."""

    protocol_version = "HTTP/1.1"

    def __init__(self, controller: WhisperAppController, *args: Any, **kw: Any) -> None:  # noqa: ANN401
        self.controller = controller
        super().__init__(*args, **kw)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        """Silence the default stderr access log."""

    # ── responses ────────────────────────────────────────────────────────
    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:  # noqa: ANN401
        self._send(
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json; charset=utf-8",
            status,
        )

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        self._send(
            path.read_bytes(),
            MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        )

    # ── routes ───────────────────────────────────────────────────────────
    def do_GET(self) -> None:
        """Serve the UI, the API reads and the loader files."""
        route = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(route.path)
        if path in {"/", "/index.html"}:
            self._file(UI_DIR / "index.html")
        elif path == "/api/state":
            self._json(self._state())
        elif path == "/api/loaders":
            self._json({"loaders": list_loaders(), "groups": GROUP_LABELS})
        elif path == "/api/history":
            limit = int(urllib.parse.parse_qs(route.query).get("n", ["100"])[0])
            self._json({"entries": self._history(limit)})
        elif path.startswith("/loaders/"):
            resolved = _safe_loader_path(path[len("/loaders/"):])
            if resolved:
                self._file(resolved)
            else:
                self._json({"error": "not found"}, 404)
        elif path == "/current.png":
            self._file(PROCESSING_ASSET)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        """Apply a settings change or a new loader."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "bad json"}, 400)
            return
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/config":
            self._json(self._set_config(body))
        elif path == "/api/loader":
            self._json(self._set_loader(str(body.get("id", ""))))
        elif path == "/api/action":
            self._json(self._run_action(str(body.get("action", ""))))
        else:
            self._json({"error": "not found"}, 404)

    # ── behaviour ────────────────────────────────────────────────────────
    def _state(self) -> dict[str, Any]:
        config = self.controller.config
        return {
            "config": {
                key: config.get(key)
                for key in (
                    *TOGGLE_KEYS, *CHOICE_KEYS, "hotkey", "model",
                    "language", "microphone_name", "device", "loader",
                )
            },
            "styles": STYLES,
            "gradients": list(GRADIENTS),
            "paused": self.controller.paused,
            "history_count": len(self.controller.transcription_history),
        }

    def _history(self, limit: int) -> list[dict[str, Any]]:
        entries = self.controller.persistent_history.entries()[-limit:]
        return [
            {
                "timestamp": entry.get("timestamp", ""),
                "text": entry.get("text", ""),
                "status": entry.get("status", "ok"),
            }
            for entry in reversed(entries)
        ]

    def _set_config(self, body: dict[str, Any]) -> dict[str, Any]:
        key, value = str(body.get("key", "")), body.get("value")
        if key not in TOGGLE_KEYS | CHOICE_KEYS:
            return {"error": f"key {key!r} is not editable"}
        self.controller.apply_setting(key, value)
        return {"ok": True, "key": key, "value": value}

    def _set_loader(self, loader_id: str) -> dict[str, Any]:
        try:
            install_loader(loader_id)
        except ValueError as exc:
            return {"error": str(exc)}
        self.controller.apply_setting("loader", loader_id)
        self.controller.overlay.reload_processing_animation()
        return {"ok": True, "id": loader_id}

    def _run_action(self, action: str) -> dict[str, Any]:
        if action == "history_report":
            self.controller.open_history()
        elif action == "pause":
            self.controller.toggle_pause()
        elif action == "preview":
            self.controller.overlay.reload_processing_animation()
            self.controller.overlay.show_processing()
        elif action == "preview_stop":
            self.controller.overlay.hide()
        else:
            return {"error": f"unknown action {action!r}"}
        return {"ok": True, "action": action}
