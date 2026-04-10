#!/Users/nirajrajgor/Documents/projects/stt/venv/bin/python3
"""Speech-to-Text: Press Option+Command to start/stop a segmented session.

Audio is collected in ~0.5s chunks. An RMS-based silence detector tracks
trailing quiet; whenever >= 2s of silence follows an utterance, the speech
segment is sent through the full-accuracy batch Parakeet transcribe path
and pasted at the cursor. The full session is saved to transcriptions.md
as a single entry when you press the hotkey to stop.
"""

import collections
import datetime
import os
import queue
import re
import tempfile
import threading
import time

import Foundation
import objc

import mlx.core as mx
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
CHUNK_SAMPLES = 8000  # 0.5s per audio chunk

# Silence-gated segmentation.
SILENCE_FLUSH_SECONDS = 2.0
SILENCE_SAMPLES = int(SILENCE_FLUSH_SECONDS * SAMPLE_RATE)
# RMS threshold for treating a chunk as "silence". Tunable via env var for
# different mic profiles. 0.005 sits above typical MacBook built-in mic
# background noise (~0.001–0.003) while still catching quieter speech.
# If you see chunks of real speech being classified [silent], lower this.
# If you see background noise classified [speech], raise it.
SILENCE_RMS_THRESHOLD = float(os.environ.get("STT_SILENCE_RMS", "0.005"))
# Print per-chunk RMS and state transitions. Off by default; enable with
# STT_DEBUG=1 to watch segmentation and transcribe results live.
STT_DEBUG = os.environ.get("STT_DEBUG", "0") != "0"
# Keep a tail of silence when transcribing so end-consonants (/t/, /p/, /k/)
# and sentence-final prosody aren't clipped.
SILENCE_GUARD_SAMPLES = int(0.30 * SAMPLE_RATE)  # 300ms
# Number of silent chunks to retain immediately before speech begins, so the
# segment has a natural lead-in. Parakeet (like most ASR models) transcribes
# short isolated clips worse than the same words with some pre-roll context.
# Each chunk is CHUNK_SAMPLES / SAMPLE_RATE = 0.5s, so 2 → 1s of lead-in.
PRE_SPEECH_CHUNKS = 2
# Drop segments shorter than this — almost certainly a noise burst.
MIN_SPEECH_SAMPLES = int(0.3 * SAMPLE_RATE)  # 300ms

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTIONS_FILE = os.path.join(SCRIPT_DIR, "transcriptions.md")

# Common transcription corrections (case-insensitive find → replace)
CORRECTIONS = {
    "npxcc usage": "npx ccusage",
    "paragate": "parakeet",
    "para kit": "parakeet",
    "para kate": "parakeet",
    "Shard CN": "shadcn",
    "superbase": "supabase"
}

recording = False
stream = None
lock = threading.Lock()
pressed_keys = set()

# Per-session state (reset at the start of every session)
audio_queue: "queue.Queue" = queue.Queue()
stop_event = threading.Event()
worker_thread = None
session_text = ""


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


def transcribe(audio_file):
    """Full-accuracy batch transcribe on a WAV file."""
    try:
        result = parakeet_model.transcribe(audio_file)
        return apply_corrections(result.text.strip())
    finally:
        # parakeet_mlx's transcribe() never clears MLX's buffer cache, so
        # cached intermediates from the largest-ever segment pin memory
        # until process exit. Drop them between calls.
        mx.clear_cache()


def save_to_markdown(text):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## {now}\n\n{text}\n"

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


def paste_text(text):
    """Copy `text` to the clipboard and synthesize Cmd+V at the cursor."""
    if not text:
        return
    pyperclip.copy(text)
    time.sleep(0.05)
    controller = keyboard.Controller()
    controller.press(keyboard.Key.cmd)
    controller.press('v')
    controller.release('v')
    controller.release(keyboard.Key.cmd)


def replace_pasted_text(new_text, char_count):
    """Delete `char_count` characters behind the cursor, then paste `new_text`.

    Assumes the cursor is positioned immediately after the last character
    that was pasted during the session (i.e. the user hasn't moved it).
    """
    controller = keyboard.Controller()
    for _ in range(char_count):
        controller.press(keyboard.Key.backspace)
        controller.release(keyboard.Key.backspace)
    time.sleep(0.05)
    paste_text(new_text)


def chunk_rms(chunk):
    """Root-mean-square of a 1D float32 audio chunk."""
    if len(chunk) == 0:
        return 0.0
    return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))


