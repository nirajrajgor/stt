#!/usr/bin/env python3
"""Speech-to-Text: Hold right Option (push-to-talk) OR press Option+Command (toggle). Transcribes, copies to clipboard, saves to markdown."""

import datetime
import faulthandler
import os
import queue
import re
import signal
import sys
import threading
import time
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.executable) != VENV_PYTHON:
    os.execv(VENV_PYTHON, [VENV_PYTHON, os.path.abspath(__file__), *sys.argv[1:]])

import Foundation
import objc

import mlx.core as mx
import noisereduce as nr
import numpy as np
import pyperclip
import sounddevice as sd
from parakeet_mlx import from_pretrained
from parakeet_mlx.audio import get_logmel
from pynput import keyboard

import overlay

NSUserNotification = objc.lookUpClass("NSUserNotification")
NSUserNotificationCenter = objc.lookUpClass("NSUserNotificationCenter")
NSSound = objc.lookUpClass("NSSound")

# --- Whisper config (commented out, replaced by Parakeet) ---
# WHISPER_CLI = "whisper-cli"
# MODEL_PATH = "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-medium.bin"

SAMPLE_RATE = 16000
TRANSCRIPTIONS_FILE = os.path.join(SCRIPT_DIR, "transcriptions.md")
LOG_FILE = os.path.join(SCRIPT_DIR, "stt.log")
# Spectral-gating noise reduction before transcribe.
#   STT_DENOISE=auto (default): fire only when the clip's noise floor looks
#     elevated (music/ambient bleed). Clean rooms keep plosive fidelity.
#   STT_DENOISE=1: always on.
#   STT_DENOISE=0: always off.
_DENOISE_MODE = os.environ.get("STT_DENOISE", "auto").lower()
# RMS of the quietest 10% of 20 ms frames. Tuned against a MacBook Air built-in
# mic — clean speech sits around 0.003–0.008; music bleed pushes it above ~0.02.
NOISE_FLOOR_THRESHOLD = 0.015
# Ignore hold durations shorter than this — almost always an accidental tap.
MIN_HOLD_SECONDS = 0.25
# Safety cap for push-to-talk: if macOS drops the key-release event (screen
# lock, fullscreen VM, focus change), this prevents an unbounded recording.
MAX_PTT_SECONDS = 360
PTT_KEY = keyboard.Key.alt_r

# Audio cue on paste complete. Set STT_SOUNDS=0 to disable.
SOUNDS_ENABLED = os.environ.get("STT_SOUNDS", "1") != "0"
END_SOUND = "Pop"

# Word-for-word transcription fixes (case-insensitive, word-boundary match).
WORD_CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
    "Shard CN": "shadcn",
    "superbase": "supabase",
}

# Spoken punctuation: eat surrounding whitespace so tokens fuse, e.g.
# "search hyphen bar dot tsx" → "search-bar.tsx".
PUNCT_CORRECTIONS = {
    "at the rate": "@",
    "hyphen": "-",
    "underscore": "_",
    "dot": ".",
    "comma": ",",
    "slash": "/",
}

recording = False
audio_frames = []
stream = None
lock = threading.Lock()
pressed_keys = set()
ptt_held = False
ptt_auto_stop_timer = None
shutting_down = False

# Single-consumer queue so a slow transcription can't block the hotkey lock
# or Ctrl+C, and concurrent clips don't race on the Parakeet model.
_transcribe_queue = queue.Queue()


class _TimestampedTee:
    """Mirror writes to a terminal stream and a log file, prepending a
    timestamp to each line in the log."""

    def __init__(self, term, log_fh):
        self._term = term
        self._log = log_fh
        self._buf = ""

    def write(self, s):
        self._term.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._log.write(f"[{ts}] {line}\n")

    def flush(self):
        self._term.flush()
        self._log.flush()


