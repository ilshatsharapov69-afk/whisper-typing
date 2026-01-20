# Whisper Typing

![whiisper](https://github.com/user-attachments/assets/8bbd34ac-38d2-481e-9356-06e9f4498f0e)

A powerful, human-like background speech-to-text application for Windows that runs locally. It listens for a global hotkey to record your voice, transcribes it in real-time using `faster-whisper`, and types the result into your active window with natural rhythm and pace.

## Features

- **Real-Time Transcription**: See your words appear in the preview area instantly as you speak.
- **Human-like Typing**: Simulates natural typing with variable speed, random jitter, and intelligent pauses after punctuation.
- **Global Hotkeys**: Control recording and typing from any application.
  - **Record/Stop**: `F8` (default)
  - **Confirm Type**: `F9` (default)
  - **Improve Text**: `F10` (default) - Uses Gemini AI to fix grammar and refine text.
- **Safe Focus**: Automatically stops typing if you switch away from the target window.
- **Secure Storage**: Sensitive API keys are stored safely in a local `.env` file, not in plain JSON.
- **TUI Management**: A sleek terminal interface for monitoring logs, previewing text, and configuring settings.
- **Local Processing**: Audio is processed locally using `faster-whisper` (accelerated with CUDA if available).

## Prerequisites

- **Python 3.13+**
- **NVIDIA GPU (Recommended)**: Supports CUDA for lightning-fast transcription. Fallback to CPU is supported but slower.

## Installation

This project uses `uv` for dependency management.

1. **Clone the repository**:
   ```bash
   git clone https://github.com/rpfilomeno/whispher-typing.git
   cd whispher-typing
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

## Usage

Run the application using `uv`:

```bash
uv run whisper-typing
```

### TUI Shortcuts

Inside the application, you can use these keys:

- **`c`**: Open Configuration screen.
- **`p`**: Pause/Resume hotkeys.
- **`r`**: Reload configuration.
- **`q`**: Quit the application.

### Workflow

1. **Start Recording**: Press **F8**. You will see "Recording" in the status bar.
2. **Speak**: You will see transcribed text appear in the **Preview Area** in real-time.
3. **Stop**: Press **F8** again.
4. **Confirm Type**: Switch to your target application (e.g., Notepad, Slack) and press **F9**. The text will be typed out with human-like timing.
5. **Improve (Optional)**: Press **F10** before typing to have Gemini AI refine your transcription.

## Configuration

You can customize the application via the UI (press `c`) or by editing local files.

### Secure API Keys

The Gemini API key is stored in a `.env` file:

```env
GEMINI_API_KEY=your_key_here
```

### JSON Configuration (`config.json`)

Other settings are stored in `config.json`:

```json
{
  "hotkey": "<f8>",
  "type_hotkey": "<f9>",
  "improve_hotkey": "<f10>",
  "model": "openai/whisper-large-v3-turbo",
  "compute_type": "auto",
  "device": "cuda",
  "typing_wpm": 40
}
```

## Troubleshooting

- **Slow Transcription**: Check the logs to see if "cuda" or "cpu" is being used. You can change this in the Configuration screen.
- **Hotkeys not working**: Ensure no other application is capturing the same keys.
