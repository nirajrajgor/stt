import pytest

import config
import hotkeys


def test_missing_config_is_created_with_defaults(tmp_path):
    path = tmp_path / "stt.config.toml"

    assert not path.exists()
    data = config.load_config_data(path)

    assert path.read_text(encoding="utf-8") == config.DEFAULT_CONFIG
    assert data["hotkeys"]["push_to_talk"] == config.DEFAULT_PUSH_TO_TALK


def test_missing_config_write_failure_is_config_error(tmp_path, monkeypatch):
    path = tmp_path / "stt.config.toml"

    def fail_write_text(self, *args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(config.Path, "write_text", fail_write_text)

    with pytest.raises(config.ConfigError, match="Could not create"):
        config.load_config_data(path)


def test_missing_config_without_create_is_config_error(tmp_path):
    path = tmp_path / "stt.config.toml"

    with pytest.raises(config.ConfigError, match="Missing config file"):
        config.load_config_data(path, create_if_missing=False)


def test_invalid_toml_is_config_error(tmp_path):
    path = tmp_path / "stt.config.toml"
    path.write_text("[hotkeys\n", encoding="utf-8")

    with pytest.raises(config.ConfigError, match="Invalid TOML"):
        config.load_config_data(path)


def test_hotkey_config_error_is_config_error():
    assert issubclass(hotkeys.HotkeyConfigError, config.ConfigError)


def test_hotkeys_only_config_loads_hotkeys_and_default_settings(tmp_path):
    """Existing configs that predate [settings] must keep working unchanged."""
    path = tmp_path / "stt.config.toml"
    path.write_text(
        "[hotkeys]\n"
        'push_to_talk = "right_option"\n'
        'toggle = "left_option+left_command"\n',
        encoding="utf-8",
    )

    bindings = hotkeys.load_hotkey_bindings(path)
    settings = config.load_settings(path)

    assert bindings.push_to_talk_name == "right_option"
    assert bindings.toggle_name == "left_option+left_command"
    assert settings == config.Settings()


def test_settings_section_may_be_empty(tmp_path):
    path = tmp_path / "stt.config.toml"
    path.write_text(
        "[hotkeys]\n"
        'push_to_talk = "right_option"\n'
        'toggle = "left_option+left_command"\n'
        "[settings]\n",
        encoding="utf-8",
    )

    assert config.load_settings(path) == config.Settings()


def test_settings_must_be_a_section(tmp_path):
    path = tmp_path / "stt.config.toml"
    path.write_text('settings = "oops"\n', encoding="utf-8")

    with pytest.raises(config.ConfigError, match="must be a section"):
        config.load_settings(path)


@pytest.mark.parametrize("value", [True, False])
def test_sounds_accepts_booleans(tmp_path, value):
    path = tmp_path / "stt.config.toml"
    path.write_text(f"[settings]\nsounds = {str(value).lower()}\n", encoding="utf-8")

    assert config.load_settings(path).sounds is value


def test_sounds_defaults_to_true_when_missing(tmp_path):
    path = tmp_path / "stt.config.toml"
    path.write_text("[settings]\n", encoding="utf-8")

    assert config.load_settings(path).sounds is True


@pytest.mark.parametrize("value", ['"true"', "1"])
def test_sounds_rejects_non_boolean(tmp_path, value):
    path = tmp_path / "stt.config.toml"
    path.write_text(f"[settings]\nsounds = {value}\n", encoding="utf-8")

    with pytest.raises(config.ConfigError, match="must be true or false"):
        config.load_settings(path)


def test_default_config_parses_with_default_settings(tmp_path):
    path = tmp_path / "stt.config.toml"

    settings = config.load_settings(path)

    assert settings == config.Settings()
    assert "[settings]" in path.read_text(encoding="utf-8")


def test_unknown_settings_key_is_rejected(tmp_path):
    path = tmp_path / "stt.config.toml"
    path.write_text("[settings]\nsoundz = true\n", encoding="utf-8")

    with pytest.raises(config.ConfigError, match="Unknown key.*soundz"):
        config.load_settings(path)


def test_example_config_parses_without_creating():
    data = config.load_config_data(
        config.EXAMPLE_CONFIG_PATH, create_if_missing=False
    )

    assert "hotkeys" in data


def test_example_config_settings_are_valid():
    settings = config.load_settings(
        config.EXAMPLE_CONFIG_PATH, create_if_missing=False
    )

    assert settings == config.Settings()
