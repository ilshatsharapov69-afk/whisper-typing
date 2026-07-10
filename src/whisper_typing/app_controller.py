"""Main application controller for whisper-typing."""

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
from whisper_typing.diagnostics import PersistentHistory, save_audio_backup
from whisper_typing.overlay import AudioOverlay
from whisper_typing.transcriber import Transcriber
from whisper_typing.typer import Typer
from whisper_typing.window_manager import WindowManager

if TYPE_CHECKING:
    from collections.abc import Callable

DEFAULT_CONFIG: dict[str, Any] = {
    "hotkey": "<f8>",
    "extra_hotkeys": [],
    "type_hotkey": "<f9>",
    "improve_hotkey": "<f10>",
    "model": "openai/whisper-base",
    "language": None,
    "gemini_prompt": None,
    "microphone_name": None,
    "gemini_model": None,
    "device": "cpu",
    "compute_type": "auto",
    "debug": False,
    "typing_wpm": 40,
    "gemini_api_key": None,
    "refocus_window": True,
    "model_cache_dir": None,
    "pause_media": True,
    "auto_format": False,
    "visualizer_style": "bars",
    "visualizer_gradient": "green_red",
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
            with path.open() as f:
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

        with Path(config_path).open("w") as f:
            json.dump(save_data, f, indent=4)
    except Exception:  # noqa: BLE001, S110
        pass


class MediaController:
    """Pause/resume media using Windows SMTC (System Media Transport Controls).

    Uses try_pause_async / try_play_async — explicit commands, not toggle.
    Correctly detects Playing vs Paused state via playback_status.
    """

    def __init__(self, logger: "Callable[[str], None] | None" = None) -> None:
        self._log = logger or (lambda _: None)
        self._we_paused: bool = False

    def pause_if_playing(self) -> bool:
        """Pause media if currently playing. Returns True if we paused."""
        import asyncio

        try:
            return asyncio.run(self._async_pause_if_playing())
        except Exception as e:
            self._log(f"MediaController pause error: {e}")
            return False

    def resume(self) -> None:
        """Resume media if we previously paused it."""
        import asyncio

        try:
            asyncio.run(self._async_resume())
        except Exception as e:
            self._log(f"MediaController resume error: {e}")

    async def _async_pause_if_playing(self) -> bool:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
        )

        manager = await Mgr.request_async()
        session = manager.get_current_session()
        if not session:
            self._log("No media session found.")
            return False

        info = session.get_playback_info()
        # PlaybackStatus: 4=Playing, 5=Paused
        if info.playback_status == 4:
            result = await session.try_pause_async()
            self._log(f"Media paused (success={result}).")
            return bool(result)

        self._log(f"Media not playing (status={info.playback_status}) — skipping.")
        return False

    async def _async_resume(self) -> None:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Mgr,
        )

        manager = await Mgr.request_async()
        session = manager.get_current_session()
        if session:
            result = await session.try_play_async()
            self._log(f"Media resumed (success={result}).")

    def stop(self) -> None:
        """Nothing to clean up."""