def _setup_logging():
    """Tee stdout/stderr to stt.log with timestamps and wire faulthandler.

    SIGUSR1 dumps every thread's stack to the log — run `kill -USR1 <pid>`
    from another terminal when the app appears stuck.
    """
    log_fh = open(LOG_FILE, "a", buffering=1)
    log_fh.write(
        f"\n=== stt.py started {datetime.datetime.now().isoformat(timespec='seconds')} "
        f"pid={os.getpid()} ===\n"
    )
    sys.stdout = _TimestampedTee(sys.stdout, log_fh)
    sys.stderr = _TimestampedTee(sys.stderr, log_fh)
    faulthandler.enable(file=log_fh)
    faulthandler.register(signal.SIGUSR1, file=log_fh, all_threads=True)
    return log_fh


_log_fh = _setup_logging()


def notify(title, message):
    """Show a macOS notification."""
    center = NSUserNotificationCenter.defaultUserNotificationCenter()
    if center is None:
        # NSUserNotificationCenter is unavailable (e.g. not running from a
        # bundled .app, or deprecated on this macOS/Python build). Skip.
        return
    # Remove previous notifications so they don't pile up
    center.removeAllDeliveredNotifications()
    n = NSUserNotification.alloc().init()
    n.setTitle_(title)
    n.setInformativeText_(message)
    center.deliverNotification_(n)


# --- Whisper transcribe (commented out, replaced by Parakeet) ---
# def transcribe(audio_file):
#     result = subprocess.run(
#         [WHISPER_CLI, "-m", MODEL_PATH, "-f", audio_file, "--no-timestamps"],
#         capture_output=True,
#         text=True,
#     )
#     lines = [l.strip() for l in result.stdout.strip().splitlines() if l.strip()]
#     return " ".join(lines)

# --- Parakeet MLX ---
print("Loading Parakeet TDT 0.6B v2 model...")
parakeet_model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v2")
# Cap MLX's buffer cache so it reclaims instead of growing unboundedly with
# the longest transcription. 512 MB is plenty for intermediate tensors.
mx.set_cache_limit(512 * 1024 * 1024)
print("Model loaded.")


def apply_corrections(text):
    for wrong, right in WORD_CORRECTIONS.items():
        text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
    for wrong, right in PUNCT_CORRECTIONS.items():
        # [,.;]? eats the stray comma/period Parakeet adds when the speaker
        # pauses after a punctuation word (e.g. "at the rate, transcription.md"
        # → "@transcription.md" instead of "@, transcription.md").
        text = re.sub(
            rf"\s*\b{re.escape(wrong)}\b[,.;]?\s*",
            right,
            text,
            flags=re.IGNORECASE,
        )
    # Parakeet tacks a sentence-end "." on silence. When the last token is a
    # filename/URL ("...md.", "...tsx.", "...com."), drop that trailing dot.
    # Gated on an extension-like prefix so prose sentences keep their period.
    text = re.sub(r"(\.[a-z0-9]{1,6})\.\s*$", r"\1", text, flags=re.IGNORECASE)
    return text


