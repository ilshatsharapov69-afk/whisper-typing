"""Configuration screens for the TUI."""

import os
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Label,
    Select,
)

from whisper_typing.ai_improver import AIImprover
from whisper_typing.app_controller import WhisperAppController
from whisper_typing.constants import WHISPER_MODELS


class ConfigurationScreen(Screen[bool]):
    """Screen for configuring application settings."""

    CSS = """
    ConfigurationScreen {
        align: center middle;
    }

    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: auto;
        padding: 0 1;
        width: 90%;
        max-width: 120;
        height: auto;
        border: thick $background 80%;
        background: $surface;
    }

    #title {
        column-span: 2;
        height: 1;
        content-align: center middle;
        text-style: bold;
        background: $primary;
        color: $text;
        margin-bottom: 1;
    }

    Label {
        column-span: 1;
        height: 3;
        content-align: left middle;
    }

    Select, Input {
        column-span: 1;
        width: 100%;
    }

    #buttons {
        column-span: 2;
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    Button {
        margin: 0 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, controller: WhisperAppController) -> None:
        """Initialize the ConfigurationScreen.

        Args:
            controller: The application controller instance.

        """
        super().__init__()
        self.controller = controller
        self.inputs: dict[str, Any] = {}

    def _get_mic_options(self) -> tuple[list[tuple[str, int | None]], int | None]:
        """Get microphone options for selection.

        Returns:
            A tuple of (options_list, start_value).

        """
        config = self.controller.config
        devices = self.controller.list_input_devices()
        mic_options: list[tuple[str, int | None]] = [
            (name, index) for index, name in devices
        ]
        mic_options.insert(0, ("Default System Mic", None))

        current_mic = config.get("microphone_name")
        start_value = None
        if current_mic:
            for idx, name in devices:
                if name == current_mic:
                    start_value = idx
                    break
        return mic_options, start_value

    def _get_gemini_options(self) -> tuple[list[tuple[str, str]], str]:
        """Get Gemini model options for selection.

        Returns:
            A tuple of (options_list, current_value).

        """
        config = self.controller.config
        gemini_api_key = config.get("gemini_api_key")
        gemini_models: list[tuple[str, str]] = []
        if gemini_api_key:
            model_ids = AIImprover.list_models(api_key=gemini_api_key)
            gemini_models = [(m.split("/")[-1], m) for m in model_ids]

        if not gemini_models:
            gemini_models = [
                ("Gemini 1.5 Flash", "models/gemini-1.5-flash"),
                ("Gemini 1.5 Pro", "models/gemini-1.5-pro"),
                ("Gemini 2.0 Flash", "models/gemini-2.0-flash"),
            ]

        current_gemini_model = config.get("gemini_model") or "models/gemini-1.5-flash"
        if current_gemini_model and not any(
            m[1] == current_gemini_model for m in gemini_models
        ):
            gemini_models.append(
                (current_gemini_model.split("/")[-1], current_gemini_model)
            )
        return gemini_models, current_gemini_model

    def compose(self) -> ComposeResult:
        """Compose the configuration screen layout."""
        config = self.controller.config
        mic_options, start_value = self._get_mic_options()
        compute_type_options = [
            ("Auto (Recommended)", "auto"),
            ("float16 (Fast GPU)", "float16"),
            ("int8 (Fast CPU)", "int8"),
            ("int8_float16", "int8_float16"),
            ("float32 (Accurate)", "float32"),
        ]
        device_options = [("CPU", "cpu"), ("GPU (CUDA)", "cuda")]
        gemini_models, current_gemini_model = self._get_gemini_options()

        yield Container(
            Label("Configuration", id="title"),
            Label("Microphone:"),
            Select(mic_options, value=start_value, id="mic_select"),
            Label("Whisper Model:"),
            Select(WHISPER_MODELS, value=config.get("model"), id="model_select"),
            Label("Device:"),
            Select(
                device_options, value=config.get("device", "cpu"), id="device_select"
            ),
            Label("Compute Type:"),
            Select(
                compute_type_options,
                value=config.get("compute_type", "auto"),
                id="compute_type_select",
            ),
            Label("Gemini API Key:"),
            Input(
                value=config.get("gemini_api_key") or "",
                password=True,
                id="api_key_input",
            ),
            Label("Gemini Model:"),
            Select(gemini_models, value=current_gemini_model, id="gemini_model_select"),
            Label("Model Cache Dir:"),
            Input(
                value=config.get("model_cache_dir") or "",
                placeholder="Default (HuggingFace cache)",
                id="model_cache_input",
            ),
            Label("Record Hotkey:"),
            Input(value=config.get("hotkey"), id="hotkey_input"),
            Label("Refocus Window:"),
            Checkbox(value=config.get("refocus_window", True), id="refocus_checkbox"),
            Label("Debug Mode:"),
            Checkbox(value=config.get("debug", False), id="debug_checkbox"),
            Horizontal(
                Button("Save", variant="primary", id="save_btn"),
                Button("Cancel", variant="error", id="cancel_btn"),
                id="buttons",
            ),
            id="dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "save_btn":
            self.save_and_exit()
        elif event.button.id == "cancel_btn":
            self.app.pop_screen()

    def action_cancel(self) -> None:
        """Cancel the configuration and exit the screen."""
        self.app.pop_screen()

    def _get_new_config(self) -> dict[str, Any]:
        """Gather current settings from UI widgets.

        Returns:
            A dictionary containing the new configuration values.

        """
        model_select = self.query_one("#model_select", Select)
        device_select = self.query_one("#device_select", Select)
        hotkey_input = self.query_one("#hotkey_input", Input)
        gemini_model_select = self.query_one("#gemini_model_select", Select)
        debug_checkbox = self.query_one("#debug_checkbox", Checkbox)
        refocus_checkbox = self.query_one("#refocus_checkbox", Checkbox)
        compute_type_select = self.query_one("#compute_type_select", Select)
        model_cache_input = self.query_one("#model_cache_input", Input)

        new_config = {
            "microphone_name": None,
            "model": model_select.value,
            "device": device_select.value,
            "compute_type": compute_type_select.value,
            "gemini_model": gemini_model_select.value,
            "debug": debug_checkbox.value,
            "refocus_window": refocus_checkbox.value,
            "hotkey": hotkey_input.value,
            "model_cache_dir": model_cache_input.value or None,
        }

        # Handle Microphone Name
        mic_select = self.query_one("#mic_select", Select)
        mic_idx = mic_select.value
        if mic_idx is not None:
            devices = self.controller.list_input_devices()
            for idx, name in devices:
                if idx == mic_idx:
                    new_config["microphone_name"] = name
                    break

        return new_config

    def save_and_exit(self) -> None:
        """Gather current settings, save them, and exit the screen."""
        new_config = self._get_new_config()

        # Change detection
        current_config = self.controller.config
        has_changes = any(
            current_config.get(key) != value for key, value in new_config.items()
        )

        # Special handling for API Key separately
        api_input = self.query_one("#api_key_input", Input)
        env_api_key = os.getenv("GEMINI_API_KEY", "")
        if api_input.value != env_api_key:
            self.controller.update_env_api_key(api_input.value)
            has_changes = True  # Signal that we should reload/re-init if key changed

        if has_changes:
            self.controller.update_config(new_config)
            self.dismiss(result=True)  # Return True to indicate save and reload
        else:
            self.dismiss(result=False)  # Return False to indicate no changes


class HistoryScreen(ModalScreen[None]):
    """Screen showing the last 10 transcriptions with copy-to-clipboard."""

    CSS = """
    HistoryScreen {
        align: center middle;
        background: $background 50%;
    }

    #history_dialog {
        padding: 1 2;
        width: 90%;
        max-width: 100;
        height: 80%;
        border: thick $primary;
        background: $surface;
    }

    #history_title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        color: $primary;
    }

    #history_list {
        height: 1fr;
        border: solid $accent;
        background: $surface;
        padding: 1;
        overflow-y: auto;
    }

    .history_entry {
        margin-bottom: 1;
        padding: 0 1;
    }

    .history_time {
        color: $accent;
        text-style: bold;
    }

    #history_buttons {
        align: center middle;
        margin-top: 1;
    }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "close", "Close"),
        Binding("c", "copy_last", "Copy last"),
        Binding("1", "copy_n(1)", "Copy #1"),
        Binding("2", "copy_n(2)", "Copy #2"),
        Binding("3", "copy_n(3)", "Copy #3"),
        Binding("4", "copy_n(4)", "Copy #4"),
        Binding("5", "copy_n(5)", "Copy #5"),
    ]

    def __init__(self, history: list[tuple[str, str]]) -> None:
        """Initialize with transcription history.

        Args:
            history: List of (timestamp, text) tuples, newest first.

        """
        super().__init__()
        self.history = history

    def compose(self) -> ComposeResult:
        """Compose the history screen layout."""
        from textual.widgets import RichLog

        yield Container(
            Label(
                "Transcription History — press 1-5 to copy that entry, "
                "C = copy last, Esc = close",
                id="history_title",
            ),
            RichLog(id="history_list", markup=True, highlight=True),
            Horizontal(
                Button("Copy Last", variant="primary", id="history_copy_last_btn"),
                Button("Copy All", variant="default", id="history_copy_all_btn"),
                Button("Close", variant="error", id="history_close_btn"),
                id="history_buttons",
            ),
            id="history_dialog",
        )

    def on_mount(self) -> None:
        """Populate the history list."""
        from textual.widgets import RichLog

        log_widget = self.query_one("#history_list", RichLog)
        if not self.history:
            log_widget.write("[dim]No transcriptions yet.[/dim]")
            return

        for i, (timestamp, text) in enumerate(self.history, 1):
            # Color failed/empty entries differently so they stand out
            is_error = text.startswith("[FAILED")
            is_empty = text.startswith("[NO SPEECH")
            if is_error:
                header_color = "bold red"
            elif is_empty:
                header_color = "bold yellow"
            else:
                header_color = "bold blue"
            log_widget.write(
                f"[{header_color}][{timestamp}][/{header_color}] [bold]#{i}[/bold]"
            )
            # text may contain a wav path on its own line — render verbatim
            for line in text.splitlines() or [""]:
                log_widget.write(f"  {line}")
            log_widget.write("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "history_copy_all_btn":
            self._copy_all()
        elif event.button.id == "history_copy_last_btn":
            self.action_copy_last()
        elif event.button.id == "history_close_btn":
            self.dismiss(None)

    def action_close(self) -> None:
        """Close the history screen."""
        self.dismiss(None)

    def action_copy_last(self) -> None:
        """Copy the newest entry's text (first item)."""
        self.action_copy_n(1)

    def action_copy_n(self, n: int) -> None:
        """Copy entry #n (1-based, newest first)."""
        import pyperclip

        if not self.history or n < 1 or n > len(self.history):
            self.app.notify(f"No entry #{n}", severity="warning")
            return
        _, text = self.history[n - 1]
        # Strip [FAILED ...] / [NO SPEECH ...] marker prefix when copying so the
        # user gets clean text or a usable wav path, not the diagnostic label.
        clean = text
        if text.startswith("[FAILED") or text.startswith("[NO SPEECH"):
            # Keep marker line so user sees what was copied; they can edit.
            pass
        pyperclip.copy(clean)
        preview = clean[:60].replace("\n", " ")
        self.app.notify(f"Copied #{n}: {preview}")

    def _copy_all(self) -> None:
        """Copy all history entries to clipboard."""
        import pyperclip

        if not self.history:
            self.app.notify("No history to copy", severity="warning")
            return

        lines = []
        for timestamp, text in self.history:
            lines.append(f"[{timestamp}] {text}")
        pyperclip.copy("\n".join(lines))
        self.app.notify(f"Copied {len(self.history)} entries to clipboard")


class ApiKeyPromptScreen(ModalScreen[str | None]):
    """Screen for prompting the user for a Gemini API key on startup."""

    CSS = """
    ApiKeyPromptScreen {
        align: center middle;
        background: $background 50%;
    }

    #api_dialog {
        padding: 1 2;
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
    }

    #api_title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        color: $primary;
    }

    #api_note {
        margin-bottom: 1;
        color: $text-muted;
    }

    #api_link {
        color: $accent;
        text-style: underline;
        margin-bottom: 1;
    }

    #api_input {
        margin-bottom: 1;
    }

    #api_buttons {
        align: center middle;
    }

    Button {
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Compose the API key prompt screen layout."""
        yield Container(
            Label("Gemini API Key Required", id="api_title"),
            Label(
                "The AI text improver will not be active if an API key is not present.",
                id="api_note",
            ),
            Label("Key: https://aistudio.google.com/app/apikey", id="api_link"),
            Input(placeholder="Enter Gemini API Key...", password=True, id="api_input"),
            Horizontal(
                Button("Save", variant="primary", id="api_save_btn"),
                Button("Skip", variant="error", id="api_skip_btn"),
                id="api_buttons",
            ),
            id="api_dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press events."""
        if event.button.id == "api_save_btn":
            api_key = self.query_one("#api_input", Input).value.strip()
            if api_key:
                self.dismiss(api_key)
            else:
                self.app.notify("Please enter a valid API key", severity="error")
        elif event.button.id == "api_skip_btn":
            self.dismiss(None)
