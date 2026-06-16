#!/usr/bin/env python3
"""Speech-to-Text: Hold right Option (push-to-talk) OR press Option+Command (toggle). Transcribes, pastes into the focused app (preserving your clipboard), saves to markdown."""

import datetime
import faulthandler
import json
import os
import queue
import select
import signal
import subprocess
import sys
import threading
import tempfile
import time
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.executable) != VENV_PYTHON:
    os.execv(VENV_PYTHON, [VENV_PYTHON, os.path.abspath(__file__), *sys.argv[1:]])

import Foundation
import objc
from AppKit import NSPasteboardTypeString, NSWorkspace
import numpy as np
from pynput import keyboard

import config
import hotkeys
import overlay
import recorder
from transcriber import SAMPLE_RATE, Transcriber

NSUserNotification = objc.lookUpClass("NSUserNotification")
NSUserNotificationCenter = objc.lookUpClass("NSUserNotificationCenter")
NSSound = objc.lookUpClass("NSSound")
NSPasteboard = objc.lookUpClass("NSPasteboard")

# --- Whisper config (commented out, replaced by Parakeet) ---
# WHISPER_CLI = "whisper-cli"
# MODEL_PATH = "/opt/homebrew/Cellar/whisper-cpp/1.8.4/share/whisper-cpp/ggml-medium.bin"

TRANSCRIPTIONS_FILE = os.path.join(SCRIPT_DIR, "transcriptions.md")
LOG_FILE = os.path.join(SCRIPT_DIR, "stt.log")
RECORDER_WORKER = os.path.join(SCRIPT_DIR, "recorder_worker.py")

# Env vars that moved into [settings] of stt.config.toml and no longer work.
_RETIRED_ENV_VARS = {
    "STT_SOUNDS": "sounds",
    "STT_UTTERANCE_GAP": "utterance_gap",
    "STT_DENOISE": "denoise",
    "STT_INPUT_DEVICE": "input_device",
}


def _load_config_data():
    try:
        return config.load_config_data(), None
    except config.ConfigError as exc:
        return {}, exc


def _load_settings(config_data, config_error):
    for var, key in _RETIRED_ENV_VARS.items():
        if var in os.environ:
            print(
                f"Warning: {var} no longer has any effect. "
                f'Set "{key}" in {config.CONFIG_PATH.name} instead.',
                file=sys.stderr,
            )
    try:
        if config_error is not None:
            raise config_error
        return config.parse_settings(config_data)
    except config.ConfigError as exc:
        print(exc, file=sys.stderr)
        print("Using default settings.", file=sys.stderr)
        return config.Settings()


# Ignore hold durations shorter than this — almost always an accidental tap.
MIN_HOLD_SECONDS = 0.25
# Safety cap for push-to-talk: if macOS drops the key-release event (screen
# lock, fullscreen VM, focus change), this prevents an unbounded recording.
MAX_PTT_SECONDS = 360

END_SOUND = "Pop"
# Parent waits this long for the child process to either open the mic or fail.
RECORDER_READY_TIMEOUT = float(os.environ.get("STT_RECORDER_READY_TIMEOUT", "3.0"))
# After stop, the child saves audio before attempting risky CoreAudio cleanup.
RECORDER_STOP_TIMEOUT = float(os.environ.get("STT_RECORDER_STOP_TIMEOUT", "2.0"))

recording = False
recording_mode = None
recorder_proc = None
recorder_output_path = None
lock = threading.Lock()
pressed_keys = set()
ptt_held = False
toggle_state = hotkeys.ToggleChordState()
ptt_auto_stop_timer = None
shutting_down = False

# Single-consumer queue so a slow transcription can't block the hotkey lock
# or Ctrl+C, and concurrent clips don't race on the Parakeet model.
_transcribe_queue = queue.Queue()
_hotkey_queue = queue.Queue()


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

