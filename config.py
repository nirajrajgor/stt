"""Shared loading for stt.config.toml.

Must stay stdlib-only: the recorder child process may import this before
the heavy third-party imports in stt.py are available.
"""

from dataclasses import dataclass
from pathlib import Path
import tomllib


CONFIG_PATH = Path(__file__).with_name("stt.config.toml")
EXAMPLE_CONFIG_PATH = Path(__file__).with_name("stt.config.example.toml")

DEFAULT_PUSH_TO_TALK = "right_option"
DEFAULT_TOGGLE = "left_option+left_command"
DEFAULT_CONFIG = (
    "[hotkeys]\n"
    f'push_to_talk = "{DEFAULT_PUSH_TO_TALK}"\n'
    f'toggle = "{DEFAULT_TOGGLE}"\n'
    "\n"
    "[settings]\n"
    "sounds = true\n"
)


class ConfigError(ValueError):
    """Raised when stt.config.toml is missing, unreadable, or invalid."""


@dataclass(frozen=True)
class Settings:
    """Runtime settings from the optional [settings] section.

    Fields are added as the STT_* environment variables migrate here.
    Defaults here are the single source of truth for missing keys.
    """

    sounds: bool = True


# Keys allowed in [settings]; anything else is rejected so typos fail
# loudly instead of silently using defaults.
_KNOWN_SETTINGS = frozenset({"sounds"})


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
    return Settings(**kwargs)


def _bool_setting(section, key, path):
    value = section[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f'"{key}" in [settings] of {path.name} must be true or false.'
        )
    return value
