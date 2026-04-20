#!/Users/nirajrajgor/Documents/projects/stt/venv/bin/python3
"""Speech-to-Text: Hold right Option (push-to-talk) OR press Option+Command (toggle). Transcribes, copies to clipboard, saves to markdown."""

import datetime
import os
import re
import threading
import time

import Foundation
import objc

import mlx.core as mx
import numpy as np
import pyperclip
import sounddevice as sd
from parakeet_mlx import from_pretrained
from parakeet_mlx.audio import get_logmel
from pynput import keyboard

NSUserNotification = objc.lookUpClass("NSUserNotification")
NSUserNotificationCenter = objc.lookUpClass("NSUserNotificationCenter")

# --- Whisper config (commented out, replaced by Parakeet) ---
# WHISPER_CLI = "whisper-cli"
# MODEL_PATH = "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-medium.bin"

SAMPLE_RATE = 16000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTIONS_FILE = os.path.join(SCRIPT_DIR, "transcriptions.md")
# Ignore hold durations shorter than this — almost always an accidental tap.
MIN_HOLD_SECONDS = 0.25
# Safety cap for push-to-talk: if macOS drops the key-release event (screen
# lock, fullscreen VM, focus change), this prevents an unbounded recording.
MAX_PTT_SECONDS = 120
PTT_KEY = keyboard.Key.alt_r

# Common transcription corrections (case-insensitive find → replace)
CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
    "Shard CN": "shadcn",
    "superbase": "supabase",
    "at the rate": "@",
    "dot": ".",
    "comma": ","
}

recording = False
audio_frames = []
stream = None
lock = threading.Lock()
pressed_keys = set()
ptt_held = False
ptt_auto_stop_timer = None


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
    for wrong, right in CORRECTIONS.items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    return text


def transcribe(audio_np):
    """Transcribe a numpy audio array directly, bypassing file I/O + ffmpeg."""
    try:
        audio_mx = mx.array(audio_np.flatten())
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

    device = resolve_input_device()
    dev_info = sd.query_devices(device, "input")
    print(f"🎙️  Using input device: {dev_info['name']}")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, callback=callback, device=device
    )
    stream.start()
    notify("STT", "Recording started...")
    print("🎙️  Recording...")



def stop_recording():
    global recording, stream, audio_frames, ptt_auto_stop_timer

    recording = False
    if ptt_auto_stop_timer:
        ptt_auto_stop_timer.cancel()
        ptt_auto_stop_timer = None
    if stream:
        stream.stop()
        stream.close()
        stream = None

    if not audio_frames:
        notify("STT", "No audio captured.")
        print("No audio captured.")
        return

    audio_data = np.concatenate(audio_frames, axis=0)
    # Drop raw chunks now that they're consolidated; the global was keeping
    # them alive until the next recording started.
    audio_frames = []

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
        words = len(text.split())
        wpm = round(words * 60 / duration) if duration > 0 else 0
        notify("STT", f"Pasted, {wpm} WPM.")
        print("✅ Pasted to focused input.")
    else:
        notify("STT", "No speech detected.")
        print("No speech detected.")



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


def main():
    print("=" * 40)
    print("  Speech-to-Text (Parakeet TDT)")
    print("=" * 40)
    print("\n  Push-to-talk: hold Right Option")
    print("  Toggle:       Option + Command (press to start, again to stop)")
    print("  Ctrl+C to quit\n")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    try:
        listener.join()
    except KeyboardInterrupt:
        listener.stop()
        print("\nBye!")


if __name__ == "__main__":
    main()
