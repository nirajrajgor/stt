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
2. **Accessibility** — for your terminal app. Needed so the global hotkeys and the simulated `Cmd+V` paste work.

After granting either permission, **fully quit and reopen the terminal** (`Cmd+Q`, not just close the window) for it to take effect.

## Usage

```bash
source venv/bin/activate   # if not already active
./stt.py
```

Click into the app/field where you want the text to land, then use either:

- **Push-to-talk**: hold **Right Option**, speak, release. Auto-stops after 120s as a safety cap.
- **Toggle**: press **Option + Command** to start, press again to stop.

The transcription is copied to your clipboard and auto-pasted into the focused input.

Transcriptions are also appended to `transcriptions.md` in the project directory.

## Stats

Each entry's heading logs duration, word count, and WPM:

```
## 2026-04-14 15:42:08 (4.2s, 18w, 257 wpm)
```

From this you can derive:

- Words spoken per day / week
- Average and peak WPM
- Total time spent dictating
- Usage cadence (entries per day, time-of-day patterns)

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

Common transcription fixes live in two dictionaries at the top of `stt.py`:

- `WORD_CORRECTIONS` — straight word-for-word swaps (e.g. `"paragate" → "parakeet"`).
- `PUNCT_CORRECTIONS` — spoken punctuation that fuses adjacent tokens (e.g. `"search hyphen bar dot tsx" → "search-bar.tsx"`).

Add your own entries to either as needed.

### Noise suppression

If background music or ambient noise is bleeding into the mic, the transcription can pick up phantom words. The script runs spectral-gating noise reduction (`noisereduce`) before transcribing, gated by an auto-detect on the clip's noise floor — so it only fires when it's actually needed. When it runs, you'll see `🔇 Denoising (noise floor 0.XXXX)` in the terminal.

Override with `STT_DENOISE`:

```bash
STT_DENOISE=0 ./stt.py     # force off — best for clean rooms; preserves plosive sounds (e.g. "blink")
STT_DENOISE=1 ./stt.py     # force on — for persistent background noise
# unset (default):         # auto — denoises only when noise floor exceeds threshold
```

Trade-off: aggressive denoising can eat short plosives (`/b/`, `/p/`, `/t/`), turning "blink" into "link". The auto-detect avoids this in clean environments, but if you notice initial consonants disappearing, try `STT_DENOISE=0`.

## Troubleshooting

- **`AttributeError: 'NoneType' object has no attribute 'removeAllDeliveredNotifications'`** — you're running under Anaconda Python. Recreate the venv using Homebrew Python (see Setup).
- **No audio captured / silent recordings** — the terminal app doesn't have microphone permission, *or* Anaconda Python failed to trigger the TCC prompt. Grant permission manually in System Settings → Privacy & Security → Microphone, then fully quit and reopen the terminal.
- **Hotkey does nothing** — the terminal app doesn't have Accessibility permission. Grant it in System Settings → Privacy & Security → Accessibility and fully restart the terminal.
- **Transcribed text appears in the terminal instead of where you wanted** — the terminal was the focused window when you stopped recording. Click into your target app *before* pressing the stop hotkey.