def _noise_floor(audio):
    """10th-percentile RMS across 20 ms frames — a cheap proxy for ambient noise."""
    frame = int(SAMPLE_RATE * 0.02)
    trimmed = audio[: len(audio) // frame * frame]
    if len(trimmed) < frame:
        return 0.0
    frames = trimmed.reshape(-1, frame)
    frame_rms = np.sqrt(np.mean(frames ** 2, axis=1))
    return float(np.percentile(frame_rms, 10))


def _should_denoise(noise_floor):
    if _DENOISE_MODE == "0":
        return False
    if _DENOISE_MODE == "1":
        return True
    return noise_floor > NOISE_FLOOR_THRESHOLD


def transcribe(audio_np):
    """Transcribe a numpy audio array directly, bypassing file I/O + ffmpeg."""
    try:
        audio_flat = audio_np.flatten().astype(np.float32)
        floor = _noise_floor(audio_flat)
        if _should_denoise(floor):
            # Non-stationary spectral gating so the noise profile tracks music
            # that evolves over time rather than assuming a fixed hum.
            print(f"🔇 Denoising (noise floor {floor:.4f})")
            audio_flat = nr.reduce_noise(
                y=audio_flat, sr=SAMPLE_RATE, stationary=False
            )
        audio_mx = mx.array(audio_flat)
        mel = get_logmel(audio_mx, parakeet_model.preprocessor_config)
        result = parakeet_model.generate(mel)[0]
        return apply_corrections(result.text.strip())
    finally:
        # parakeet_mlx's non-streaming transcribe() never clears MLX's buffer
        # cache, so cached intermediates from the largest-ever audio clip pin
        # GB of memory until process exit. Drop them between calls.
        mx.clear_cache()


def save_to_markdown(text, duration):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    words = len(text.split())
    wpm = round(words * 60 / duration) if duration > 0 else 0
    entry = f"\n## {now} ({duration:.1f}s, {words}w, {wpm} wpm)\n\n{text}\n"

    # Create file with header if it doesn't exist
    if not os.path.exists(TRANSCRIPTIONS_FILE):
        with open(TRANSCRIPTIONS_FILE, "w") as f:
            f.write("# Transcriptions\n")

    with open(TRANSCRIPTIONS_FILE, "a") as f:
        f.write(entry)


def resolve_input_device():
    """Pick the input device to record from.

    Priority:
      1. STT_INPUT_DEVICE env var — either an integer index or a case-insensitive
         substring match against a device name (e.g. "webcam", "macbook").
      2. The current system default input device.
    """
    override = os.environ.get("STT_INPUT_DEVICE")
    if override:
        try:
            return int(override)
        except ValueError:
            needle = override.lower()
            for idx, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                    return idx
            print(
                f"⚠️  STT_INPUT_DEVICE='{override}' not found; "
                "falling back to system default."
            )
    # None tells sounddevice to use the current system default input.
    return None


def start_recording():
    global recording, audio_frames, stream

    audio_frames = []
    recording = True

    def callback(indata, frames, time, status):
        if recording:
            audio_frames.append(indata.copy())
            overlay.push_amplitude(float(np.sqrt(np.mean(indata ** 2))))

    device = resolve_input_device()
    dev_info = sd.query_devices(device, "input")
    print(f"🎙️  Using input device: {dev_info['name']}")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, callback=callback, device=device
    )
    stream.start()
    overlay.show()
    print("🎙️  Recording...")



def stop_recording():
    """Flip state and hand the captured frames to the worker. Call with `lock` held."""
    global recording, stream, audio_frames, ptt_auto_stop_timer

    if not recording:
        return

    recording = False
    overlay.hide()
    if ptt_auto_stop_timer:
        ptt_auto_stop_timer.cancel()
        ptt_auto_stop_timer = None

    frames = audio_frames
    strm = stream
    audio_frames = []
    stream = None

    _transcribe_queue.put((frames, strm))


def _finish_recording(frames, strm):
    """Heavy post-recording work. Runs on the worker thread, never under `lock`."""
    if strm is not None:
        try:
            strm.stop()
            strm.close()
        except Exception:
            traceback.print_exc()

    if not frames:
        notify("STT", "No audio captured.")
        print("No audio captured.")
        return

    audio_data = np.concatenate(frames, axis=0)
    duration = len(audio_data) / SAMPLE_RATE

    # Short clips are almost always an accidental push-to-talk tap.
    if duration < MIN_HOLD_SECONDS:
        print(f"⏭️  Discarded {duration:.2f}s clip (too short).")
        return

    print("⏳ Transcribing...")

    # Transcribe directly from memory — no temp file / ffmpeg round-trip.
    text = transcribe(audio_data)

    if text:
        pyperclip.copy(text)
        time.sleep(0.01)
        controller = keyboard.Controller()
        controller.press(keyboard.Key.cmd)
        controller.press('v')
        controller.release('v')
        controller.release(keyboard.Key.cmd)
        threading.Thread(target=save_to_markdown, args=(text, duration), daemon=True).start()
        if SOUNDS_ENABLED and (s := NSSound.soundNamed_(END_SOUND)):
            s.play()
        words = len(text.split())
        wpm = round(words * 60 / duration) if duration > 0 else 0
        print(f"✅ Pasted to focused input ({wpm} WPM).")
    else:
        notify("STT", "No speech detected.")
        print("No speech detected.")


