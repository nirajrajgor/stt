from pynput import keyboard
import pytest

import hotkeys


def write_config(path, push_to_talk="right_option", toggle="left_option+left_command"):
    path.write_text(
        "[hotkeys]\n"
        f'push_to_talk = "{push_to_talk}"\n'
        f'toggle = "{toggle}"\n',
        encoding="utf-8",
    )


def test_missing_config_is_created_with_defaults(tmp_path):
    path = tmp_path / "stt.config.toml"

    assert not path.exists()
    bindings = hotkeys.load_hotkey_bindings(path)

    assert path.read_text(encoding="utf-8") == hotkeys.DEFAULT_CONFIG
    assert bindings.push_to_talk_name == "right_option"
    assert bindings.toggle_name == "left_option+left_command"


def test_missing_config_write_failure_is_config_error(tmp_path, monkeypatch):
    path = tmp_path / "stt.config.toml"

    def fail_write_text(self, *args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(hotkeys.Path, "write_text", fail_write_text)

    with pytest.raises(hotkeys.HotkeyConfigError, match="Could not create"):
        hotkeys.load_hotkey_bindings(path)


def test_example_config_parses():
    bindings = hotkeys.load_hotkey_bindings(
        hotkeys.EXAMPLE_CONFIG_PATH,
        create_if_missing=False,
    )

    assert bindings.push_to_talk_name == "right_option"
    assert bindings.toggle_name == "left_option+left_command"


def test_default_hotkeys_match_current_behavior(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path)

    bindings = hotkeys.load_hotkey_bindings(path)

    assert bindings.is_push_to_talk_key(keyboard.Key.alt_r)
    assert bindings.is_toggle_pressed({keyboard.Key.alt_l, keyboard.Key.cmd})


def test_toggle_can_use_letters_and_numbers(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="left_command+a+1")
    bindings = hotkeys.load_hotkey_bindings(path)
    pressed_keys = set()
    ptt_held = False
    toggle_held = False

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.Key.cmd_l
    )
    assert action is None

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("A")
    )
    assert action is None

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("1")
    )
    assert toggle_held is True
    assert action == "toggle"


@pytest.mark.parametrize("key", ["a", "1"])
def test_toggle_rejects_option_letter_or_number_combo(tmp_path, key):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle=f"left_option+{key}")

    with pytest.raises(hotkeys.HotkeyConfigError, match="special characters"):
        hotkeys.load_hotkey_bindings(path)


def test_toggle_allows_option_with_non_letter_keys(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="left_option+space")

    bindings = hotkeys.load_hotkey_bindings(path)

    assert bindings.is_toggle_pressed({keyboard.Key.alt_l, keyboard.Key.space})


def test_push_to_talk_repeat_does_not_enter_pressed_keys(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, push_to_talk="space")
    bindings = hotkeys.load_hotkey_bindings(path)
    pressed_keys = set()

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, False, False, keyboard.Key.space
    )
    assert ptt_held is True
    assert toggle_held is False
    assert action == "ptt_press"
    assert pressed_keys == set()

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.Key.space
    )
    assert ptt_held is True
    assert toggle_held is False
    assert action is None
    assert pressed_keys == set()


def test_push_to_talk_release_discards_stale_pressed_key(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, push_to_talk="space")
    bindings = hotkeys.load_hotkey_bindings(path)
    pressed_keys = {keyboard.Key.space}

    ptt_held, toggle_held, action = hotkeys.handle_key_release(
        bindings, pressed_keys, True, False, keyboard.Key.space
    )

    assert ptt_held is False
    assert toggle_held is False
    assert action == "ptt_release"
    assert pressed_keys == set()


def test_toggle_does_not_refire_while_combo_is_held(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="left_command+a")
    bindings = hotkeys.load_hotkey_bindings(path)
    pressed_keys = set()

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, False, False, keyboard.Key.cmd_l
    )
    assert action is None

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("a")
    )
    assert toggle_held is True
    assert action == "toggle"

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("b")
    )
    assert toggle_held is True
    assert action is None


def test_toggle_rearms_when_tapped_key_is_released(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="left_command+a")
    bindings = hotkeys.load_hotkey_bindings(path)
    pressed_keys = set()
    ptt_held = False
    toggle_held = False

    ptt_held, toggle_held, _ = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.Key.cmd_l
    )
    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("a")
    )
    assert action == "toggle"

    ptt_held, toggle_held, action = hotkeys.handle_key_release(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("a")
    )
    assert toggle_held is False
    assert action is None

    ptt_held, toggle_held, action = hotkeys.handle_key_press(
        bindings, pressed_keys, ptt_held, toggle_held, keyboard.KeyCode.from_char("a")
    )
    assert toggle_held is True
    assert action == "toggle"


def test_push_to_talk_rejects_combo(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, push_to_talk="right_option+left_command")

    with pytest.raises(hotkeys.HotkeyConfigError, match="exactly one key"):
        hotkeys.load_hotkey_bindings(path)


def test_push_to_talk_rejects_letters_and_numbers(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, push_to_talk="a")

    with pytest.raises(hotkeys.HotkeyConfigError, match="letters or numbers"):
        hotkeys.load_hotkey_bindings(path)


def test_toggle_rejects_single_key(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="left_command")

    with pytest.raises(hotkeys.HotkeyConfigError, match="at least two keys"):
        hotkeys.load_hotkey_bindings(path)


def test_toggle_rejects_push_to_talk_conflict(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="right_option+left_command")

    with pytest.raises(hotkeys.HotkeyConfigError, match="cannot also be part of toggle"):
        hotkeys.load_hotkey_bindings(path)


def test_generic_modifier_rejected_with_side_specific_suggestion(tmp_path):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle="option+left_command")

    with pytest.raises(hotkeys.HotkeyConfigError, match="left_option or right_option"):
        hotkeys.load_hotkey_bindings(path)


@pytest.mark.parametrize("name", ["fn", "globe"])
def test_fn_and_globe_are_rejected(tmp_path, name):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle=f"{name}+left_command")

    with pytest.raises(hotkeys.HotkeyConfigError, match="fn/globe is not supported"):
        hotkeys.load_hotkey_bindings(path)


@pytest.mark.parametrize("name", ["Left_option", "left_option + left_command"])
def test_key_names_must_be_exact_lowercase_without_spaces(tmp_path, name):
    path = tmp_path / "stt.config.toml"
    write_config(path, toggle=name)

    with pytest.raises(hotkeys.HotkeyConfigError, match="exact lowercase"):
        hotkeys.load_hotkey_bindings(path)