def transcription_worker():
    """Segment incoming audio on silence and batch-transcribe each segment.

    State machine per chunk:
      - Before any speech: silent chunks are dropped (no buffer growth).
      - After the first speech chunk: everything is appended to `buffer`,
        and `trailing_silence` counts how many trailing samples are silent.
      - When `trailing_silence >= SILENCE_SAMPLES`, flush: trim most of the
        tail silence (keeping SILENCE_GUARD_SAMPLES), write a WAV, run the
        full-accuracy batch transcribe, paste the result, reset state.
      - On stop_event, final-flush any buffered speech regardless of silence.
    """
    global session_text
    session_text = ""

    buffer = []            # list of np.ndarray chunks since start of the utterance
    trailing_silence = 0   # samples of silence at the end of `buffer`
    has_speech = False
    chunk_index = 0
    segment_count = 0      # segments successfully pasted this session
    # Rolling buffer of the most recent silent chunks before speech begins.
    # When the first speech chunk arrives, these get prepended to `buffer`
    # so the segment has real pre-roll instead of starting cold.
    pre_speech = collections.deque(maxlen=PRE_SPEECH_CHUNKS)
    full_audio_chunks = []  # ALL chunks for full-session re-transcription at stop
    pasted_char_count = 0   # total characters pasted, for replacement on refine

    def flush(is_final=False):
        nonlocal buffer, trailing_silence, has_speech, segment_count
        nonlocal pasted_char_count
        global session_text

        if not buffer:
            if STT_DEBUG:
                print("  [flush] empty buffer, skipping")
            return

        audio = np.concatenate(buffer)
        raw_duration = len(audio) / SAMPLE_RATE
        # Trim most of the tail silence; keep a small guard for end consonants.
        if trailing_silence > SILENCE_GUARD_SAMPLES:
            trim_amount = trailing_silence - SILENCE_GUARD_SAMPLES
            audio = audio[:-trim_amount]
        trimmed_duration = len(audio) / SAMPLE_RATE

        if STT_DEBUG:
            print(
                f"  [flush{' FINAL' if is_final else ''}] "
                f"raw={raw_duration:.2f}s trimmed={trimmed_duration:.2f}s "
                f"trailing_silence={trailing_silence/SAMPLE_RATE:.2f}s"
            )

        if len(audio) < MIN_SPEECH_SAMPLES:
            if STT_DEBUG:
                print(
                    f"  [flush] dropping — {trimmed_duration:.2f}s < "
                    f"MIN_SPEECH={MIN_SPEECH_SAMPLES/SAMPLE_RATE:.2f}s"
                )
            buffer = []
            trailing_silence = 0
            has_speech = False
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio, SAMPLE_RATE)
            tmp_path = f.name
        try:
            try:
                text = transcribe(tmp_path)
            except Exception as e:
                print(f"  [flush] transcribe FAILED: {e}")
                text = ""
        finally:
            os.unlink(tmp_path)

        if STT_DEBUG:
            print(f"  [flush] transcribe returned: {text!r}")

        if text:
            # Ensure space separation between consecutive segments.
            if session_text and not session_text.endswith((" ", "\n")):
                delta = " " + text
            else:
                delta = text
            session_text += delta
            if is_final:
                # The user's physical Option+Cmd is likely still held at
                # stop time; let it release before synthesizing Cmd+V so
                # the paste isn't interpreted as Option+Cmd+V.
                time.sleep(0.25)
            paste_text(delta)
            segment_count += 1
            pasted_char_count += len(delta)
            print(f"  ↳ flushed: {delta!r}")
            # Re-post the notification on each mid-session flush so the
            # user gets a periodic visual confirmation that recording is
            # still active. The final flush's notification is handled by
            # the "Session saved." post below, so skip it here.
            if not is_final:
                notify("STT", f"Listening… ({segment_count} pasted)")

        buffer = []
        trailing_silence = 0
        has_speech = False

    try:
        while not stop_event.is_set() or not audio_queue.empty():
            try:
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            chunk_index += 1
            full_audio_chunks.append(chunk)
            rms = chunk_rms(chunk)
            peak = float(np.max(np.abs(chunk))) if len(chunk) else 0.0
            is_silent = rms < SILENCE_RMS_THRESHOLD

            if STT_DEBUG:
                tag = "silent" if is_silent else "SPEECH"
                print(
                    f"  [chunk {chunk_index:3d}] rms={rms:.4f} peak={peak:.4f} "
                    f"{tag} (has_speech={has_speech}, "
                    f"trailing={trailing_silence/SAMPLE_RATE:.2f}s)"
                )

            if is_silent:
                if has_speech:
                    # Trailing silence after an utterance — keep it so we
                    # can measure the pause, but it'll be trimmed at flush.
                    buffer.append(chunk)
                    trailing_silence += len(chunk)
                else:
                    # Pre-speech silence. Retain a short rolling window of
                    # it so the next segment can start with real lead-in.
                    pre_speech.append(chunk)
            else:
                if not has_speech and pre_speech:
                    # First speech chunk of a new segment — prepend the
                    # rolling pre-speech buffer for context.
                    buffer.extend(pre_speech)
                    pre_speech.clear()
                buffer.append(chunk)
                trailing_silence = 0
                has_speech = True

            if has_speech and trailing_silence >= SILENCE_SAMPLES:
                flush()

        if STT_DEBUG:
            print(
                f"  [worker] loop exit. has_speech={has_speech} "
                f"buffer_chunks={len(buffer)} "
                f"buffer_samples={sum(len(c) for c in buffer)}"
            )

        # Stop: final flush of any buffered speech.
        if has_speech:
            flush(is_final=True)

        # --- Full-session refinement ---
        # When the session had multiple segments, re-transcribe the entire
        # audio in one shot (full context → maximum accuracy). If the result
        # differs from the concatenated per-segment transcriptions, delete
        # what was pasted and replace it with the refined version.
        if segment_count > 1 and full_audio_chunks:
            notify("STT", "Refining…")
            print("  ⏳ Refining full session…")
            full_audio = np.concatenate(full_audio_chunks)
            if len(full_audio) >= MIN_SPEECH_SAMPLES:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    sf.write(f.name, full_audio, SAMPLE_RATE)
                    tmp_path = f.name
                try:
                    try:
                        full_text = transcribe(tmp_path)
                    except Exception as e:
                        print(f"  [refine] transcribe FAILED: {e}")
                        full_text = ""
                finally:
                    os.unlink(tmp_path)

                if full_text and full_text != session_text.strip():
                    print(f"  ↳ refined: {full_text!r}")
                    replace_pasted_text(full_text, pasted_char_count)
                    session_text = full_text
                else:
                    print("  ↳ no refinement needed")

        # Free the full audio buffer now that refinement is done.
        full_audio_chunks.clear()
    except Exception as e:
        print(f"Worker error: {e}")
        notify("STT", f"Error: {e}")
        return

    final_text = session_text.strip()
    if final_text:
        save_to_markdown(final_text)
        notify("STT", "Session saved.")
        print(f"✅ Session:\n{final_text}")
    else:
        notify("STT", "No speech detected.")
        print("No speech detected.")


