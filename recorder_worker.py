#!/usr/bin/env python3
"""Recorder worker process for stt.py.

This process owns the CoreAudio/PortAudio stream and communicates with the
parent using newline-delimited JSON on stdout.
"""

import json
import os
import select
import sys
import threading
import time
import traceback

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(SCRIPT_DIR, "venv", "bin", "python")
if os.path.exists(VENV_PYTHON) and os.path.abspath(sys.executable) != VENV_PYTHON:
    os.execv(VENV_PYTHON, [VENV_PYTHON, os.path.abspath(__file__), *sys.argv[1:]])

import recorder


def _emit(event):
    print(json.dumps(event), flush=True)


def _output_path_from_argv(argv):
    if len(argv) != 2:
        _emit({"event": "error", "message": "missing output path"})
        os._exit(2)
    return argv[1]


def main(argv=None):
    """Record microphone audio until stdin receives STOP or CANCEL."""
    argv = sys.argv if argv is None else argv
    out_path = _output_path_from_argv(argv)

    try:
        import numpy as np
        import sounddevice as sd

        sample_rate = int(os.environ.get("STT_SAMPLE_RATE", "16000"))
        frames = []
        active = True
        amp_lock = threading.Lock()
        latest_amp = 0.0

        def callback(indata, frame_count, time_info, status):
            nonlocal latest_amp
            if active:
                frames.append(indata.copy())
                with amp_lock:
                    latest_amp = float(np.sqrt(np.mean(indata ** 2)))

        def emit_amplitudes():
            while active:
                with amp_lock:
                    level = latest_amp
                _emit({"event": "amplitude", "level": level})
                time.sleep(1.0 / 30.0)

        device, device_warning = recorder.resolve_input_device(
            sd, os.environ.get(recorder.RECORDER_DEVICE_ENV)
        )
        if device_warning:
            _emit({"event": "warning", "message": device_warning})

        dev_info = sd.query_devices(device, "input")
        strm = sd.InputStream(
            samplerate=sample_rate, channels=1, callback=callback, device=device
        )
        strm.start()
        amp_thread = threading.Thread(target=emit_amplitudes, daemon=True)
        amp_thread.start()
        _emit({"event": "ready", "device": dev_info["name"]})

        command = "STOP"
        while True:
            readable, _, _ = select.select([sys.stdin], [], [], 0.1)
            if not readable:
                continue
            line = sys.stdin.readline()
            if line == "":
                break
            command = line.strip().upper() or "STOP"
            if command in {"STOP", "CANCEL"}:
                break

        active = False
        amp_thread.join(0.2)
        if command != "CANCEL":
            saved_frames = list(frames)
            if saved_frames:
                audio_data = np.concatenate(saved_frames, axis=0)
            else:
                audio_data = np.empty((0, 1), dtype=np.float32)
            np.save(out_path, audio_data)
            _emit({"event": "saved", "frames": len(saved_frames)})

        def cleanup():
            try:
                strm.abort()
            except Exception:
                traceback.print_exc()
            try:
                strm.close()
            except Exception:
                traceback.print_exc()

        cleanup_thread = threading.Thread(target=cleanup, daemon=True)
        cleanup_thread.start()
        cleanup_thread.join(0.5)
        os._exit(0)
    except Exception as exc:
        _emit({"event": "error", "message": str(exc)})
        traceback.print_exc()
        os._exit(2)


if __name__ == "__main__":
    main()
