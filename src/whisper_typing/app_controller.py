"""Main application controller for whisper-typing."""

import asyncio
import ctypes
import json
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sounddevice as sd
from dotenv import find_dotenv
from pynput import keyboard

from whisper_typing.ai_improver import AIImprover
from whisper_typing.audio_capture import AudioRecorder
from whisper_typing.browser_media_bridge import BrowserMediaBridge
from whisper_typing.diagnostics import PersistentHistory, get_logger, save_audio_backup
from whisper_typing.overlay import AudioOverlay
from whisper_typing.transcriber import Transcriber
from whisper_typing.window_manager import WindowManager

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": "<f8>",
    "extra_hotkeys": [],
    "improve_hotkey": "<f10>",
    "model": "openai/whisper-base",
    "language": None,
    "gemini_prompt": None,
    "microphone_name": None,
    "gemini_model": None,
    "device": "cpu",
    "compute_type": "auto",
    "debug": False,
    "gemini_api_key": None,
    "refocus_window": True,
    "model_cache_dir": None,
    "pause_media": True,
    "auto_format": False,
    "visualizer_style": "bars",
    "visualizer_gradient": "green_red",
    "record_mode": "toggle",
    "auto_type": False,
    "format_prompt": (
        "You receive raw speech-to-text output. The speaker may switch between "
        "Russian and English freely, even mid-sentence. Your ONLY job:\n"
        "1. Remove filler words (uh, um, ну, типа, как бы, вот, это самое, короче, э)\n"
        "2. Remove accidental word repetitions (stutters)\n"
        "3. Fix punctuation and capitalization\n"
        "DO NOT rephrase, summarize, shorten, or change the meaning. "
        "Keep every meaningful word exactly as spoken. "
        "Output ONLY the cleaned text, nothing else."
    ),
}


def load_config(config_path: str = "config.json") -> dict[str, Any]:
    """Load configuration from JSON file.

    Args:
        config_path: Path to the configuration file.

    Returns:
        The loaded configuration dictionary.

    """
    path = Path(config_path)
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001, S110
            pass
    return {}


