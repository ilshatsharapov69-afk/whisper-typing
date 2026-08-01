# Whisper Typing

![whisper](https://github.com/user-attachments/assets/8bbd34ac-38d2-481e-9356-06e9f4498f0e)

A background speech-to-text application for Windows that runs locally. It listens for a global hotkey to record your voice, transcribes it using `faster-whisper`, and safely pastes the result into your target window.

> Fork of [rpfilomeno/whisper-typing](https://github.com/rpfilomeno/whisper-typing) with system tray support, audio overlay, media pause, and hold-to-record mode.

## Features

- **Real-Time Transcription**: See your words appear in the preview area instantly as you speak.
- **System Tray Icon**: Runs in the background with a color-coded tray icon (green = ready, red = recording, yellow = processing).
- **Audio Overlay**: Floating audio level visualization while recording.
- **Media Auto-Pause**: Pauses every Windows media session plus Chrome/Edge Picture-in-Picture when recording starts, then resumes only what the app paused.
- **Recovery History**: Right-click the tray icon and choose **History** for a searchable local report with copy buttons and playable WAV backups.
- **Hold-to-Record**: Hold the hotkey to record, release to stop (configurable: hold or toggle mode).
- **Auto-Paste**: Automatically pastes the transcribed text after recording stops.
- **Global Hotkeys**: Control recording and optional AI improvement from any application.
  - **Record/Stop**: `Caps Lock` or `F8` (configurable)
  - **Improve Text**: `F10` (default) - Uses Gemini AI to fix grammar and refine text.
- **Window Refocus**: Automatically switches back to your target window after recording stops.
- **Safe Focus**: Keeps the text in the clipboard instead of pasting if focus changed.
- **TUI Management**: A sleek terminal interface for monitoring logs, previewing text, and configuring settings.
- **Microphone Selection**: Choose your preferred input device directly from the configuration screen.
- **Local Processing**: Audio is processed locally using `faster-whisper` (accelerated with CUDA if available).

## Prerequisites

- **Python 3.13+**
- **uv** — Python package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **NVIDIA GPU (Recommended)**: Supports CUDA for lightning-fast transcription. Fallback to CPU is supported but slower.

## Quick Start (3 steps)

```bash
# 1. Clone
git clone https://github.com/ilshatsharapov69-afk/whisper-typing.git
cd whisper-typing

# 2. Install dependencies
uv sync

# 3. Run
uv run whisper-typing
```

On first run, models will be downloaded automatically (~1.5 GB for `whisper-large-v3-turbo`).

## Silent Launch (no console window)

To run whisper-typing in the background with only the system tray icon visible:

**Option 1**: Double-click `whisper-typing-silent.vbs`

**Option 2**: Add to Windows startup — copy `whisper-typing-silent.vbs` to:
```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
```

## Configuration

### Hotkeys & Settings (`config.json`)

On first run, a `config.json` is created with defaults. You can edit it or press `c` in the TUI:

```json
{
  "hotkey": "caps_lock",
  "improve_hotkey": "<f10>",
  "model": "openai/whisper-large-v3-turbo",
  "language": null,
  "device": "cuda",
  "compute_type": "float16",
  "refocus_window": true,
  "record_mode": "hold",
  "auto_type": true,
  "model_cache_dir": "./models/"
}
```

| Setting | Description |
|---------|-------------|
| `hotkey` | Record trigger key (`caps_lock`, `<f8>`, etc.) |
| `record_mode` | `"hold"` = hold key to record, `"toggle"` = press to start/stop |
| `auto_type` | Automatically type text after recording stops |
| `device` | `"cuda"` for GPU, `"cpu"` for CPU-only |
| `model` | Whisper model (`whisper-base.en` for fast, `whisper-large-v3-turbo` for quality) |
| `language` | `null` for auto-detect, `"en"`, `"ru"`, etc. |

### AI Text Improvement (optional)

To enable AI grammar correction (F10), create a `.env` file:

```env
GEMINI_API_KEY=your_key_here
```

Get a free API key at [Google AI Studio](https://aistudio.google.com/apikey).

### TUI Shortcuts

Inside the application:

- **`c`**: Open Configuration screen
- **`p`**: Pause/Resume hotkeys
- **`r`**: Reload configuration
- **`q`**: Quit the application

## Build EXE

Build a standalone Windows executable:

```powershell
.\build_dist.ps1
```

## System Tray

The app shows a system tray icon with state indicators:

| Color | State |
|-------|-------|
| Green | Ready — waiting for hotkey |
| Red | Recording — speak now |
| Yellow | Processing / Loading / Typing |

Right-click the tray icon to configure the app, open **History**, pause hotkeys, or quit.

History keeps up to 1,000 transcription records. The newest 100 raw recordings
are retained in `_audio_backup/`, and older successful transcriptions are
recovered from the rotating application logs during migration.

## Troubleshooting

- **Slow Transcription**: Check if `cuda` or `cpu` is being used (see logs). Change in config.
- **Hotkeys not working**: Ensure no other application captures the same keys.
- **Microphone Issues**: Press `c` to open config and select the correct microphone.
- **No tray icon**: Make sure `pystray` and `pillow` are installed (`uv sync` should handle this).

## Credits

Based on [rpfilomeno/whisper-typing](https://github.com/rpfilomeno/whisper-typing). MIT License.