def _transcription_worker():
    """Single consumer. Serializes Parakeet calls and preserves paste order."""
    while True:
        frames, strm = _transcribe_queue.get()
        try:
            _finish_recording(frames, strm)
        except Exception:
            traceback.print_exc()



def on_hotkey_toggle():
    with lock:
        if recording:
            stop_recording()
        else:
            start_recording()


def on_ptt_press():
    global ptt_auto_stop_timer
    with lock:
        if not recording:
            start_recording()
            ptt_auto_stop_timer = threading.Timer(MAX_PTT_SECONDS, _ptt_auto_stop)
            ptt_auto_stop_timer.daemon = True
            ptt_auto_stop_timer.start()


def on_ptt_release():
    with lock:
        if recording:
            stop_recording()


def _ptt_auto_stop():
    """Fail-safe if macOS drops the right-Option release event."""
    global ptt_held
    with lock:
        if recording:
            print(f"⏱  PTT auto-stopped after {MAX_PTT_SECONDS}s (stuck hotkey?).")
            # Clear the held flag so the user's eventual (late) release is a
            # no-op and the next press re-arms cleanly.
            ptt_held = False
            stop_recording()


def on_press(key):
    global ptt_held
    # Push-to-talk: hold right Option. Guard against auto-repeat re-firing
    # start while the key is already held.
    if key == PTT_KEY and not ptt_held:
        ptt_held = True
        threading.Thread(target=on_ptt_press, daemon=True).start()
        return

    # Toggle: Option+Command. Use left Option specifically so right Option
    # stays exclusive to push-to-talk.
    if key in (keyboard.Key.alt_l, keyboard.Key.cmd):
        pressed_keys.add(key)
        if keyboard.Key.alt_l in pressed_keys and keyboard.Key.cmd in pressed_keys:
            pressed_keys.clear()
            threading.Thread(target=on_hotkey_toggle, daemon=True).start()


def on_release(key):
    global ptt_held
    if key == PTT_KEY and ptt_held:
        ptt_held = False
        threading.Thread(target=on_ptt_release, daemon=True).start()
        return
    pressed_keys.discard(key)


def _watch_listener(listener):
    try:
        listener.join()
    except Exception as exc:
        if shutting_down:
            return
        print(f"❌ Hotkey listener failed: {exc}")
        notify("STT", "Hotkey listener failed. Exiting.")
        overlay.stop()
        return

    if not shutting_down:
        print("❌ Hotkey listener stopped unexpectedly.")
        notify("STT", "Hotkey listener stopped. Exiting.")
        overlay.stop()


def main():
    global shutting_down
    print("=" * 40)
    print("  Speech-to-Text (Parakeet TDT)")
    print("=" * 40)
    print("\n  Push-to-talk: hold Right Option")
    print("  Toggle:       Option + Command (press to start, again to stop)")
    print("  Ctrl+C to quit\n")

    shutting_down = False
    overlay.start()
    threading.Thread(target=_transcription_worker, daemon=True).start()
    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    listener.wait()
    threading.Thread(target=_watch_listener, args=(listener,), daemon=True).start()
    try:
        overlay.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutting_down = True
        listener.stop()
        try:
            listener.join(1.0)
        except Exception:
            pass
        print("\nBye!")


if __name__ == "__main__":
    main()
