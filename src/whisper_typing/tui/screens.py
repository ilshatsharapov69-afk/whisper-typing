from textual.app import ComposeResult
from textual.containers import Container, Vertical, Horizontal, Grid
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, Footer, Button, Label, Input, Select, Static
from textual.binding import Binding

class ConfigurationScreen(Screen):
    CSS = """
    ConfigurationScreen {
        align: center middle;
    }

    #dialog {
        grid-size: 2;
        grid-gutter: 1 2;
        grid-rows: auto;
        padding: 0 1;
        width: 60;
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
    
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.inputs = {}

    def compose(self) -> ComposeResult:
        config = self.controller.config
        
        # Microphones
        devices = self.controller.list_input_devices()
        # devices is list of (index, name)
        # Select takes list of (label, value)
        mic_options = [(name, index) for index, name in devices]
        # Add 'Default' option
        mic_options.insert(0, ("Default System Mic", None))
        
        current_mic = config.get("microphone_name")
        start_value = None
        if current_mic:
            # Find index for name
            for name, idx in devices:
                if name == current_mic:
                    start_value = idx
                    break

        # Whisper Models
        model_options = [
            ("Tiny", "openai/whisper-tiny"),
            ("Base", "openai/whisper-base"),
            ("Small", "openai/whisper-small"),
            ("Medium", "openai/whisper-medium"),
            ("Large v3", "openai/whisper-large-v3"),
            ("Large v3 Turbo", "openai/whisper-large-v3-turbo"),
        ]
        
        yield Container(
            Label("Configuration", id="title"),
            
            Label("Microphone:"),
            Select(mic_options, value=start_value, id="mic_select"),
            
            Label("Whisper Model:"),
            Select(model_options, value=config.get("model"), id="model_select"),
            
            Label("Gemini API Key:"),
            Input(value=config.get("gemini_api_key") or "", password=True, id="api_key_input"),
            
            Label("Record Hotkey:"),
            Input(value=config.get("hotkey"), id="hotkey_input"),
            
            Label("Type Hotkey:"),
            Input(value=config.get("type_hotkey"), id="type_hotkey_input"),
            
            Horizontal(
                Button("Save", variant="primary", id="save_btn"),
                Button("Cancel", variant="error", id="cancel_btn"),
                id="buttons"
            ),
            id="dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save_btn":
            self.save_and_exit()
        elif event.button.id == "cancel_btn":
            self.app.pop_screen()

    def action_cancel(self):
        self.app.pop_screen()

    def save_and_exit(self):
        # Gather values
        mic_select = self.query_one("#mic_select", Select)
        model_select = self.query_one("#model_select", Select)
        api_input = self.query_one("#api_key_input", Input)
        hotkey_input = self.query_one("#hotkey_input", Input)
        type_input = self.query_one("#type_hotkey_input", Input)
        
        new_config = {
            "microphone_name": None, # Resolve logic below
            "model": model_select.value,
            "gemini_api_key": api_input.value,
            "hotkey": hotkey_input.value,
            "type_hotkey": type_input.value
        }
        
        # Handle Microphone Name
        # value is the index or None
        mic_idx = mic_select.value
        if mic_idx is not None:
             # Find name from index
             mic_name = mic_select.get_option_at_index(mic_select.items.index((mic_select.prompt, mic_idx)) if mic_select.value != Select.BLANK else 0)[0]
             # Actually, Select options are (label, value).
             # We need to find the label corresponding to this value
             for label, value in mic_select._options:
                 if value == mic_idx:
                     new_config["microphone_name"] = label
                     break
        
        self.controller.update_config(new_config)
        self.dismiss(True) # Return True to indicate save
