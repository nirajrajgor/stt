import pytest

import recorder


class FakeSounddevice:
    """Stands in for the sounddevice module: query_devices() only."""

    def __init__(self, devices):
        self._devices = devices

    def query_devices(self):
        return self._devices


DEVICES = [
    {"name": "MacBook Air Microphone", "max_input_channels": 1},
    {"name": "External Display", "max_input_channels": 0},
    {"name": "Niraj's AirPods Pro", "max_input_channels": 1},
]


# --- child_env: parent side of the handoff ---


def test_child_env_unset_device_sets_nothing():
    env = recorder.child_env({"PATH": "/usr/bin"}, None)

    assert recorder.RECORDER_DEVICE_ENV not in env
    assert env["PATH"] == "/usr/bin"


def test_child_env_strips_stale_value():
    base = {recorder.RECORDER_DEVICE_ENV: "stale"}

    assert recorder.RECORDER_DEVICE_ENV not in recorder.child_env(base, None)


def test_child_env_passes_index_as_string():
    env = recorder.child_env({}, 2)

    assert env[recorder.RECORDER_DEVICE_ENV] == "2"


def test_child_env_passes_name():
    env = recorder.child_env({}, "airpods")

    assert env[recorder.RECORDER_DEVICE_ENV] == "airpods"


def test_child_env_does_not_mutate_base():
    base = {recorder.RECORDER_DEVICE_ENV: "stale"}
    recorder.child_env(base, "airpods")

    assert base == {recorder.RECORDER_DEVICE_ENV: "stale"}


# --- resolve_input_device: child side of the handoff ---


def test_resolve_no_override_uses_default():
    assert recorder.resolve_input_device(FakeSounddevice(DEVICES), None) == (None, None)


def test_resolve_index_passes_through():
    assert recorder.resolve_input_device(FakeSounddevice(DEVICES), "2") == (2, None)


def test_resolve_name_matches_substring_case_insensitive():
    device, warning = recorder.resolve_input_device(FakeSounddevice(DEVICES), "AIRPODS")

    assert device == 2
    assert warning is None


def test_resolve_name_skips_output_only_devices():
    device, warning = recorder.resolve_input_device(FakeSounddevice(DEVICES), "display")

    assert device is None
    assert "not found" in warning


def test_resolve_unknown_name_warns_and_falls_back():
    device, warning = recorder.resolve_input_device(FakeSounddevice(DEVICES), "yeti")

    assert device is None
    assert warning == "input_device 'yeti' not found; falling back to system default."
