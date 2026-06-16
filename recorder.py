"""Recorder child helpers.

Must stay stdlib-only: the recorder child imports this before the heavy
third-party imports in stt.py are available.
"""

# Internal parent-to-child handoff of the configured input_device; the child
# must not parse the config file itself (it runs before the heavy imports).
RECORDER_DEVICE_ENV = "STT_RECORDER_INPUT_DEVICE"

# Newline-delimited JSON protocol between stt.py and recorder_worker.py.
EVENT_KEY = "event"
EVENT_READY = "ready"
EVENT_WARNING = "warning"
EVENT_ERROR = "error"
EVENT_AMPLITUDE = "amplitude"
EVENT_SAVED = "saved"

COMMAND_STOP = "STOP"
COMMAND_CANCEL = "CANCEL"

# Capture/transcription rate (Hz); shared here since both sides must match (no resampling).
SAMPLE_RATE = 16000


def child_env(base_env, input_device):
    """Environment for spawning the recorder child.

    Strips any stale handoff value from base_env so a leftover in the
    parent's shell cannot leak through, then sets the configured device.
    """
    env = dict(base_env)
    env.pop(RECORDER_DEVICE_ENV, None)
    if input_device is not None:
        env[RECORDER_DEVICE_ENV] = str(input_device)
    return env


def resolve_input_device(sd, override):
    """Map the handed-off device value to a sounddevice index.

    Returns (device_index_or_None, warning_or_None); None means the system
    default input. `sd` is the sounddevice module, passed in so tests can
    fake the device list.
    """
    if not override:
        return None, None
    try:
        return int(override), None
    except ValueError:
        needle = override.lower()
        for idx, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0 and needle in dev["name"].lower():
                return idx, None
        return None, (
            f"input_device '{override}' not found; falling back to system default."
        )