def start_recording():
    global recording, stream, worker_thread

    # Reset per-session state. Drain any stale chunks from a prior session
    # before clearing stop_event so the new worker starts with an empty queue.
    while not audio_queue.empty():
        try:
            audio_queue.get_nowait()
        except queue.Empty:
            break
    stop_event.clear()
    recording = True

    def callback(indata, frames, time_info, status):
        # sd audio thread — must return fast. put_nowait is thread-safe.
        if recording:
            audio_queue.put_nowait(indata.copy().flatten())

    device = resolve_input_device()
    dev_info = sd.query_devices(device, "input")
    print(f"🎙️  Using input device: {dev_info['name']}")

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        callback=callback,
        device=device,
        blocksize=CHUNK_SAMPLES,
    )
    stream.start()

    worker_thread = threading.Thread(target=transcription_worker, daemon=True)
    worker_thread.start()

    notify("STT", "Recording started...")
    print("🎙️  Recording...")


def stop_recording():
    global recording, stream, worker_thread

    recording = False
    if stream:
        stream.stop()
        stream.close()
        stream = None

    # Tell the worker to drain and exit, then wait for it. Joining here means
    # by the time the hotkey lock releases, the final paste + markdown save
    # have completed — so a rapid second hotkey press can't race the previous
    # session's cleanup.
    stop_event.set()
    if worker_thread is not None:
        worker_thread.join()
        worker_thread = None


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
    print(f"  Pastes after each ~{SILENCE_FLUSH_SECONDS:g}s pause")
    print("  Press again to stop and save the session")
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