def save_config(config: dict[str, Any], config_path: str = "config.json") -> None:
    """Save configuration to JSON file, excluding sensitive data.

    Args:
        config: The configuration dictionary to save.
        config_path: Path to the configuration file.

    """
    try:
        # Create a copy and remove sensitive keys
        save_data = config.copy()
        save_data.pop("gemini_api_key", None)

        path = Path(config_path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:  # noqa: BLE001, S110
        pass


class MediaController:
    """Pause/resume media using Windows SMTC plus a Chromium UI fallback.

    Pauses EVERY playing session, not just the "current" one — with several
    media apps open (browser tabs + player) Windows often reports a session
    that is not the one actually audible, which made pausing look random.
    Resumes exactly the sessions whose transition to a non-playing state was
    verified. Every call is bounded by a timeout and never raises.
    """

    _TIMEOUT_S: float = 3.0
    _STATE_CONFIRM_ATTEMPTS: int = 5
    _STATE_CONFIRM_DELAY_S: float = 0.05
    _PLAYING_STATUS: int = 4
    _PAUSED_STATUS: int = 5

    def __init__(
        self,
        logger: "Callable[[str], None] | None" = None,
        browser_bridge: BrowserMediaBridge | None = None,
    ) -> None:
        """Create an empty, thread-safe media pause lease."""
        self._log = logger or (lambda _: None)
        # Keep the actual session objects: source_app_user_model_id is not
        # unique (multiple Chrome tabs share it), and resuming by id used to
        # start tabs that had already been paused before recording.
        self._paused_sessions: list[Any] = []
        self._lock = threading.RLock()
        self._last_smtc_error: str | None = None
        self._browser_bridge = browser_bridge

    def pause_if_playing(self) -> bool:
        """Pause all playing media sessions. Returns True if we paused any."""
        with self._lock:
            # A stale state can remain after a failed/aborted take. Restore it
            # before creating a new pause lease.
            if self._paused_sessions:
                self._resume_locked()

            try:
                self._paused_sessions = asyncio.run(
                    asyncio.wait_for(self._async_pause_all(), self._TIMEOUT_S)
                )
                self._last_smtc_error = None
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {exc}"
                if message != self._last_smtc_error:
                    self._log(
                        "Windows media sessions unavailable "
                        f"({message}); media state left unchanged."
                    )
                    self._last_smtc_error = message
                self._paused_sessions = []

            browser_paused = 0
            if self._browser_bridge:
                browser_paused = self._browser_bridge.pause_playing()

            paused = bool(self._paused_sessions or browser_paused)
            if paused:
                self._log(
                    "Media paused and verified "
                    f"(sessions={len(self._paused_sessions)}, "
                    f"browser={browser_paused})."
                )
            return paused

    def resume(self) -> None:
        """Resume the sessions we previously paused."""
        with self._lock:
            self._resume_locked()

    def _resume_locked(self) -> None:
        """Resume and clear the current pause lease while holding _lock."""
        sessions = self._paused_sessions
        self._paused_sessions = []

        resumed = 0
        if sessions:
            try:
                resumed = asyncio.run(
                    asyncio.wait_for(
                        self._async_resume_sessions(sessions),
                        self._TIMEOUT_S,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self._log(f"MediaController resume error: {exc}")
        browser_resumed, browser_leased = (0, 0)
        if self._browser_bridge:
            browser_resumed, browser_leased = self._browser_bridge.resume_paused()
        if sessions or browser_leased:
            self._log(
                "Media resumed "
                f"(sessions={resumed}/{len(sessions)}, "
                f"browser={browser_resumed}/{browser_leased})."
            )

    async def _get_sessions(self) -> list[Any]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
        )  # noqa: PLC0415

        manager = await Mgr.request_async()
        try:
            return list(manager.get_sessions())
        except Exception:  # noqa: BLE001
            # Fallback for older winrt projections without get_sessions
            session = manager.get_current_session()
            return [session] if session else []

    async def _async_pause_all(self) -> list[Any]:
        sessions = await self._get_sessions()
        paused: list[Any] = []
        for session in sessions:
            try:
                info = session.get_playback_info()
                if info.playback_status != self._PLAYING_STATUS:
                    continue
                requested = await session.try_pause_async()
                if requested and await self._wait_until_paused(session):
                    paused.append(session)
            except Exception:  # noqa: BLE001, S112
                continue
        return paused

    async def _wait_until_paused(self, session: Any) -> bool:  # noqa: ANN401
        """Confirm that a pause request produced the exact paused state."""
        for attempt in range(self._STATE_CONFIRM_ATTEMPTS):
            if session.get_playback_info().playback_status == self._PAUSED_STATUS:
                return True
            if attempt + 1 < self._STATE_CONFIRM_ATTEMPTS:
                await asyncio.sleep(self._STATE_CONFIRM_DELAY_S)
        return False

    async def _async_resume_sessions(self, sessions: list[Any]) -> int:
        """Resume the exact session objects paused by this controller."""
        resumed = 0
        for session in sessions:
            try:
                status = session.get_playback_info().playback_status
                if status == self._PAUSED_STATUS and await session.try_play_async():
                    resumed += 1
            except Exception:  # noqa: BLE001, S112
                continue
        return resumed

    def stop(self) -> None:
        """Restore media if the application exits during a recording."""
        self.resume()
        if self._browser_bridge:
            self._browser_bridge.stop()


class WhisperAppController:
    """Controller for Whisper Typing App logic.

    Decoupled from UI (CLI or TUI).
    """

    def __init__(self) -> None:
        """Initialize the WhisperAppController."""
        self.config: dict[str, Any] = {}
        self.recorder: AudioRecorder | None = None
        self.transcriber: Transcriber | None = None
        self.improver: AIImprover | None = None
        self.listener: keyboard.GlobalHotKeys | None = None
        self.window_manager: WindowManager = WindowManager()
        self.overlay: AudioOverlay = AudioOverlay()
        self.target_window_handle: Any | None = None

        self.is_processing: bool = False
        self._processing_start_time: float = 0.0
        self._processing_jobs: int = 0
        self._processing_lock = threading.Lock()
        self.pending_text: str | None = None
        self.paused: bool = False

        # History of transcriptions: persisted to history.json (survives
        # restarts, keeps failures + wav backup paths); in-memory view = last 10.
        self._persistent_history: PersistentHistory = PersistentHistory()
        self.transcription_history: list[tuple[str, str]] = (
            self._persistent_history.recent(50)
        )

        # State tracking for optimization
        self.current_model_id: str | None = None
        self.current_language: str | None = None
        self.current_mic_index: int | None = None
        self.current_device: str | None = None
        self.current_compute_type: str | None = None

        self.stop_live_transcribe: threading.Event = threading.Event()
        self.live_transcribe_thread: threading.Thread | None = None

        # Callbacks for UI updates
        self.on_status_change: Callable[[str], None] | None = None
        self.on_log: Callable[[str], None] | None = None
        self.on_preview_update: Callable[[str, str | None], None] | None = None

        # Hold-to-talk state. Recording runs while any registered push-to-talk
        # key is held (multi-key: e.g. CapsLock on the left + numpad Enter on
        # the right). Start on the first key down, stop on the last key up.
        self._hold_listener: keyboard.Listener | None = None
        self._hold_keys: set[Any] = set()  # pynput Key objects matched in the callbacks
        self._hold_caps: bool = (
            False  # CapsLock is a PTT key (needs OS-toggle suppression)
        )
        self._hold_numpad_enter: bool = (
            False  # numpad Enter is a PTT key (handled in the hook filter)
        )
        self._pressed_hold_keys: set[Any] = set()  # PTT keys currently held down
        # Serializes PTT start/stop: a quick re-press must wait for the
        # previous stop to finish, otherwise recorder.start() sees
        # recording=True and silently swallows the new take.
        self._ptt_lock: threading.Lock = threading.Lock()
        # Increments on every PTT start; a media-pause that completes after
        # its take already ended must not mark (or leave) media paused.
        self._ptt_gen: int = 0
        self._we_paused_media: bool = False
        self._media: MediaController | None = None
        # Self-healing keyboard-hook supervisor
        self._probe_seen: threading.Event = threading.Event()
        self._supervisor_stop: threading.Event = threading.Event()
        self._supervisor_thread: threading.Thread | None = None

    def log(self, message: str) -> None:
        """Log a message to the file log and the UI callback.

        The file log matters more than the TUI one: with
        whisper-typing-silent.vbs the TUI is invisible, so _app.log is the
        only place failures can actually be seen.

        Args:
            message: The message to log.

        """
        try:
            get_logger().info(message)
        except Exception:  # noqa: BLE001, S110
            pass
        if self.on_log:
            self.on_log(message)

    def _add_to_history(
        self,
        text: str,
        status: str = "ok",
        audio_path: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record a transcription (or failure) in history.json and refresh the in-memory view."""
        self._persistent_history.add(
            text, status=status, audio_path=audio_path, error=error
        )
        self.transcription_history = self._persistent_history.recent(50)

    def open_history(self) -> None:
        """Open the persistent history report from the tray menu."""
        try:
            report = self._persistent_history.export_html()
            os.startfile(report)  # noqa: S606
            self.log(
                f"History opened ({len(self._persistent_history.entries())} entries)."
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"Could not open history: {exc}")

    def _begin_processing(self) -> None:
        """Register one background transcription/AI job."""
        with self._processing_lock:
            self._processing_jobs += 1
            self.is_processing = True
            self._processing_start_time = time.time()

    def _finish_processing(self) -> None:
        """Finish one background job without hiding other active jobs."""
        with self._processing_lock:
            self._processing_jobs = max(0, self._processing_jobs - 1)
            self.is_processing = self._processing_jobs > 0

    def set_status(self, status: str) -> None:
        """Update the application status using the configured UI callback.

        Args:
            status: The new status string.

        """
        if self.on_status_change:
            self.on_status_change(status)

    def load_configuration(self, args: Any = None) -> None:  # noqa: ANN401
        """Load and merge configuration.

        Args:
            args: Optional command line arguments to override file config.

        """
        self.config = DEFAULT_CONFIG.copy()
        file_config = load_config()
        self.config.update(file_config)

        # Load from environment
        env_key = os.getenv("GEMINI_API_KEY")
        if env_key:
            self.config["gemini_api_key"] = env_key

        # Override with CLI args if provided
        if args:
            if args.hotkey:
                self.config["hotkey"] = args.hotkey
            if args.improve_hotkey:
                self.config["improve_hotkey"] = args.improve_hotkey
            if args.model:
                self.config["model"] = args.model
            if args.language:
                self.config["language"] = args.language
            if args.api_key:
                self.config["gemini_api_key"] = args.api_key

    def get_mic_index_from_config(self) -> int | None:
        """Find device index based on configured name.

        Returns:
            The device index if found, else None.

        """
        mic_name = self.config.get("microphone_name")
        if not mic_name:
            return None

        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            if dev["max_input_channels"] > 0 and mic_name in dev["name"]:
                return i
        return None

    def list_input_devices(self) -> list[tuple[int, str]]:
        """List available audio input devices.

        Returns:
            A list of tuples containing device index and name.

        """
        return AudioRecorder.list_devices()

    def update_config(self, new_config: dict[str, Any]) -> None:
        """Update runtime config and save to file.

        Args:
            new_config: Dictionary of configuration updates.

        """
        self.config.update(new_config)
        save_config(self.config)
        self.log("Configuration saved.")

    def update_env_api_key(self, api_key: str) -> None:
        """Update Gemini API Key in .env file.

        Args:
            api_key: The new Gemini API key.

        """
        try:
            env_file = find_dotenv() or ".env"
            path = Path(env_file).absolute()
            self.log(f"Saving API key to {path}")

            # Read existing lines
            lines = []
            if path.exists():
                with path.open("r", encoding="utf-8") as f:
                    lines = f.readlines()

            # Update or append
            key_found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith("GEMINI_API_KEY="):
                    new_lines.append(f"GEMINI_API_KEY={api_key}\n")
                    key_found = True
                else:
                    new_lines.append(line)

            if not key_found:
                if new_lines and not new_lines[-1].endswith("\n"):
                    new_lines[-1] += "\n"
                new_lines.append(f"GEMINI_API_KEY={api_key}\n")

            # Write back
            with path.open("w", encoding="utf-8") as f:
                f.writelines(new_lines)

            # Update current session environment variable and config
            os.environ["GEMINI_API_KEY"] = api_key
            self.config["gemini_api_key"] = api_key
            self.log(f"API Key successfully saved to {path.name}")
        except Exception as e:  # noqa: BLE001
            self.log(f"Error saving API key: {e}")

    def initialize_components(self) -> bool:
        """Initialize or re-initialize components.

        Returns:
            True if initialization was successful, False otherwise.

        """
        self.log("Initializing components...")

        # Microphone Setup
        mic_index = self.get_mic_index_from_config()
        # Note: If mic not found, we default to None (System Default)
        # instead of interactive prompt here. The UI should handle setup.
        self.current_mic_index = mic_index

        try:
            # Reload Optimization: Check if model/language changed
            if (
                not self.transcriber
                or self.current_model_id != self.config["model"]
                or self.current_language != self.config["language"]
                or self.current_device != self.config.get("device", "cpu")
                or self.current_compute_type != self.config.get("compute_type", "auto")
            ):
                self.log(f"Loading Transcriber ({self.config['model']})...")
                device = self.config.get("device", "cpu")
                compute_type = self.config.get("compute_type", "auto")
                self.transcriber = Transcriber(
                    model_id=self.config["model"],
                    language=self.config["language"],
                    device=device,
                    compute_type=compute_type,
                    download_root=self.config.get("model_cache_dir"),
                )
                self.current_model_id = self.config["model"]
                self.current_language = self.config["language"]
                self.current_device = device
                self.current_compute_type = compute_type

            # Stop old recorder before creating new one to avoid zombie threads
            if self.recorder and self.recorder.recording:
                self.recorder.stop()
            self.recorder = AudioRecorder(device_index=self.current_mic_index)
            self.improver = AIImprover(
                api_key=self.config.get("gemini_api_key"),
                model_name=self.config.get("gemini_model") or "gemini-1.5-flash",
                debug=self.config.get("debug", False),
                logger=self.log,
            )

            # Configure and start overlay (hidden until recording)
            self.overlay.set_style(self.config.get("visualizer_style", "bars"))
            self.overlay.set_gradient(
                self.config.get("visualizer_gradient", "green_red")
            )
            self.overlay.start()

            # Start persistent media controller for pause/resume
            if not self._media:
                browser_bridge = BrowserMediaBridge(logger=self.log)
                self._media = MediaController(
                    logger=self.log,
                    browser_bridge=browser_bridge,
                )
                threading.Thread(
                    target=browser_bridge.start,
                    name="browser-media-warmup",
                    daemon=True,
                ).start()

            self.log("Components initialized.")
        except Exception as e:  # noqa: BLE001
            self.log(f"Error initializing components: {e}")
            return False
        else:
            return True

    def start_listener(self) -> None:
        """Start the hotkey listener."""
        self._stop_keyboard_listener(self.listener)
        self._stop_keyboard_listener(self._hold_listener)
        self.listener = None
        self._hold_listener = None

        record_mode = self.config.get("record_mode", "toggle")

        try:
            if self._needs_record_key_listener():
                self._setup_hold_listener()
            if record_mode == "hold":
                self._start_global_hotkeys()
                hotkey_name = self.config["hotkey"]
                self.log(
                    f"Hold-to-talk mode. Hold {hotkey_name} to record, "
                    "release to transcribe+type."
                )
            else:
                self._start_global_hotkeys()
                self.log(
                    f"Toggle mode. Press {self.config['hotkey']} to start, "
                    "press again to stop."
                )
            self._start_supervisor()
            self.set_status("Ready")
        except ValueError as e:
            self.log(f"Invalid hotkey format: {e}")
            self.set_status("Hotkey Error")

    @staticmethod
    def _stop_keyboard_listener(
        listener: keyboard.Listener | keyboard.GlobalHotKeys | None,
    ) -> None:
        """Stop and join a pynput hook so no orphan hook keeps modifiers."""
        if listener is None:
            return
        try:
            listener.stop()
            if listener is not threading.current_thread():
                listener.join(timeout=1.0)
        except Exception:  # noqa: BLE001, S110
            pass

    def _start_global_hotkeys(self) -> None:
        """(Re)start the GlobalHotKeys listener for the current record_mode."""
        if self.listener:
            self._stop_keyboard_listener(self.listener)
        mapping = {self.config["improve_hotkey"]: self.on_improve_text}
        if (
            self.config.get("record_mode", "toggle") != "hold"
            and self.config["hotkey"] not in {"numpad_enter", "caps_lock"}
        ):
            mapping[self.config["hotkey"]] = self._queue_record_toggle
        self.listener = keyboard.GlobalHotKeys(mapping)
        self.listener.start()

    def _needs_record_key_listener(self) -> bool:
        """Return whether press/release-aware handling is required."""
        if self.config.get("record_mode", "toggle") == "hold":
            return True
        names = [self.config.get("hotkey")]
        names += self.config.get("extra_hotkeys") or []
        return any(name in {"numpad_enter", "caps_lock"} for name in names)

    def _start_supervisor(self) -> None:
        """Start the self-healing watchdog thread (idempotent)."""
        self._supervisor_stop.clear()
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            return
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop, daemon=True
        )
        self._supervisor_thread.start()

    def _supervisor_loop(self) -> None:
        """Watchdog: detect and revive dead keyboard listeners.

        Covers the two ways the PTT key silently stops working:
        - a listener thread died (unhandled exception inside pynput) —
          detected via ``.running``;
        - Windows silently removed the low-level hook (it does this when a
          hook callback exceeds the OS timeout under load; nothing is raised
          and the thread still looks healthy) — detected by injecting a
          harmless F24 keystroke that win32_event_filter must acknowledge.
        """
        user32 = ctypes.windll.user32
        vk_probe = 0x87  # F24
        keyeventf_keyup = 0x0002

        class LastInputInfo(ctypes.Structure):
            _fields_ = (("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint))

        def idle_seconds() -> float:
            info = LastInputInfo()
            info.cbSize = ctypes.sizeof(info)
            if not user32.GetLastInputInfo(ctypes.byref(info)):
                return 0.0
            return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0

        while not self._supervisor_stop.wait(30.0):
            try:
                if self.paused:
                    continue
                # Never interfere mid-take
                if self._pressed_hold_keys or (
                    self.recorder and self.recorder.recording
                ):
                    continue
                if self.listener and not self.listener.running:
                    self._heal("hotkey listener thread died")
                    continue
                if self._hold_listener is None:
                    continue
                if not self._hold_listener.running:
                    self._heal("hold listener thread died")
                    continue
                # Probe only while the user is actively at the machine: the
                # injected keystroke resets the OS idle timer, and probing an
                # idle machine would keep the display awake forever.
                if idle_seconds() > 60.0:
                    continue
                self._probe_seen.clear()
                user32.keybd_event(vk_probe, 0, 0, 0)
                user32.keybd_event(vk_probe, 0, keyeventf_keyup, 0)
                if not self._probe_seen.wait(1.0):
                    self._heal("keyboard hook unresponsive (silent unhook)")
            except Exception as e:  # noqa: BLE001
                try:
                    get_logger().warning("supervisor error: %s", e)
                except Exception:  # noqa: BLE001, S110
                    pass

    def _heal(self, reason: str) -> None:
        """Reinstall keyboard listeners after a detected failure."""
        if self._pressed_hold_keys or (self.recorder and self.recorder.recording):
            return  # a take just started — try again next cycle
        self.log(f"Self-heal: {reason} — reinstalling hotkey listeners.")
        try:
            self._stop_keyboard_listener(self._hold_listener)
            self._hold_listener = None
        except Exception:  # noqa: BLE001, S110
            pass
        try:
            if self._needs_record_key_listener():
                self._setup_hold_listener()
            self._start_global_hotkeys()
            self.log("Hotkey listeners reinstalled.")
        except Exception as e:  # noqa: BLE001
            self.log(f"Self-heal failed: {e}")

    def _setup_hold_listener(self) -> None:
        """Set up a press/release-aware listener for record keys.

        Hold mode records while the configured key is held. Toggle mode uses
        key-up only for debouncing, so auto-repeat cannot immediately stop a
        recording that the first key-down just started.

        Two keys need low-level-hook handling and get a ``win32_event_filter``:
        - ``caps_lock`` is suppressed system-wide so it can never flip the OS
          CapsLock state, while still driving recording through the callbacks.
        - ``numpad_enter`` shares its virtual-key code (VK_RETURN) with the main
          Enter and can only be told apart by the extended-key flag in the hook,
          so it is handled in the filter and swallowed (no stray newline/submit).
        """
        # pynput Key for the plain (non-special) PTT keys.
        key_map = {
            "alt_l": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "ctrl_l": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "shift_l": keyboard.Key.shift_l,
            "shift_r": keyboard.Key.shift_r,
            "menu": keyboard.Key.menu,
        }

        names = [self.config.get("hotkey", "caps_lock")]
        names += self.config.get("extra_hotkeys") or []

        self._hold_keys = set()
        self._hold_caps = False
        self._hold_numpad_enter = False
        self._pressed_hold_keys = set()
        hold_mode = self.config.get("record_mode", "toggle") == "hold"
        for name in names:
            if name == "numpad_enter":
                self._hold_numpad_enter = True
            elif name == "caps_lock":
                self._hold_caps = True
            elif hold_mode and name in key_map:
                self._hold_keys.add(key_map[name])

        def on_press(key: Any) -> None:  # noqa: ANN401
            if key in self._hold_keys:
                self._record_key_down(key)

        def on_release(key: Any) -> None:  # noqa: ANN401
            if key in self._hold_keys:
                self._record_key_up(key)

        if self._hold_caps:
            # One-time: clear CapsLock now, before the hook starts
            # suppressing it — otherwise a lock that was already ON would
            # be stuck ON for the whole session.
            self._ensure_caps_lock_off()

        wm_keydown, wm_syskeydown = 0x0100, 0x0104
        wm_keyup, wm_syskeyup = 0x0101, 0x0105
        vk_return, vk_capital, vk_probe = 0x0D, 0x14, 0x87  # 0x87 = F24
        llkhf_extended, llkhf_injected = 0x01, 0x10

        def win32_event_filter(msg: int, data: Any) -> bool:  # noqa: ANN401
            # Any exception here would kill the pynput listener thread and
            # leave the PTT key silently dead — fail open instead.
            suppress = False
            try:
                vk = getattr(data, "vkCode", None)
                # Liveness probe from the supervisor: acknowledge and swallow.
                if vk == vk_probe:
                    self._probe_seen.set()
                    suppress = True
                # Numpad Enter = VK_RETURN with the extended-key flag. The
                # callback only ever sees a generic Key.enter and couldn't tell
                # it from the main Enter, so drive recording here and swallow it.
                # Injected (synthetic) Enters from other automation tools are
                # ignored — only the physical key drives recording.
                elif (
                    self._hold_numpad_enter
                    and vk == vk_return
                    and (data.flags & llkhf_extended)
                    and not (data.flags & llkhf_injected)
                ):
                    if msg in (wm_keydown, wm_syskeydown):
                        self._record_key_down("numpad_enter")
                    elif msg in (wm_keyup, wm_syskeyup):
                        self._record_key_up("numpad_enter")
                    suppress = True
                # CapsLock: swallow system-wide so it can't flip the OS lock,
                # and drive PTT directly in this filter. Using pynput's public
                # per-event suppression avoids leaving a private global
                # ``_suppress`` flag set, which could eat an unrelated Shift
                # release after a hook failure.
                elif self._hold_caps and vk == vk_capital:
                    if not (data.flags & llkhf_injected):
                        if msg in (wm_keydown, wm_syskeydown):
                            self._record_key_down("caps_lock")
                        elif msg in (wm_keyup, wm_syskeyup):
                            self._record_key_up("caps_lock")
                    suppress = True
            except Exception:  # noqa: BLE001
                return True

            if suppress and self._hold_listener:
                # suppress_event raises pynput's private control exception;
                # keep this outside the catch above so the hook can consume it.
                self._hold_listener.suppress_event()
            return not suppress

        self._hold_listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
            win32_event_filter=win32_event_filter,
        )
        self._hold_listener.start()

    def _record_key_down(self, ident: Any) -> None:  # noqa: ANN401
        """Handle a physical record-key down in hold or toggle mode."""
        if self.config.get("record_mode", "toggle") == "hold":
            self._press_hold_key(ident)
            return
        if ident in self._pressed_hold_keys:
            return
        self._pressed_hold_keys.add(ident)
        self._queue_record_toggle()

    def _record_key_up(self, ident: Any) -> None:  # noqa: ANN401
        """Release a toggle debounce lease, or stop a hold-mode take."""
        if self.config.get("record_mode", "toggle") == "hold":
            self._release_hold_key(ident)
        else:
            self._pressed_hold_keys.discard(ident)

    def _queue_record_toggle(self) -> None:
        """Run a toggle outside the keyboard hook and serialize rapid presses."""
        threading.Thread(
            target=self._do_record_toggle,
            name="record-toggle",
            daemon=True,
        ).start()

    def _do_record_toggle(self) -> None:
        """Serialize toggle starts/stops against microphone recovery work."""
        with self._ptt_lock:
            self.on_record_toggle()

    def _press_hold_key(self, ident: Any) -> None:  # noqa: ANN401
        """Register a PTT key going down; start recording on the first one."""
        if ident in self._pressed_hold_keys:
            return
        was_idle = not self._pressed_hold_keys
        self._pressed_hold_keys.add(ident)
        if was_idle:
            self._on_hold_start()

    def _release_hold_key(self, ident: Any) -> None:  # noqa: ANN401
        """Register a PTT key going up; stop recording when the last one lifts."""
        if ident not in self._pressed_hold_keys:
            return
        self._pressed_hold_keys.discard(ident)
        if not self._pressed_hold_keys:
            self._on_hold_release()

    def _cancel_recording(self) -> None:
        """Cancel an in-progress recording without transcribing."""
        if self.recorder and self.recorder.recording:
            self._ptt_gen += 1
            self.stop_live_transcribe.set()
            if self.live_transcribe_thread:
                self.live_transcribe_thread.join(timeout=1)
            self.recorder.stop()
            if self._media:
                self._media.resume()
            self._we_paused_media = False
            self.log("Recording cancelled.")
            self.set_status("Ready")

    def _ensure_caps_lock_off(self) -> None:
        """Toggle CapsLock OFF once if it happens to be ON.

        Called once before the hold-listener starts (while CapsLock isn't yet
        suppressed by the hook), so the injected keystroke actually reaches the
        OS and flips the lock. While the app runs the hook suppresses every
        physical CapsLock event, so the lock can no longer be toggled on — no
        watchdog needed.
        """
        user32 = ctypes.windll.user32
        VK_CAPITAL = 0x14
        KEYEVENTF_KEYUP = 0x0002
        # GetKeyState bit 0 = toggled ON
        if user32.GetKeyState(VK_CAPITAL) & 1:
            user32.keybd_event(VK_CAPITAL, 0x3A, 0, 0)
            user32.keybd_event(VK_CAPITAL, 0x3A, KEYEVENTF_KEYUP, 0)

    def _on_hold_start(self) -> None:
        """Handle hold key press — start recording.

        Deliberately does NOT gate on ``is_processing``: recording is
        independent of transcription, and the transcriber's own lock
        serializes GPU work. Blocking here silently swallowed speech when
        the user pressed PTT while the previous take was still processing.
        """
        if self.paused:
            return
        if not self.recorder:
            self.log("Recorder not initialized.")
            return

        def do_start() -> None:
            with self._ptt_lock:
                if not self.recorder or self.recorder.recording:
                    return
                self._we_paused_media = False
                self._ptt_gen += 1
                # Recording starts FIRST — the SMTC media pause can take
                # hundreds of ms and must never delay capturing speech.
                self._start_recording()
                if self.config.get("pause_media", True) and self._media:
                    threading.Thread(
                        target=self._pause_media_bg, args=(self._ptt_gen,), daemon=True
                    ).start()
            # Key already released while we were starting (quick tap) —
            # stop now, or recording runs forever.
            if not self._pressed_hold_keys:
                self._do_ptt_stop()

        threading.Thread(target=do_start, daemon=True).start()

    def _pause_media_bg(self, gen: int) -> None:
        """Pause media in parallel with an already-running recording."""
        if not self._media:
            return
        if not self._media.pause_if_playing():
            return
        if gen == self._ptt_gen and self.recorder and self.recorder.recording:
            self._we_paused_media = True
        else:
            # The take already ended (quick tap) — undo the late pause.
            self._media.resume()

    def _on_hold_release(self) -> None:
        """Handle hold key release — stop recording, transcribe, auto-type."""
        threading.Thread(target=self._do_ptt_stop, daemon=True).start()

    def _do_ptt_stop(self) -> None:
        """Stop the PTT recording (serialized against starts via _ptt_lock)."""
        with self._ptt_lock:
            if not self.recorder:
                return
            # Also proceed when the stream died mid-take (recording=False but
            # the live-preview thread is still up) so overlay/threads get
            # cleaned up and the failure lands in history.
            stream_died = (
                self.live_transcribe_thread is not None
                and self.live_transcribe_thread.is_alive()
            )
            if not self.recorder.recording and not stream_died:
                return
            # Invalidate a pause still in flight before resuming. This closes
            # the release-time race where media became paused after the old
            # boolean check and then stayed paused forever.
            self._ptt_gen += 1
            if self._media:
                self._media.resume()
            self._we_paused_media = False
            self._stop_recording_and_type()

    def _verify_mic_alive(self) -> None:
        """Self-heal: confirm the mic stream actually delivers audio.

        sd.InputStream can fail to open (device busy, USB hiccup) while the
        UI happily shows "Recording". Detect that shortly after start and
        restart the stream once; a persistent failure surfaces on release
        as an error entry in history.
        """
        time.sleep(0.7)
        with self._ptt_lock:
            rec = self.recorder
            if not rec or not rec.recording:
                return  # take already ended — nothing to verify
            if rec.last_error is None and rec.frames:
                return  # healthy: stream is delivering frames
            err = rec.last_error or "no frames from microphone"
            self.log(f"Mic stream dead at start ({err}) — restarting stream.")
            rec.stop()
            # Restart while the take is still wanted: PTT key held, or
            # toggle mode (where recording runs until toggled off).
            if (
                self._pressed_hold_keys
                or self.config.get("record_mode", "toggle") != "hold"
            ):
                rec.start()

    def stop(self) -> None:
        """Stop the application: listeners, recording, live transcription, overlay."""
        self._supervisor_stop.set()
        # Stop live transcription thread first
        self.stop_live_transcribe.set()
        if self.live_transcribe_thread:
            self.live_transcribe_thread.join(timeout=3.0)
            self.live_transcribe_thread = None

        # Stop any active recording
        if self.recorder and self.recorder.recording:
            try:
                self.recorder.stop()
            except Exception:  # noqa: BLE001, S110
                pass

        self._stop_keyboard_listener(self.listener)
        self._stop_keyboard_listener(self._hold_listener)
        self.listener = None
        self._hold_listener = None
        if self._media:
            self._media.stop()
        self.overlay.stop()

    def toggle_pause(self) -> None:
        """Toggle the application pause state."""
        self.paused = not self.paused
        if self.paused:
            self.set_status("Paused")
            self.log("App paused. Hotkeys disabled.")
        else:
            self.set_status("Ready")
            self.log("App resumed.")

    # --- Callbacks ---
    def on_record_toggle(self) -> None:
        """Toggle audio recording."""
        if self.paused:
            return

        if (
            self.is_processing
            and time.time() - self._processing_start_time > 60  # noqa: PLR2004
        ):
            # Transcription has its own serialization. Do not swallow a new
            # recording press merely because the previous take is processing.
            self.log("Processing timeout — resetting stuck state.")
            with self._processing_lock:
                self._processing_jobs = 0
                self.is_processing = False

        if not self.recorder:
            self.log("Recorder not initialized.")
            return

        if self.recorder.recording:
            self._ptt_gen += 1
            if self._media:
                self._media.resume()
            self._we_paused_media = False
            if self.config.get("auto_type", False):
                self._stop_recording_and_type()
            else:
                self._stop_recording()
        else:
            self._we_paused_media = False
            self._ptt_gen += 1
            self._start_recording()
            if self.config.get("pause_media", True) and self._media:
                threading.Thread(
                    target=self._pause_media_bg,
                    args=(self._ptt_gen,),
                    daemon=True,
                ).start()

    def _start_recording(self) -> None:
        """Handle the start of an audio recording session."""
        if self.config.get("refocus_window", True) and self.window_manager:
            self.target_window_handle = self.window_manager.get_active_window()
        else:
            self.target_window_handle = None

        self.pending_text = None
        if self.on_preview_update:
            self.on_preview_update("", None)  # Clear preview

        if self.recorder:
            self.recorder.start()
            # Show audio visualizer overlay
            self.overlay.show(self.recorder)
            threading.Thread(target=self._verify_mic_alive, daemon=True).start()
        self.set_status("Recording")
        self.log("Recording started...")

        # Start live transcription loop
        self.stop_live_transcribe.clear()
        self.live_transcribe_thread = threading.Thread(
            target=self._live_transcription_loop, daemon=True
        )
        self.live_transcribe_thread.start()

    def _stop_recording(self) -> None:
        """Handle the end of an audio recording session."""
        self.log("Stopping recording...")
        self.set_status("Processing")

        # Stop live transcription loop
        self.stop_live_transcribe.set()
        if self.live_transcribe_thread:
            self.live_transcribe_thread.join(timeout=5.0)
            if self.live_transcribe_thread.is_alive():
                self.log("Warning: live transcription thread did not stop in time")
            self.live_transcribe_thread = None

        if not self.recorder:
            return

        audio_data = self.recorder.stop()

        if audio_data is not None:
            self._begin_processing()

            def process_audio() -> None:
                # Backup the raw audio first — if transcription fails, the
                # speech is still recoverable from _audio_backup/.
                backup = save_audio_backup(audio_data)
                backup_path = str(backup) if backup else None
                if backup:
                    self.log(f"Audio backup saved: {backup.name}")
                try:
                    if self.transcriber:
                        text = self.transcriber.transcribe(audio_data)
                        if text:
                            self.pending_text = text
                            self._add_to_history(text, audio_path=backup_path)
                            self.log(f"Transcribed: {text}")
                            if self.on_preview_update:
                                self.on_preview_update(text, None)
                            self.set_status("Text Ready")
                        else:
                            self._add_to_history(
                                "", status="empty", audio_path=backup_path
                            )
                            self.log("No text transcribed.")
                            self.set_status("Ready")
                except Exception as e:  # noqa: BLE001
                    self._add_to_history(
                        self.pending_text or "",
                        status="error",
                        audio_path=backup_path,
                        error=str(e),
                    )
                    self.log(f"Error: {e}")
                    self.set_status("Error")
                finally:
                    self._finish_processing()

            threading.Thread(target=process_audio, daemon=True).start()
        else:
            self.log("No audio data.")
            self.set_status("Ready")

    def _stop_recording_and_type(self) -> None:
        """Stop recording, transcribe, and auto-type the result."""
        # A new take may start while this one is transcribing. Keep the exact
        # destination captured for this take instead of reading the mutable
        # controller-wide handle when the GPU job eventually finishes.
        target_window_handle = self.target_window_handle
        self.log("Stopping recording...")
        self.overlay.show_processing()  # Switch to yellow dot while transcribing
        self.set_status("Processing")

        # Stop live transcription loop
        self.stop_live_transcribe.set()
        if self.live_transcribe_thread:
            self.live_transcribe_thread.join(timeout=5.0)
            if self.live_transcribe_thread.is_alive():
                self.log("Warning: live transcription thread did not stop in time")
            self.live_transcribe_thread = None

        if not self.recorder:
            self.overlay.hide()
            return

        audio_data = self.recorder.stop()

        if audio_data is not None:
            self._begin_processing()

            def process_and_type() -> None:
                # Backup the raw audio first — if transcription fails, the
                # speech is still recoverable from _audio_backup/.
                backup = save_audio_backup(audio_data)
                backup_path = str(backup) if backup else None
                if backup:
                    self.log(f"Audio backup saved: {backup.name}")
                try:
                    if self.transcriber:
                        text = self.transcriber.transcribe(audio_data)
                        if text:
                            self.pending_text = text
                            self.log(f"Transcribed: {text}")
                            if self.on_preview_update:
                                self.on_preview_update(text, None)

                            # Auto-format via Gemini if enabled
                            if self.config.get("auto_format", False) and self.improver:
                                self.set_status("Formatting")
                                self.log("Formatting text via AI...")
                                fmt_prompt = self.config.get("format_prompt", "")
                                if fmt_prompt:
                                    prompt = fmt_prompt + "\n\nText: " + text
                                    formatted = self.improver.improve_text(
                                        text, prompt_template=prompt
                                    )
                                    if formatted and formatted != text:
                                        original = text
                                        text = formatted
                                        self.pending_text = text
                                        self.log("Text formatted.")
                                        if self.on_preview_update:
                                            self.on_preview_update(text, original)

                            self._add_to_history(text, audio_path=backup_path)

                            # Auto-type if enabled
                            if self.config.get("auto_type", False):
                                self.set_status("Typing")
                                self._auto_type_text(text, target_window_handle)
                            else:
                                self.set_status("Text Ready")
                        else:
                            self._add_to_history(
                                "", status="empty", audio_path=backup_path
                            )
                            self.log("No text transcribed.")
                            self.set_status("Ready")
                except Exception as e:  # noqa: BLE001
                    self._add_to_history(
                        self.pending_text or "",
                        status="error",
                        audio_path=backup_path,
                        error=str(e),
                    )
                    self.log(f"Error: {e}")
                    self.set_status("Error")
                finally:
                    self._finish_processing()
                    # Don't yank the visualizer away from a NEW recording the
                    # user may have already started while we were transcribing.
                    if not (self.recorder and self.recorder.recording):
                        self.overlay.hide()

            threading.Thread(target=process_and_type, daemon=True).start()
        else:
            err = self.recorder.last_error if self.recorder else None
            self._add_to_history("", status="error", error=err or "no audio captured")
            self.log(f"No audio data ({err or 'unknown reason'}).")
            self.overlay.hide()
            self.set_status("Ready")

    def _auto_type_text(
        self,
        text: str,
        target_window_handle: object | None = None,
    ) -> None:
        """Auto-paste transcribed text into active window + keep in clipboard as backup."""
        import pyperclip

        # The Windows clipboard is occasionally locked for a few milliseconds
        # by another app. Retry instead of turning a valid transcription into
        # an apparent loss or, worse, pasting stale clipboard contents.
        clipboard_error: Exception | None = None
        for attempt in range(5):
            try:
                pyperclip.copy(text)
                clipboard_error = None
                break
            except Exception as exc:  # noqa: BLE001
                clipboard_error = exc
                time.sleep(0.05 * (attempt + 1))
        if clipboard_error is not None:
            self.log(
                "Text is safe in History, but the clipboard was unavailable: "
                f"{clipboard_error}"
            )
            self.set_status("Text Ready")
            return

        # Refocus the target window where recording started
        do_refocus = self.config.get("refocus_window", True)
        if do_refocus and self.window_manager and target_window_handle:
            if not self.window_manager.focus_window(target_window_handle):
                self.log(
                    f"Clipboard ({len(text)} chars). Could not refocus — "
                    "Ctrl+V to paste."
                )
                self.set_status("Ready")
                return
            time.sleep(0.15)
            active = self.window_manager.get_active_window()
            if active is not None and not self._windows_match(
                active, target_window_handle
            ):
                self.log(
                    f"Clipboard ({len(text)} chars). Focus changed — "
                    "Ctrl+V to paste safely."
                )
                self.set_status("Ready")
                return

        # Simulate Ctrl+V via Windows API directly (pynput Controller
        # conflicts with the active CapsLock suppress listener)
        user32 = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_V = 0x56
        KEYEVENTF_KEYUP = 0x0002

        control_down = False
        v_down = False
        try:
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            control_down = True
            user32.keybd_event(VK_V, 0, 0, 0)
            v_down = True
            time.sleep(0.05)
        finally:
            # Never leave a synthetic modifier held if injection fails midway.
            if v_down:
                user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            if control_down:
                user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)

        self.log(f"Auto-pasted ({len(text)} chars). Also in clipboard.")
        self.set_status("Ready")

    def _live_transcription_loop(self) -> None:
        """Periodically transcribe a recent audio window during recording.

        Only transcribes the last ~10 seconds of audio (not the full buffer)
        using greedy decoding (beam_size=1) for speed.
        """
        last_transcription_time = time.time()
        # Max samples to transcribe live: ~5 seconds at 16kHz (keep short for responsiveness)
        max_preview_samples = 16000 * 5
        while not self.stop_live_transcribe.is_set():
            # Use wait() instead of sleep() so thread responds immediately to stop
            if self.stop_live_transcribe.wait(timeout=1.0):
                break

            throttle_limit = 2.0
            if time.time() - last_transcription_time < throttle_limit:
                continue

            if not self.recorder or not self.transcriber:
                continue

            if self.stop_live_transcribe.is_set():
                break

            audio_data = self.recorder.get_recent_data(max_samples=max_preview_samples)
            audio_buffer_min_len = 16000  # At least 1s of audio
            if audio_data is not None and len(audio_data) > audio_buffer_min_len:
                try:
                    text = self.transcriber.transcribe_fast(audio_data)
                    if self.stop_live_transcribe.is_set():
                        break
                    # Only update preview if we got real text (not empty/hallucination)
                    if text and text != self.pending_text:
                        self.pending_text = text
                        if self.on_preview_update:
                            self.on_preview_update(text, None)
                    last_transcription_time = time.time()
                except Exception:  # noqa: BLE001, S110
                    pass

    @staticmethod
    def _windows_match(first: object, second: object) -> bool:
        """Compare pygetwindow objects by HWND when available."""
        if hasattr(first, "_hWnd") and hasattr(second, "_hWnd"):
            return bool(first._hWnd == second._hWnd)  # noqa: SLF001
        return bool(first == second)

    def on_improve_text(self) -> None:
        """Improve the current pending text using AI."""
        if self.paused:
            return

        if self.is_processing:
            return

        if self.pending_text:
            if not self.config.get("gemini_api_key"):
                self.log("AI Improvement disabled: Gemini API Key missing.")
                return

            self._begin_processing()
            self.set_status("Improving AI")
            self.log("Requesting AI improvement...")

            def run_improve() -> None:
                try:
                    original_text = self.pending_text
                    prompt_template = self.config.get("gemini_prompt")
                    if self.improver:
                        improved = self.improver.improve_text(
                            original_text, prompt_template=prompt_template
                        )
                        if improved:
                            self.pending_text = improved
                            self.log("AI Improvement applied.")
                            if self.on_preview_update:
                                self.on_preview_update(improved, original_text)
                            self.set_status("Text Ready (Improved)")
                except Exception as e:  # noqa: BLE001
                    self.log(f"AI Error: {e}")
                finally:
                    self._finish_processing()

            threading.Thread(target=run_improve, daemon=True).start()
        else:
            self.log("No text to improve.")
