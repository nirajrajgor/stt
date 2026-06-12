"""Config-backed hotkey parsing for stt."""

from dataclasses import dataclass
from pathlib import Path
import string

from pynput import keyboard

from config import (
    CONFIG_PATH,
    EXAMPLE_CONFIG_PATH,
    ConfigError,
    load_config_data,
)


MAX_TOGGLE_KEYS = 3

_SIDE_SPECIFIC_MODIFIERS = {
    "left_command": keyboard.Key.cmd_l,
    "right_command": keyboard.Key.cmd_r,
    "left_option": keyboard.Key.alt_l,
    "right_option": keyboard.Key.alt_r,
    "left_control": keyboard.Key.ctrl_l,
    "right_control": keyboard.Key.ctrl_r,
    "left_shift": keyboard.Key.shift_l,
    "right_shift": keyboard.Key.shift_r,
}

_SPECIAL_KEYS = {
    "space": keyboard.Key.space,
    "enter": keyboard.Key.enter,
    "escape": keyboard.Key.esc,
    "tab": keyboard.Key.tab,
    "backspace": keyboard.Key.backspace,
    "delete": keyboard.Key.delete,
    "up": keyboard.Key.up,
    "down": keyboard.Key.down,
    "left": keyboard.Key.left,
    "right": keyboard.Key.right,
}

_FUNCTION_KEYS = {
    f"f{i}": getattr(keyboard.Key, f"f{i}")
    for i in range(1, 21)
}

_KEYS = {
    **_SIDE_SPECIFIC_MODIFIERS,
    **_SPECIAL_KEYS,
    **_FUNCTION_KEYS,
    **{ch: keyboard.KeyCode.from_char(ch) for ch in string.ascii_lowercase},
    **{digit: keyboard.KeyCode.from_char(digit) for digit in string.digits},
}

_GENERIC_MODIFIERS = {
    "command": ("left_command", "right_command"),
    "option": ("left_option", "right_option"),
    "control": ("left_control", "right_control"),
    "shift": ("left_shift", "right_shift"),
}

_UNSUPPORTED_FN = {"fn", "globe"}
_PTT_DISALLOWED = set(string.ascii_lowercase) | set(string.digits)
_OPTION_KEYS = {"left_option", "right_option"}


class HotkeyConfigError(ConfigError):
    """Raised when stt.config.toml contains invalid hotkey settings."""


@dataclass(frozen=True)
class HotkeyBindings:
    push_to_talk_name: str
    push_to_talk_key: object
    toggle_name: str
    toggle_keys: frozenset

    def is_push_to_talk_key(self, key):
        return key == self.push_to_talk_key

    def is_toggle_pressed(self, pressed_keys):
        return pressed_keys == self.toggle_keys


@dataclass(frozen=True)
class ToggleChordState:
    pending: bool = False
    poisoned: bool = False


def handle_key_press(bindings, pressed_keys, ptt_held, toggle_state, key):
    key = normalize_event_key(key)
    if key is None:
        return ptt_held, toggle_state, None

    if bindings.is_push_to_talk_key(key):
        if pressed_keys & bindings.toggle_keys:
            toggle_state = ToggleChordState(poisoned=True)
        if not ptt_held:
            return True, toggle_state, "ptt_press"
        return ptt_held, toggle_state, None

    if key in pressed_keys:
        return ptt_held, toggle_state, None

    pressed_keys.add(key)
    if ptt_held and key in bindings.toggle_keys:
        toggle_state = ToggleChordState(poisoned=True)
    elif pressed_keys & bindings.toggle_keys and pressed_keys - bindings.toggle_keys:
        toggle_state = ToggleChordState(poisoned=True)
    elif bindings.is_toggle_pressed(pressed_keys) and not toggle_state.poisoned:
        toggle_state = ToggleChordState(pending=True)
    return ptt_held, toggle_state, None


def handle_key_release(bindings, pressed_keys, ptt_held, toggle_state, key):
    key = normalize_event_key(key)
    if key is None:
        return ptt_held, toggle_state, None

    was_toggle_key = key in bindings.toggle_keys
    pressed_keys.discard(key)

    if bindings.is_push_to_talk_key(key) and ptt_held:
        return (
            False,
            _reset_toggle_state_if_idle(pressed_keys, False, toggle_state),
            "ptt_release",
        )

    if was_toggle_key and toggle_state.pending and not toggle_state.poisoned:
        return ptt_held, ToggleChordState(), "toggle"

    return ptt_held, _reset_toggle_state_if_idle(pressed_keys, ptt_held, toggle_state), None


