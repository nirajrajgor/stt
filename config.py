"""Shared loading for stt.config.toml.

Must stay stdlib-only: the recorder child process may import this before
the heavy third-party imports in stt.py are available.
"""

from dataclasses import dataclass
import math
from pathlib import Path
import tomllib


CONFIG_PATH = Path(__file__).with_name("stt.config.toml")
EXAMPLE_CONFIG_PATH = Path(__file__).with_name("stt.config.example.toml")

DEFAULT_PUSH_TO_TALK = "right_option"
DEFAULT_TOGGLE = "left_option+left_command"


class ConfigError(ValueError):
    """Raised when stt.config.toml is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings from the optional [settings] section.

    Fields are added as the STT_* environment variables migrate here.
    Defaults here are the single source of truth for missing keys.
    """

    sounds: bool = True
    utterance_gap: float = 0.7
    denoise: str = "auto"
    # Device index (int), name substring (str), or None for system default.
    input_device: int | str | None = None


_DEFAULTS = Settings()
# Written on first run. Settings values are interpolated so the generated
# file cannot drift from the code defaults; input_device is omitted because
# its default is "key absent" (system default input).
DEFAULT_CONFIG = (
    "[hotkeys]\n"
    f'push_to_talk = "{DEFAULT_PUSH_TO_TALK}"\n'
    f'toggle = "{DEFAULT_TOGGLE}"\n'
    "\n"
    "[settings]\n"
    f"sounds = {'true' if _DEFAULTS.sounds else 'false'}\n"
    f"utterance_gap = {_DEFAULTS.utterance_gap}\n"
    f'denoise = "{_DEFAULTS.denoise}"\n'
)


DENOISE_CHOICES = ("auto", "on", "off")

# Keys allowed in [settings]; anything else is rejected so typos fail
# loudly instead of silently using defaults.
_KNOWN_SETTINGS = frozenset({"sounds", "utterance_gap", "denoise", "input_device"})


def ensure_config_exists(config_path=CONFIG_PATH):
    path = Path(config_path)
    if not path.exists():
        try:
            path.write_text(DEFAULT_CONFIG, encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Could not create {path.name}: {exc}") from exc


def load_config_data(config_path=CONFIG_PATH, create_if_missing=True):
    path = Path(config_path)
    if create_if_missing:
        ensure_config_exists(path)

    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path.name}: {exc}") from exc
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing config file: {path}") from exc


def load_settings(config_path=CONFIG_PATH, create_if_missing=True):
    data = load_config_data(config_path, create_if_missing)
    return parse_settings(data, config_path)


def parse_settings(data, config_path=CONFIG_PATH):
    path = Path(config_path)
    section = data.get("settings", {})
    if not isinstance(section, dict):
        raise ConfigError(f"[settings] must be a section in {path.name}.")

    unknown = sorted(set(section) - _KNOWN_SETTINGS)
    if unknown:
        raise ConfigError(
            f"Unknown key(s) in [settings] of {path.name}: {', '.join(unknown)}"
        )

    kwargs = {}
    if "sounds" in section:
        kwargs["sounds"] = _bool_setting(section, "sounds", path)
    if "utterance_gap" in section:
        kwargs["utterance_gap"] = _positive_number_setting(
            section, "utterance_gap", path, max_value=10
        )
    if "denoise" in section:
        kwargs["denoise"] = _choice_setting(
            section, "denoise", path, DENOISE_CHOICES
        )
    if "input_device" in section:
        kwargs["input_device"] = _input_device_setting(
            section, "input_device", path
        )
    return Settings(**kwargs)


def _bool_setting(section, key, path):
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f'"{key}" in [settings] of {path.name} must be true or false.'
        )
    return value


def _choice_setting(section, key, path, choices):
    value = section[key]
    if value not in choices:
        quoted = ", ".join(f'"{c}"' for c in choices)
        raise ConfigError(
            f'"{key}" in [settings] of {path.name} must be one of: {quoted}.'
        )
    return value


def _input_device_setting(section, key, path):
    value = section[key]
    if isinstance(value, bool) or not isinstance(value, (int, str)) or (
        isinstance(value, int) and value < 0
    ) or (isinstance(value, str) and not value.strip()):
        raise ConfigError(
            f'"{key}" in [settings] of {path.name} must be a device index '
            "(whole number >= 0) or a device name string."
        )
    # Strip name padding: the child's substring match would silently miss
    # otherwise and fall back to the default device.
    return value.strip() if isinstance(value, str) else value


def _positive_number_setting(section, key, path, max_value):
    value = section[key]
    # bool is an int subclass; true/false are not numbers here.
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < value <= max_value
    ):
        raise ConfigError(
            f'"{key}" in [settings] of {path.name} must be a number '
            f"greater than 0 and at most {max_value}."
        )
    return float(value)
