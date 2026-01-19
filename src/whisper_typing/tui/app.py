from textual.app import App, ComposeResult
from textual.containers import Container, Vertical, Horizontal
from textual.widgets import Header, Footer, Static, Log, Label, Button
from textual.binding import Binding
from textual.reactive import reactive
from textual.screen import Screen

from ..app_controller import WhisperAppController

class WhisperTui(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    
    #status_bar {
        dock: top;
        height: 3;
        background: $primary-background;
        color: $text;
        content-align: center middle;
        text-style: bold;
        border-bottom: solid $primary;
    }

    #preview_area {
        height: 20%;
        border: solid $secondary;
        background: $surface;
        padding: 1;
        margin: 1;
    }
    
    #log_area {
        height: 1fr;
        border: solid $accent;
        background: $surface;
        margin: 1;
    }

    .status_ready { color: $success; }
    .status_recording { color: $error; background: $error 20%; }
    .status_processing { color: $warning; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "configure", "Configure"), # Placeholder for now
        Binding("r", "reload", "Reload Config"),
    ]

    status_message = reactive("Starting...")
    preview_text = reactive("Ready to record...")

    def __init__(self, controller: WhisperAppController):
        super().__init__()
        self.controller = controller
        
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Label(self.status_message, id="status_bar")
        
        yield Container(
            Label("Preview:", classes="label"),
            Static(self.preview_text, id="preview_area"),
            Label("Logs:", classes="label"),
            Log(id="log_area"),
            id="main_container"
        )
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Whisper Typing"
        
        # Connect Controller Callbacks
        self.controller.on_log = self.write_log
        self.controller.on_status_change = self.update_status
        self.controller.on_preview_update = self.update_preview
        
        # Initialize Controller (this might take a moment, maybe run in worker?)
        # For now, run directly, but in real app better to be async if slow.
        # But initialize_components loads models, so it IS slow.
        self.run_worker(self.startup_controller, exclusive=True, thread=True)

    def startup_controller(self):
        self.write_log("Loading models... (this may take a few seconds)")
        self.update_status("Loading...")
        success = self.controller.initialize_components()
        if success:
            self.controller.start_listener()
            self.update_status("Ready")
            self.write_log("Application started successfully.")
            self.write_log(f"Press {self.controller.config['hotkey']} to record.")
        else:
            self.update_status("Initialization Failed")
            self.write_log("Failed to initialize components. Check logs/config.")

    def write_log(self, message: str) -> None:
        log_widget = self.query_one("#log_area", Log)
        log_widget.write_line(message)

    def update_status(self, status: str) -> None:
        self.status_message = status
        # Update style based on status content (simple heuristic)
        try:
            status_widget = self.query_one("#status_bar", Label)
            status_widget.update(status)
            status_widget.classes = "" # Reset
            if "Recording" in status:
                status_widget.add_class("status_recording")
            elif "Processing" in status or "Loading" in status:
                status_widget.add_class("status_processing")
            else:
                status_widget.add_class("status_ready")
        except Exception:
            pass # Widget might not be mounted yet

    def update_preview(self, text: str) -> None:
        self.preview_text = text if text else "..."
        try:
            self.query_one("#preview_area", Static).update(self.preview_text)
        except Exception:
            pass

    def action_reload(self):
        self.write_log("Reloading configuration...")
        self.controller.stop()
        self.controller.load_configuration()
        self.run_worker(self.startup_controller)

    def action_quit(self):
        self.controller.stop()
        self.exit()
