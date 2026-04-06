# stt

Press-to-talk speech-to-text for macOS. Hold a hotkey, speak, release — the transcription is pasted into whatever window you're focused on. Runs Parakeet TDT 0.6B v2 locally via MLX.

## Requirements

- **macOS on Apple Silicon** (M1 / M2 / M3 / …). MLX is arm64-only.
- **Homebrew Python, not Anaconda.** Anaconda's Python lacks a proper macOS Framework build, which breaks notifications and prevents the microphone permission prompt from firing. Use `brew install python@3.14` (or 3.12 / 3.13).

## Setup

```bash
# 1. Install Homebrew Python (skip if you already have it)
brew install python@3.14

# 2. Clone and enter the project
git clone <repo-url> stt
cd stt

# 3. Create a virtual environment with Python's built-in venv module
python3.14 -m venv venv

# 4. Activate it
source venv/bin/activate

# 5. Install dependencies
pip install -r requirements.txt
```

## macOS permissions (required)

The script needs two permissions. macOS should prompt for each one the first time it triggers, but you can also grant them manually in **System Settings → Privacy & Security**:

1. **Microphone** — for your terminal app (Terminal.app, iTerm2, etc.). Without this, recordings are silently empty.
2. **Accessibility** — for your terminal app. Needed so the global hotkey (`Option + Command`) and the simulated `Cmd+V` paste work.

After granting either permission, **fully quit and reopen the terminal** (`Cmd+Q`, not just close the window) for it to take effect.

## Usage

```bash
source venv/bin/activate   # if not already active
./stt.py
```

Then:

1. Click into the app/field where you want the text to land (Slack, editor, browser input, whatever).
2. Press `Option + Command` to start recording.
3. Speak.
4. Press `Option + Command` again to stop.
5. The transcription is copied to your clipboard and auto-pasted into the focused input.

Transcriptions are also appended to `transcriptions.md` in the project directory.

## Settings

### Choosing an input device

By default, the script uses whatever macOS has set as the system default input (**System Settings → Sound → Input**). If you plug in AirPods or a webcam mic, set them as the default there and restart the script.

To force a specific device regardless of the system default, set `STT_INPUT_DEVICE` to either an index or a case-insensitive substring of the device name:

```bash
STT_INPUT_DEVICE=webcam ./stt.py
STT_INPUT_DEVICE="HD Pro" ./stt.py
STT_INPUT_DEVICE=2 ./stt.py
```

To list available devices and their indices:

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

### Auto-corrections

Common transcription mistakes are fixed via a dictionary at the top of `stt.py` (`CORRECTIONS`). Add your own entries there as needed.

## Troubleshooting

- **`AttributeError: 'NoneType' object has no attribute 'removeAllDeliveredNotifications'`** — you're running under Anaconda Python. Recreate the venv using Homebrew Python (see Setup).
- **No audio captured / silent recordings** — the terminal app doesn't have microphone permission, *or* Anaconda Python failed to trigger the TCC prompt. Grant permission manually in System Settings → Privacy & Security → Microphone, then fully quit and reopen the terminal.
- **Hotkey does nothing** — the terminal app doesn't have Accessibility permission. Grant it in System Settings → Privacy & Security → Accessibility and fully restart the terminal.
- **Transcribed text appears in the terminal instead of where you wanted** — the terminal was the focused window when you stopped recording. Click into your target app *before* pressing the stop hotkey.