def _reset_toggle_state_if_idle(pressed_keys, ptt_held, toggle_state):
    if not pressed_keys and not ptt_held:
        return ToggleChordState()
    return toggle_state


def load_hotkey_bindings(config_path=CONFIG_PATH, create_if_missing=True):
    """Parse the [hotkeys] section into HotkeyBindings.

    Raises HotkeyConfigError for invalid hotkey settings, and its base
    ConfigError for file-level failures (missing/unreadable/invalid TOML).
    Catch ConfigError to handle both.
    """
    path = Path(config_path)
    data = load_config_data(path, create_if_missing)

    hotkey_data = data.get("hotkeys")
    if not isinstance(hotkey_data, dict):
        raise HotkeyConfigError(
            f"Missing [hotkeys] section in {path.name}.\n"
            f"See {EXAMPLE_CONFIG_PATH.name} for supported hotkeys."
        )

    ptt_name = _required_string(hotkey_data, "push_to_talk", path)
    toggle_name = _required_string(hotkey_data, "toggle", path)

    ptt_key = _parse_push_to_talk(ptt_name, path)
    toggle_keys = _parse_toggle(toggle_name, path)

    if ptt_key in toggle_keys:
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    f'push_to_talk = "{ptt_name}"',
                    f'toggle = "{toggle_name}"',
                    "push_to_talk cannot also be part of toggle.",
                ],
            )
        )

    return HotkeyBindings(
        push_to_talk_name=ptt_name,
        push_to_talk_key=ptt_key,
        toggle_name=toggle_name,
        toggle_keys=frozenset(toggle_keys),
    )


def normalize_event_key(key):
    if isinstance(key, keyboard.KeyCode) and key.char:
        return keyboard.KeyCode.from_char(key.char.lower())
    return key


def _required_string(hotkey_data, key, path):
    value = hotkey_data.get(key)
    if not isinstance(value, str) or value == "":
        raise HotkeyConfigError(
            _config_error(path, [f"{key} must be a non-empty string."])
        )
    return value


def _parse_push_to_talk(value, path):
    source_line = _source_line("push_to_talk", value)
    parts = value.split("+")
    if len(parts) != 1:
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    "push_to_talk must be exactly one key.",
                ],
            )
        )

    key = _parse_key_name(value, path, source_line)
    if value in _PTT_DISALLOWED:
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    "push_to_talk cannot use letters or numbers.",
                ],
            )
        )
    return key


def _parse_toggle(value, path):
    source_line = _source_line("toggle", value)
    parts = value.split("+")
    keys = [_parse_key_name(part, path, source_line) for part in parts]
    if len(parts) < 2:
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    "toggle must include at least two keys joined with '+'.",
                ],
            )
        )

    if len(parts) > MAX_TOGGLE_KEYS:
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    f"toggle cannot use more than {MAX_TOGGLE_KEYS} keys.",
                ],
            )
        )

    if _OPTION_KEYS.intersection(parts) and _PTT_DISALLOWED.intersection(parts):
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    "Option + letter/number hotkeys are not supported.",
                    "macOS can turn them into special characters before stt sees them.",
                    "Use command/control/shift, a function key, or space.",
                ],
            )
        )

    if len(set(keys)) != len(keys):
        raise HotkeyConfigError(
            _config_error(
                path,
                [
                    source_line,
                    "toggle must include at least two distinct keys.",
                ],
            )
        )
    return set(keys)


def _parse_key_name(name, path, source_line):
    context = [source_line]
    if name != name.lower() or name.strip() != name or any(ch.isspace() for ch in name):
        raise HotkeyConfigError(
            _config_error(
                path,
                context + [
                    f'Invalid key name: "{name}"',
                    "Use exact lowercase names with no spaces.",
                ],
            )
        )

    if name in _UNSUPPORTED_FN:
        raise HotkeyConfigError(
            _config_error(
                path,
                context + [f'Unsupported key: "{name}". fn/globe is not supported.'],
            )
        )

    if name in _GENERIC_MODIFIERS:
        left, right = _GENERIC_MODIFIERS[name]
        raise HotkeyConfigError(
            _config_error(
                path,
                context + [
                    f'Generic modifier not allowed: "{name}".',
                    f"Use {left} or {right}.",
                ],
            )
        )

    key = _KEYS.get(name)
    if key is None:
        raise HotkeyConfigError(
            _config_error(
                path,
                context + [
                    f'Unsupported key: "{name}".',
                    f"See {EXAMPLE_CONFIG_PATH.name} for supported hotkeys.",
                ],
            )
        )
    return key


def _config_error(path, lines):
    return "\n".join([f"Invalid hotkey config in {Path(path).name}:", *lines])


def _source_line(field, value):
    return f'{field} = "{value}"'
