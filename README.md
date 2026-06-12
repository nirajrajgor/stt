# stt

Privacy-first speech-to-text for macOS.

- Works offline.
- Hold a hotkey, speak, release, and text appears in the focused app.
- Works in noisy env.
- Handles quiet speech.
- Avg latency 700ms.
- Removes filler words ("um", "uh", "hmm").
- Supports voice commands like `scratch that` and `delete last 3 words`.
- Visual recording indicator.
- Auto close on sleep.
- Optimized for English language.

## Demo

<video src="https://github.com/user-attachments/assets/7ba238db-53a0-40a9-add9-0b77f314083e" controls width="720">
  Your browser does not support the video tag.
</video>

## Requirements

- **macOS on Apple Silicon** (M1 / M2 / M3 / …). MLX is arm64-only.
- **Recommended: 16GB RAM**. Running the model uses approximately 1.5GB RAM.
- **Homebrew Python, not Anaconda.** Anaconda can break macOS notifications and microphone permissions. Use `brew install python@3.14` (or 3.12 / 3.13).

## Setup

```bash
# 1. Install Homebrew Python (skip if you already have it)
brew install python@3.14

# 2. Clone and enter the project
git clone git@github.com:nirajrajgor/stt.git stt
cd stt

# 3. Create a virtual environment with Python's built-in venv module
python3 -m venv venv

# 4. Install dependencies into the virtual environment
venv/bin/python -m pip install -r requirements.txt
```

The first run downloads the Parakeet model from Hugging Face and caches it locally.

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
- **Toggle**: tap **Left Option + Left Command** to start, tap again to stop.

The transcription is pasted into the focused input and appended to `transcriptions.md`. Your existing plain text clipboard contents is preserved and the paste is hidden from clipboard history managers (Raycast, Maccy, Alfred, Pastebot, etc.).

Works in any app with a focused text field, including Notes, Slack, Mail, ChatGPT, Cursor, and browser text fields.

## Voice commands

Pause before and after a command so it is its own utterance:

- `scratch that` — delete the previous utterance
- `delete last 3 words` — delete the previous 3 words

Commands apply only within the current recording before paste.

## Settings

Hotkeys and runtime settings are read from `stt.config.toml`, created on first run. See `stt.config.example.toml` for valid key names. `fn` is not supported.

In the `[settings]` section (all keys optional):

- `sounds = true|false` — play a sound when transcribed text is pasted; default: `true`. (Replaces the removed `STT_SOUNDS` env var.)
- `utterance_gap = <seconds>` — pause length for voice-command boundaries, above 0 up to 10; default: `0.7`. (Replaces the removed `STT_UTTERANCE_GAP` env var.)
- `denoise = "auto"|"on"|"off"` — noise reduction; `"auto"` detects noisy clips; default: `"auto"`. (Replaces the removed `STT_DENOISE` env var; `0`/`1` are now `"off"`/`"on"`.)
- `input_device = <index or "name">` — input device by index or name substring; omit for the macOS default input. (Replaces the removed `STT_INPUT_DEVICE` env var.)

List available devices:

```bash
python3 -c "import sounddevice as sd; print(sd.query_devices())"
```

Common transcription fixes live in `text_cleanup.py`. Filler-word cleanup is always on. The `wpm` and word count logged in `transcriptions.md` reflect what you actually spoke (fillers included) — only the saved text is cleaned.

## Tests

```bash
venv/bin/python -m pip install -r requirements-dev.txt
venv/bin/python -m pytest
```

## Troubleshooting

- **`AttributeError: 'NoneType' object has no attribute 'removeAllDeliveredNotifications'`** — you're running under Anaconda Python. Recreate the venv using Homebrew Python (see Setup).
- **No audio captured / silent recordings** — the terminal app doesn't have microphone permission, _or_ Anaconda Python failed to trigger the TCC prompt. Grant permission manually in System Settings → Privacy & Security → Microphone, then fully quit and reopen the terminal.
- **Hotkey does nothing** — the terminal app doesn't have Accessibility permission. Grant it in System Settings → Privacy & Security → Accessibility and fully restart the terminal.
- **Transcribed text appears in the terminal instead of where you wanted** — the terminal was the focused window when you stopped recording. Click into your target app _before_ pressing the stop hotkey.