class WhisperAppController:
    """Controller for Whisper Typing App logic.

    Decoupled from UI (CLI or TUI).
    """

    def __init__(self) -> None:
        """Initialize the WhisperAppController."""
        self.config: dict[str, Any] = {}
        self.recorder: AudioRecorder | None = None
        self.transcriber: Transcriber | None = None
        self.typer: Typer | None = None
        self.improver: AIImprover | None = None
        self.listener: keyboard.GlobalHotKeys | None = None
        self.window_manager: WindowManager = WindowManager()
        self.overlay: AudioOverlay = AudioOverlay()
        self.target_window_handle: Any | None = None

        self.is_processing: bool = False
        self._processing_start_time: float = 0.0
        self.pending_text: str | None = None
        self.paused: bool = False

        # History of transcriptions: persisted to history.json (survives
        # restarts, keeps failures + wav backup paths); in-memory view = last 10.
        self._persistent_history: PersistentHistory = PersistentHistory()
        self.transcription_history: list[tuple[str, str]] = self._persistent_history.recent(10)

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

        self.typing_stop_event: threading.Event = threading.Event()
        self._is_typing: bool = False

        # Hold-to-talk state. Recording runs while any registered push-to-talk
        # key is held (multi-key: e.g. CapsLock on the left + numpad Enter on
        # the right). Start on the first key down, stop on the last key up.
        self._hold_listener: keyboard.Listener | None = None
        self._hold_keys: set[Any] = set()  # pynput Key objects matched in the callbacks
        self._hold_caps: bool = False  # CapsLock is a PTT key (needs OS-toggle suppression)
        self._hold_numpad_enter: bool = False  # numpad Enter is a PTT key (handled in the hook filter)
        self._pressed_hold_keys: set[Any] = set()  # PTT keys currently held down
        # Serializes PTT start/stop: a quick re-press must wait for the
        # previous stop to finish, otherwise recorder.start() sees
        # recording=True and silently swallows the new take.
        self._ptt_lock: threading.Lock = threading.Lock()
        self._we_paused_media: bool = False
        self._media: MediaController | None = None

    def log(self, message: str) -> None:
        """Log a message using the configured UI callback.

        Args:
            message: The message to log.

        """
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
        self._persistent_history.add(text, status=status, audio_path=audio_path, error=error)
        self.transcription_history = self._persistent_history.recent(10)

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
            if args.type_hotkey:
                self.config["type_hotkey"] = args.type_hotkey
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
            self.typer = Typer(wpm=self.config.get("typing_wpm", 40))
            self.improver = AIImprover(
                api_key=self.config.get("gemini_api_key"),
                model_name=self.config.get("gemini_model") or "gemini-1.5-flash",
                debug=self.config.get("debug", False),
                logger=self.log,
            )

            # Configure and start overlay (hidden until recording)
            self.overlay.set_style(self.config.get("visualizer_style", "bars"))
            self.overlay.set_gradient(self.config.get("visualizer_gradient", "green_red"))
            self.overlay.start()

            # Start persistent media controller for pause/resume
            if not self._media:
                self._media = MediaController(logger=self.log)

            self.log("Components initialized.")
        except Exception as e:  # noqa: BLE001
            self.log(f"Error initializing components: {e}")
            return False
        else:
            return True

    def start_listener(self) -> None:
        """Start the hotkey listener."""
        if self.listener:
            self.listener.stop()
        if self._hold_listener:
            self._hold_listener.stop()

        record_mode = self.config.get("record_mode", "toggle")

        try:
            if record_mode == "hold":
                # Hold-to-talk mode: use Listener for press/release detection
                self._setup_hold_listener()
                # Still register type/improve hotkeys via GlobalHotKeys
                self.listener = keyboard.GlobalHotKeys(
                    {
                        self.config["type_hotkey"]: self.on_type_confirm,
                        self.config["improve_hotkey"]: self.on_improve_text,
                    }
                )
                self.listener.start()
                hotkey_name = self.config["hotkey"]
                self.log(f"Hold-to-talk mode. Hold {hotkey_name} to record, release to transcribe+type.")
            else:
                # Toggle mode (original behavior)
                self.listener = keyboard.GlobalHotKeys(
                    {
                        self.config["hotkey"]: self.on_record_toggle,
                        self.config["type_hotkey"]: self.on_type_confirm,
                        self.config["improve_hotkey"]: self.on_improve_text,
                    }
                )
                self.listener.start()
                self.log(f"Hotkeys registered. Press {self.config['hotkey']} to record.")
            self.set_status("Ready")
        except ValueError as e:
            self.log(f"Invalid hotkey format: {e}")
            self.set_status("Hotkey Error")

    def _setup_hold_listener(self) -> None:
        """Set up the keyboard listener for hold-to-talk mode.

        Supports several push-to-talk keys at once (config ``hotkey`` plus
        ``extra_hotkeys``); recording runs while any of them is held.

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
        for name in names:
            if name == "numpad_enter":
                self._hold_numpad_enter = True
            elif name == "caps_lock":
                self._hold_caps = True
                self._hold_keys.add(keyboard.Key.caps_lock)
            elif name in key_map:
                self._hold_keys.add(key_map[name])

        def on_press(key: Any) -> None:  # noqa: ANN401
            if key in self._hold_keys:
                self._press_hold_key(key)

        def on_release(key: Any) -> None:  # noqa: ANN401
            if key in self._hold_keys:
                self._release_hold_key(key)

        if self._hold_caps or self._hold_numpad_enter:
            if self._hold_caps:
                # One-time: clear CapsLock now, before the hook starts
                # suppressing it — otherwise a lock that was already ON would
                # be stuck ON for the whole session.
                self._ensure_caps_lock_off()

            wm_keydown, wm_syskeydown = 0x0100, 0x0104
            wm_keyup, wm_syskeyup = 0x0101, 0x0105
            vk_return, vk_capital = 0x0D, 0x14
            llkhf_extended, llkhf_injected = 0x01, 0x10

            def win32_event_filter(msg: int, data: Any) -> bool:  # noqa: ANN401
                vk = getattr(data, "vkCode", None)
                # Numpad Enter = VK_RETURN with the extended-key flag. The
                # callback only ever sees a generic Key.enter and couldn't tell
                # it from the main Enter, so drive recording here and swallow it.
                if (
                    self._hold_numpad_enter
                    and vk == vk_return
                    and (data.flags & llkhf_extended)
                ):
                    self._hold_listener._suppress = True  # noqa: SLF001
                    if msg in (wm_keydown, wm_syskeydown):
                        self._press_hold_key("numpad_enter")
                    elif msg in (wm_keyup, wm_syskeyup):
                        self._release_hold_key("numpad_enter")
                    return False  # don't deliver to on_press/on_release
                # CapsLock: swallow system-wide so it can't flip the OS lock,
                # but still deliver physical presses to the callbacks so it
                # drives recording. Ignore synthetic (injected) caps events.
                if self._hold_caps and vk == vk_capital:
                    self._hold_listener._suppress = True  # noqa: SLF001
                    if data.flags & llkhf_injected:
                        return False
                    return True
                self._hold_listener._suppress = False  # noqa: SLF001
                return True

            self._hold_listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
                win32_event_filter=win32_event_filter,
            )
        else:
            self._hold_listener = keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            )
        self._hold_listener.start()

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
            self.stop_live_transcribe.set()
            if self.live_transcribe_thread:
                self.live_transcribe_thread.join(timeout=1)
            self.recorder.stop()
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
                if self.config.get("pause_media", True) and self._media:
                    self._we_paused_media = self._media.pause_if_playing()
                self._start_recording()
            # Key already released while we were starting (quick tap during
            # the media-pause window) — stop now, or recording runs forever.
            if not self._pressed_hold_keys:
                self._do_ptt_stop()

        threading.Thread(target=do_start, daemon=True).start()

    def _on_hold_release(self) -> None:
        """Handle hold key release — stop recording, transcribe, auto-type."""
        threading.Thread(target=self._do_ptt_stop, daemon=True).start()

    def _do_ptt_stop(self) -> None:
        """Stop the PTT recording (serialized against starts via _ptt_lock)."""
        with self._ptt_lock:
            if not self.recorder or not self.recorder.recording:
                return
            if self._we_paused_media and self._media:
                self._media.resume()
                self._we_paused_media = False
            self._stop_recording_and_type()

    def stop(self) -> None:
        """Stop the application: listeners, recording, live transcription, overlay."""
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

        # Stop typing if in progress
        self.typing_stop_event.set()

        if self.listener:
            self.listener.stop()
        if self._hold_listener:
            self._hold_listener.stop()
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

        if self.is_processing:
            # Auto-reset if processing has been stuck for over 60 seconds
            if time.time() - self._processing_start_time > 60:
                self.log("Processing timeout — resetting stuck state.")
                self.is_processing = False
            else:
                self.log("Busy processing, ignoring record toggle.")
                return

        if not self.recorder:
            self.log("Recorder not initialized.")
            return

        if self.recorder.recording:
            self._stop_recording()
        else:
            self._start_recording()

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
            self.is_processing = True
            self._processing_start_time = time.time()

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
                            self._add_to_history("", status="empty", audio_path=backup_path)
                            self.log("No text transcribed.")
                            self.set_status("Ready")
                except Exception as e:  # noqa: BLE001
                    self._add_to_history(
                        self.pending_text or "", status="error",
                        audio_path=backup_path, error=str(e),
                    )
                    self.log(f"Error: {e}")
                    self.set_status("Error")
                finally:
                    self.is_processing = False

            threading.Thread(target=process_audio, daemon=True).start()
        else:
            self.log("No audio data.")
            self.set_status("Ready")

    def _stop_recording_and_type(self) -> None:
        """Stop recording, transcribe, and auto-type the result."""
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
            self.is_processing = True
            self._processing_start_time = time.time()

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
                                self._auto_type_text(text)
                            else:
                                self.set_status("Text Ready")
                        else:
                            self._add_to_history("", status="empty", audio_path=backup_path)
                            self.log("No text transcribed.")
                            self.set_status("Ready")
                except Exception as e:  # noqa: BLE001
                    self._add_to_history(
                        self.pending_text or "", status="error",
                        audio_path=backup_path, error=str(e),
                    )
                    self.log(f"Error: {e}")
                    self.set_status("Error")
                finally:
                    self.is_processing = False
                    # Don't yank the visualizer away from a NEW recording the
                    # user may have already started while we were transcribing.
                    if not (self.recorder and self.recorder.recording):
                        self.overlay.hide()

            threading.Thread(target=process_and_type, daemon=True).start()
        else:
            self.log("No audio data.")
            self.overlay.hide()
            self.set_status("Ready")

    def _auto_type_text(self, text: str) -> None:
        """Auto-paste transcribed text into active window + keep in clipboard as backup."""
        import pyperclip

        # Always copy to clipboard as backup
        pyperclip.copy(text)

        # Refocus the target window where recording started
        do_refocus = self.config.get("refocus_window", True)
        if do_refocus and self.window_manager and self.target_window_handle:
            if not self.window_manager.focus_window(self.target_window_handle):
                self.log(f"Clipboard ({len(text)} chars). Could not refocus — Ctrl+V to paste.")
                self.set_status("Ready")
                return
            time.sleep(0.15)

        # Simulate Ctrl+V via Windows API directly (pynput Controller
        # conflicts with the active CapsLock suppress listener)
        user32 = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_V = 0x56
        KEYEVENTF_KEYUP = 0x0002

        user32.keybd_event(VK_CONTROL, 0, 0, 0)
        user32.keybd_event(VK_V, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
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

    def on_type_confirm(self) -> None:
        """Confirm and start typing the transcribed text."""
        if self.paused:
            return

        if self._is_typing:
            self.log("Stopping typing simulation...")
            self.typing_stop_event.set()
            return

        if self.pending_text:
            text_to_type = self.pending_text
            self.typing_stop_event.clear()
            self._is_typing = True

            threading.Thread(
                target=self._async_typing_wrapper, args=(text_to_type,), daemon=True
            ).start()
        else:
            self.log("No text to type.")

    def _async_typing_wrapper(self, text: str) -> None:
        """Wrap asynchronous typing simulation."""
        try:
            do_refocus = self.config.get("refocus_window", True)
            if do_refocus and self.window_manager and self.target_window_handle:
                if not self.window_manager.focus_window(self.target_window_handle):
                    self.log("Failed to restore focus.")
                    self._is_typing = False
                    return
                time.sleep(0.3)

            if self.typer:
                self.typer.type_text(
                    text,
                    stop_event=self.typing_stop_event,
                    check_focus=self._check_typing_focus,
                )

                if self.typing_stop_event.is_set():
                    self.log("Typing stopped.")
                else:
                    self.log("Typing finished.")
        finally:
            self._is_typing = False
            self.set_status("Ready")

    def _check_typing_focus(self) -> bool:
        """Check if the target window still has focus."""
        if not self.window_manager or not self.target_window_handle:
            return True

        active = self.window_manager.get_active_window()
        if (
            active
            and hasattr(active, "_hWnd")
            and hasattr(self.target_window_handle, "_hWnd")
        ):
            return bool(active._hWnd == self.target_window_handle._hWnd)  # noqa: SLF001
        return bool(active == self.target_window_handle)

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

            self.is_processing = True
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
                    self.is_processing = False

            threading.Thread(target=run_improve, daemon=True).start()
        else:
            self.log("No text to improve.")
