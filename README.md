# stt

Press-to-talk speech-to-text for macOS. Hold a hotkey, speak, release, and the transcription is pasted into the focused app. Runs Parakeet TDT 0.6B v2 locally via MLX.

## Requirements

- **macOS on Apple Silicon** (M1 / M2 / M3 / …). MLX is arm64-only.
- **Homebrew Python, not Anaconda.** Anaconda can break macOS notifications and microphone permissions. Use `brew install python@3.14` (or 3.12 / 3.13).

## Setup

```bash
# 1. Install Homebrew Python (skip if you already have it)
brew install python@3.14

# 2. Clone and enter the project
git clone <repo-url> stt
cd stt

# 3. Create a virtual environment with Python's built-in venv module
python3 -m venv venv

# 4. Install dependencies into the virtual environment
venv/bin/python -m pip install -r requirements.txt
```

## macOS permissions (required)

The script needs two permissions. macOS should prompt for each one the first time it triggers, but you can also grant them manually in **System Settings → Privacy & Security**:

1. **Microphone** — for your terminal app (Terminal.app, iTerm2, etc.). Without this, recordings are silently empty.
2. **Accessibility** — for your terminal app. Needed so the global hotkeys and the simulated `Cmd+V` paste work.

After granting either permission, **fully quit and reopen the terminal** (`Cmd+Q`, not just close the window) for it to take effect.

## Usage

```bash
./stt.py
```

Click where you want the text to land, then use either:

- **Push-to-talk**: hold **Right Option**, speak, release.
- **Toggle**: press **Option + Command** to start, press again to stop.

The transcription is pasted into the focused input and appended to `transcriptions.md`. Your existing clipboard contents are preserved, and the paste is hidden from clipboard history managers (Raycast, Maccy, Alfred, Pastebot, etc.).

## Settings

By default, the script uses the macOS default input device. To force a device, set `STT_INPUT_DEVICE` to an index or part of the device name:

```bash
STT_INPUT_DEVICE=webcam ./stt.py
STT_INPUT_DEVICE="HD Pro" ./stt.py
STT_INPUT_DEVICE=2 ./stt.py
```

List available devices:

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

Other settings:

```bash
STT_DENOISE=0 ./stt.py     # disable noise suppression
STT_DENOISE=1 ./stt.py     # force noise suppression
STT_SOUNDS=0 ./stt.py      # disable paste sound
```

Common transcription fixes live in `text_cleanup.py`. Filler-word cleanup is always on.

## Troubleshooting

- **`AttributeError: 'NoneType' object has no attribute 'removeAllDeliveredNotifications'`** — you're running under Anaconda Python. Recreate the venv using Homebrew Python (see Setup).
- **No audio captured / silent recordings** — the terminal app doesn't have microphone permission, *or* Anaconda Python failed to trigger the TCC prompt. Grant permission manually in System Settings → Privacy & Security → Microphone, then fully quit and reopen the terminal.
- **Hotkey does nothing** — the terminal app doesn't have Accessibility permission. Grant it in System Settings → Privacy & Security → Accessibility and fully restart the terminal.
- **Transcribed text appears in the terminal instead of where you wanted** — the terminal was the focused window when you stopped recording. Click into your target app *before* pressing the stop hotkey.