# After the log tee, so config errors and retired-env warnings reach stt.log.
_CONFIG_DATA, _CONFIG_ERROR = _load_config_data()
_SETTINGS = _load_settings(_CONFIG_DATA, _CONFIG_ERROR)
# Audio cue on paste complete. Set sounds = false in [settings] to disable.
SOUNDS_ENABLED = _SETTINGS.sounds
# Owns the model plus the settings-derived utterance_gap and denoise behavior.
_TRANSCRIBER = Transcriber(_SETTINGS)


def _load_hotkey_bindings(config_data, config_error):
    try:
        if config_error is not None:
            raise config_error
        return hotkeys.parse_hotkey_bindings(config_data)
    except config.ConfigError as exc:
        print(exc, file=sys.stderr)
        return None


HOTKEY_BINDINGS = None


def paste_text(text):
    pb = NSPasteboard.generalPasteboard()
    prev = pb.stringForType_(NSPasteboardTypeString)

    # nspasteboard.org marker — clipboard managers that honor this UTI skip
    # the entry instead of writing it to history.
    pb.clearContents()
    pb.setString_forType_("", "org.nspasteboard.ConcealedType")
    pb.setString_forType_(text, NSPasteboardTypeString)

    kb = keyboard.Controller()
    kb.press(keyboard.Key.cmd)
    kb.press('v')
    kb.release('v')
    kb.release(keyboard.Key.cmd)

    # Skip restore if the user copied something new or another transcription
    # already pasted — either case would otherwise clobber fresh content.
    def _restore():
        if prev is not None and pb.stringForType_(NSPasteboardTypeString) == text:
            pb.clearContents()
            pb.setString_forType_(prev, NSPasteboardTypeString)

    t = threading.Timer(0.5, _restore)
    t.daemon = True
    t.start()


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

def save_to_markdown(text, words, duration):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wpm = round(words * 60 / duration) if duration > 0 else 0
    entry = f"\n## {now} ({duration:.1f}s, {words}w, {wpm} wpm)\n\n{text}\n"

    # Create file with header if it doesn't exist
    if not os.path.exists(TRANSCRIPTIONS_FILE):
        with open(TRANSCRIPTIONS_FILE, "w") as f:
            f.write("# Transcriptions\n")

    with open(TRANSCRIPTIONS_FILE, "a") as f:
        f.write(entry)


def _safe_unlink(path):
    if not path:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except Exception:
        traceback.print_exc()


def _terminate_recorder(proc, grace=0.5):
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            proc.wait(timeout=grace)
        except Exception:
            traceback.print_exc()
    except Exception:
        traceback.print_exc()


def _recorder_log_tail(lines):
    if not lines:
        return ""
    return " Last recorder output: " + " | ".join(lines[-4:])


def _handle_recorder_event(event):
    kind = event.get(recorder.EVENT_KEY)
    if kind == recorder.EVENT_AMPLITUDE:
        overlay.push_amplitude(float(event.get("level", 0.0)))
    elif kind == recorder.EVENT_WARNING:
        print(f"⚠️  {event.get('message')}")
    elif kind == recorder.EVENT_ERROR:
        print(f"⚠️  Recorder error: {event.get('message')}")


def _watch_recorder_output(proc):
    if proc.stdout is None:
        return
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line)
                continue
            _handle_recorder_event(event)
    except Exception:
        traceback.print_exc()


def _start_recorder_process():
    out = tempfile.NamedTemporaryFile(prefix="stt-audio-", suffix=".npy", delete=False)
    out_path = out.name
    out.close()

    child_env = recorder.child_env(os.environ, _SETTINGS.input_device)

    proc = subprocess.Popen(
        [sys.executable, RECORDER_WORKER, out_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=child_env,
    )
    lines = []
    deadline = time.monotonic() + RECORDER_READY_TIMEOUT

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            if proc.stdout is not None:
                remaining = proc.stdout.read()
                if remaining:
                    lines.extend(remaining.splitlines())
            _safe_unlink(out_path)
            raise RuntimeError(
                "microphone recorder exited before it was ready."
                + _recorder_log_tail(lines)
            )

        readable, _, _ = select.select([proc.stdout], [], [], 0.05)
        if not readable:
            continue

        line = proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)
            continue

        kind = event.get(recorder.EVENT_KEY)
        if kind == recorder.EVENT_READY:
            threading.Thread(
                target=_watch_recorder_output, args=(proc,), daemon=True
            ).start()
            return proc, out_path, event.get("device", "default input")
        if kind == recorder.EVENT_WARNING:
            print(f"⚠️  {event.get('message')}")
            continue
        if kind == recorder.EVENT_ERROR:
            _terminate_recorder(proc)
            _safe_unlink(out_path)
            raise RuntimeError(
                f"microphone recorder failed: {event.get('message')}"
                + _recorder_log_tail(lines)
            )
        lines.append(line)

    _terminate_recorder(proc)
    _safe_unlink(out_path)
    raise TimeoutError(
        f"microphone recorder did not start within {RECORDER_READY_TIMEOUT:.1f}s; "
        "killed child process to release the mic."
        + _recorder_log_tail(lines)
    )


