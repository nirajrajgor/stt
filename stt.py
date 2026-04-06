#!/Users/nirajrajgor/Documents/projects/stt/venv/bin/python3
"""Speech-to-Text: Press Option+Command to start/stop recording. Transcribes, copies to clipboard, saves to markdown."""

import datetime
import os
import re
import tempfile
import threading
import time

import Foundation
import objc

import numpy as np
import pyperclip
import sounddevice as sd
import soundfile as sf
from parakeet_mlx import from_pretrained
from pynput import keyboard

NSUserNotification = objc.lookUpClass("NSUserNotification")
NSUserNotificationCenter = objc.lookUpClass("NSUserNotificationCenter")

# --- Whisper config (commented out, replaced by Parakeet) ---
# WHISPER_CLI = "whisper-cli"
# MODEL_PATH = "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-medium.bin"

SAMPLE_RATE = 16000
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTIONS_FILE = os.path.join(SCRIPT_DIR, "transcriptions.md")

# Common transcription corrections (case-insensitive find → replace)
CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
}

recording = False
audio_frames = []
stream = None
lock = threading.Lock()
pressed_keys = set()


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
print("Model loaded.")


def apply_corrections(text):
    for wrong, right in CORRECTIONS.items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    return text


def transcribe(audio_file):
    result = parakeet_model.transcribe(audio_file)
    return apply_corrections(result.text.strip())


def save_to_markdown(text):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {now}\n\n{text}\n"

    # Create file with header if it doesn't exist
    if not os.path.exists(TRANSCRIPTIONS_FILE):
        with open(TRANSCRIPTIONS_FILE, "w") as f:
            f.write("# Transcriptions\n")

    with open(TRANSCRIPTIONS_FILE, "a") as f:
        f.write(entry)


def start_recording():
    global recording, audio_frames, stream

    audio_frames = []
    recording = True

    def callback(indata, frames, time, status):
        if recording:
            audio_frames.append(indata.copy())

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback)
    stream.start()
    notify("STT", "Recording started...")
    print("🎙️  Recording...")



def stop_recording():
    global recording, stream

    recording = False
    if stream:
        stream.stop()
        stream.close()
        stream = None

    if not audio_frames:
        notify("STT", "No audio captured.")
        print("No audio captured.")
        return

    notify("STT", "Transcribing...")
    print("⏳ Transcribing...")

    audio_data = np.concatenate(audio_frames, axis=0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, audio_data, SAMPLE_RATE)
        tmp_path = f.name

    text = transcribe(tmp_path)
    os.unlink(tmp_path)

    if text:
        pyperclip.copy(text)
        time.sleep(0.05)
        controller = keyboard.Controller()
        controller.press(keyboard.Key.cmd)
        controller.press('v')
        controller.release('v')
        controller.release(keyboard.Key.cmd)
        save_to_markdown(text)
        notify("STT", "Pasted to clipboard.")
        print(f"✅ Pasted to focused input:\n{text}")
    else:
        notify("STT", "No speech detected.")
        print("No speech detected.")



def on_hotkey_toggle():
    with lock:
        if recording:
            stop_recording()
        else:
            start_recording()


def on_press(key):
    if key in (keyboard.Key.alt_l, keyboard.Key.cmd):
        pressed_keys.add(key)
        if keyboard.Key.alt_l in pressed_keys and keyboard.Key.cmd in pressed_keys:
            pressed_keys.clear()
            threading.Thread(target=on_hotkey_toggle, daemon=True).start()


def on_release(key):
    pressed_keys.discard(key)


def main():
    print("=" * 40)
    print("  Speech-to-Text (Parakeet TDT)")
    print("=" * 40)
    print("\n  Hotkey: Option + Command")
    print("  Press to start recording")
    print("  Press again to stop & transcribe")
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