def _request_recorder_stop(proc, cancel=False):
    if proc is None or proc.poll() is not None or proc.stdin is None:
        return
    try:
        command = recorder.COMMAND_CANCEL if cancel else recorder.COMMAND_STOP
        proc.stdin.write(f"{command}\n")
        proc.stdin.flush()
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _discard_recorder_process(proc, out_path):
    _request_recorder_stop(proc, cancel=True)
    try:
        proc.wait(timeout=0.75)
    except subprocess.TimeoutExpired:
        _terminate_recorder(proc)
    except Exception:
        traceback.print_exc()
    finally:
        _safe_unlink(out_path)


def _collect_recorder_audio(proc, out_path):
    try:
        proc.wait(timeout=RECORDER_STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        print(
            f"⚠️  Recorder child did not exit within {RECORDER_STOP_TIMEOUT:.1f}s; "
            "killing it to release the mic."
        )
        _terminate_recorder(proc)
    except Exception:
        traceback.print_exc()

    try:
        if out_path and os.path.exists(out_path):
            return np.load(out_path)
    finally:
        _safe_unlink(out_path)

    return np.empty((0, 1), dtype=np.float32)


def start_recording(mode):
    global recording, recording_mode, recorder_proc, recorder_output_path

    try:
        proc, out_path, device_name = _start_recorder_process()
    except Exception:
        overlay.hide()
        notify("STT", "Microphone failed to start; recorder child was killed.")
        raise

    recording = True
    recording_mode = mode
    recorder_proc = proc
    recorder_output_path = out_path
    overlay.show()
    print(f"🎙️  Using input device: {device_name}")
    print("🎙️  Recording...")


def stop_recording(expected_mode=None, discard=False):
    """Detach the child recorder and hand it to the worker; call with `lock` held."""
    global recording, recording_mode, recorder_proc, recorder_output_path, ptt_auto_stop_timer

    if not recording:
        return False
    if expected_mode is not None and recording_mode != expected_mode:
        return False

    recording = False
    recording_mode = None
    overlay.hide()
    if ptt_auto_stop_timer:
        ptt_auto_stop_timer.cancel()
        ptt_auto_stop_timer = None

    proc = recorder_proc
    out_path = recorder_output_path
    recorder_proc = None
    recorder_output_path = None

    if discard:
        threading.Thread(
            target=_discard_recorder_process, args=(proc, out_path), daemon=True
        ).start()
        print("🛑 Recording cancelled.")
    else:
        _request_recorder_stop(proc)
        _transcribe_queue.put((proc, out_path))
    return True


def _finish_recording(audio_data):
    """Heavy post-recording work. Runs on the worker thread."""
    if audio_data is None or len(audio_data) == 0:
        notify("STT", "No audio captured.")
        print("No audio captured.")
        return

    duration = len(audio_data) / SAMPLE_RATE

    # Short clips are almost always an accidental push-to-talk tap.
    if duration < MIN_HOLD_SECONDS:
        print(f"⏭️  Discarded {duration:.2f}s clip (too short).")
        return

    print("⏳ Transcribing...")

    # Transcribe directly from memory — no temp file / ffmpeg round-trip.
    raw_text, text = _TRANSCRIBER.transcribe(audio_data)

    if text:
        paste_text(text)
        words = len(raw_text.split())
        threading.Thread(target=save_to_markdown, args=(text, words, duration), daemon=True).start()
        if SOUNDS_ENABLED and (s := NSSound.soundNamed_(END_SOUND)):
            s.play()
        wpm = round(words * 60 / duration) if duration > 0 else 0
        print(f"✅ Pasted to focused input ({wpm} WPM).")
    else:
        notify("STT", "No speech detected.")
        print("No speech detected.")


def _transcription_worker():
    """Single consumer. Serializes Parakeet calls and preserves paste order."""
    while True:
        proc, out_path = _transcribe_queue.get()
        try:
            audio_data = _collect_recorder_audio(proc, out_path)
            _finish_recording(audio_data)
        except Exception:
            traceback.print_exc()


class _SleepObserver(Foundation.NSObject):
    """Quits the app when macOS is about to sleep."""

    def willSleep_(self, _notification):
        print("💤 System sleeping — cancelling recording and exiting.")
        with lock:
            stop_recording(discard=True)
        overlay.stop()


def on_hotkey_toggle():
    with lock:
        if not recording:
            start_recording("toggle")
        elif recording_mode == "toggle":
            stop_recording("toggle")


def _hotkey_worker():
    """Single consumer for hotkey actions so press/release order is preserved."""
    while True:
        action = _hotkey_queue.get()
        try:
            if action == "toggle":
                on_hotkey_toggle()
            elif action == "ptt_press":
                on_ptt_press()
            elif action == "ptt_release":
                on_ptt_release()
            else:
                print(f"⚠️  Unknown hotkey action: {action}")
        except Exception:
            traceback.print_exc()


def on_ptt_press():
    global ptt_auto_stop_timer
    with lock:
        if not recording:
            start_recording("ptt")
            ptt_auto_stop_timer = threading.Timer(MAX_PTT_SECONDS, _ptt_auto_stop)
            ptt_auto_stop_timer.daemon = True
            ptt_auto_stop_timer.start()


def on_ptt_release():
    with lock:
        if recording_mode == "ptt":
            stop_recording("ptt")


def _ptt_auto_stop():
    """Fail-safe if macOS drops the right-Option release event."""
    global ptt_held
    with lock:
        if recording and recording_mode == "ptt":
            print(f"⏱  PTT auto-stopped after {MAX_PTT_SECONDS}s (stuck hotkey?).")
            # Clear the held flag so the user's eventual (late) release is a
            # no-op and the next press re-arms cleanly.
            ptt_held = False
            stop_recording("ptt")


def on_press(key):
    global ptt_held, toggle_state
    ptt_held, toggle_state, action = hotkeys.handle_key_press(
        HOTKEY_BINDINGS, pressed_keys, ptt_held, toggle_state, key
    )
    if action:
        _hotkey_queue.put(action)


def on_release(key):
    global ptt_held, toggle_state
    ptt_held, toggle_state, action = hotkeys.handle_key_release(
        HOTKEY_BINDINGS, pressed_keys, ptt_held, toggle_state, key
    )
    if action:
        _hotkey_queue.put(action)


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
    global HOTKEY_BINDINGS, shutting_down
    HOTKEY_BINDINGS = _load_hotkey_bindings(_CONFIG_DATA, _CONFIG_ERROR)
    if HOTKEY_BINDINGS is None:
        return 2

    _TRANSCRIBER.load_model()

    print("=" * 40)
    print("  Speech-to-Text (Parakeet TDT)")
    print("=" * 40)
    print(f"\n  Push-to-talk: hold {HOTKEY_BINDINGS.push_to_talk_name}")
    print(f"  Toggle:       {HOTKEY_BINDINGS.toggle_name} (tap to start, tap again to stop)")
    print("  Ctrl+C to quit\n")

    shutting_down = False
    overlay.start()
    sleep_observer = _SleepObserver.alloc().init()
    NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
        sleep_observer, "willSleep:", "NSWorkspaceWillSleepNotification", None
    )
    threading.Thread(target=_transcription_worker, daemon=True).start()
    threading.Thread(target=_hotkey_worker, daemon=True).start()
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
