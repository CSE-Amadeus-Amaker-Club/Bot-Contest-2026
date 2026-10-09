import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
import pytest
from config import load_config
from gamepad_callbacks import mix_track_speeds
from gamepad_manager import GamepadManager
from servo_controls import ServoControls


class FakeCommandClient:
    def __init__(self):
        self.commands: list[tuple[str, tuple]] = []

    def queue_set_servo_speed(self, channel, speed, force=False):
        self.commands.append(("speed", (channel, speed, force)))

    def queue_set_servo_angle(self, channel, angle, force=False):
        self.commands.append(("angle", (channel, angle, force)))

    def queue_set_led_color(self, led_mask, red, green, blue, brightness):
        self.commands.append(("led", (led_mask, red, green, blue, brightness)))

    def queue_play_sound(self, filename):
        self.commands.append(("play", (filename,)))

    def queue_set_servo_type(self, channel, servo_type):
        self.commands.append(("type", (channel, servo_type)))

    def queue_stop_all_motors(self):
        self.commands.append(("stop", ()))

    def command_status(self, status_key):
        return "READY"


class FakeJoystick:
    def __init__(self, axes=None, buttons=None):
        self.axes = axes or [0.0, 0.5, 0.0, -0.25, 1.0, -1.0]
        self.buttons = buttons or [0] * 6

    def get_numaxes(self):
        return len(self.axes)

    def get_axis(self, axis):
        return self.axes[axis]

    def get_numbuttons(self):
        return len(self.buttons)

    def get_button(self, button):
        return self.buttons[button]

    def get_instance_id(self):
        return 7

    def init(self):
        pass

    def get_name(self):
        return "Xbox 360 Controller"


def _controls(client):
    return ServoControls(
        client,
        600,
        400,
        (proto.SERVO_TYPE_CONTINUOUS, proto.SERVO_TYPE_CONTINUOUS,
         proto.SERVO_TYPE_270, proto.SERVO_TYPE_270,
         proto.SERVO_TYPE_180, proto.SERVO_TYPE_180),
    )


@pytest.mark.parametrize("axes, speeds", [
    ([0, -1], (100, 100)),
    ([0, 1], (-100, -100)),
    ([-1, 0], (100, -100)),
    ([1, 0], (-100, 100)),
    ([-1, -1], (100, 0)),
    ([1, -1], (0, 100)),
    ([0, 0], (0, 0)),
    ([0, -0.56], (50, 50)),
])
@pytest.mark.parametrize("configured", [False, True])
def test_left_stick_drives_both_tracks(axes, speeds, configured):
    client = FakeCommandClient()
    controls = _controls(client)
    actions = {
        "left_stick_x": "gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)",
        "left_stick_y": "gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)",
    } if configured else None
    manager = GamepadManager(controls.servo_types(), (None,) * proto.SERVO_COUNT, actions)
    manager.joystick = FakeJoystick(axes=axes + [0, 1, -1, -1])

    manager.apply_controls(client, controls)

    assert [command for command in client.commands if command[0] == "speed"] == [
        ("speed", (0, speeds[0], False)), ("speed", (1, speeds[1], False)),
    ]
    assert [channel.value for channel in controls.channels[:2]] == list(speeds)
    count = len(client.commands)
    manager.apply_controls(client, controls)
    assert len(client.commands) == count


def test_paired_bumper_preserves_trigger_position_on_release():
    client = FakeCommandClient()
    controls = _controls(client)
    actions = {
        "left_bumper": "gamepad_callbacks.set_paired_angle(side='left',servonumber=3)",
        "left_trigger": "gamepad_callbacks.set_paired_angle(side='left',servonumber=3)",
    }
    manager = GamepadManager(controls.servo_types(), (None, None, None, (45, 120), None, None), actions)
    joystick = FakeJoystick(axes=[0, 0, 0, 0, -1, -1], buttons=[0, 0, 0, 0, 1, 0])
    manager.joystick = joystick
    manager.apply_controls(client, controls)
    assert client.commands == [("angle", (3, 120, False))]
    joystick.axes[4] = 0
    manager.apply_controls(client, controls)
    assert len(client.commands) == 1
    joystick.buttons[4] = 0
    manager.apply_controls(client, controls)
    assert client.commands[-1] == ("angle", (3, 79, False))
    joystick.axes[4] = -1
    manager.apply_controls(client, controls)
    assert client.commands[-1] == ("angle", (3, 45, False))


@pytest.mark.parametrize("raw_y, expected", [
    (-0.12, 0), (0.12, 0), (-0.13, 1), (0.13, -1), (-0.56, 50), (0.56, -50),
])
def test_track_deadzone_is_rescaled_once(raw_y, expected):
    assert mix_track_speeds(0, raw_y) == (expected, expected)


@pytest.mark.parametrize("raw_x, raw_y, expected", [
    (-1, 1, (0, -100)), (1, 1, (-100, 0)),
    (-0.56, -1, (100, 33)), (0.56, -1, (33, 100)),
    (-0.56, 1, (-33, -100)), (0.56, 1, (-100, -33)),
])
def test_diagonal_track_mixing_preserves_ratio(raw_x, raw_y, expected):
    assert mix_track_speeds(raw_x, raw_y) == expected


def test_right_pair_uses_s5_limits_and_bumper_priority():
    client = FakeCommandClient()
    controls = _controls(client)
    controls.channels[4].servo_type = proto.SERVO_TYPE_270
    actions = {
        "right_bumper": "gamepad_callbacks.set_paired_angle(side='right',servonumber=4)",
        "right_trigger": "gamepad_callbacks.set_paired_angle(side='right',servonumber=4)",
    }
    manager = GamepadManager(controls.servo_types(), (None, None, None, None, (140, 270), None), actions)
    joystick = FakeJoystick(axes=[0, 0, 0, 0, -1, -1])
    manager.joystick = joystick
    manager.apply_controls(client, controls)
    assert client.commands == [("angle", (4, 140, False))]
    joystick.axes[5] = 1
    manager.apply_controls(client, controls)
    assert client.commands[-1] == ("angle", (4, 270, False))
    joystick.buttons[5] = 1
    joystick.axes[5] = -1
    manager.apply_controls(client, controls)
    assert len(client.commands) == 2
    joystick.buttons[5] = 0
    manager.apply_controls(client, controls)
    assert client.commands[-1] == ("angle", (4, 140, False))
    controls.channels[4].servo_type = proto.SERVO_TYPE_180
    client.commands.clear()
    manager.apply_controls(client, controls)
    assert client.commands == []


def test_s4_trigger_uses_detected_usb_xbox_axis_mapping(monkeypatch):
    from types import SimpleNamespace

    import gamepad_manager

    client = FakeCommandClient()
    controls = _controls(client)
    joystick = FakeJoystick(axes=[0, 0, -1, 0, 0, -1])
    mapping = {"leftx": "a0", "lefty": "a1", "rightx": "a3", "righty": "a4",
               "lefttrigger": "a2", "righttrigger": "a5"}
    mapped_controller = SimpleNamespace(get_mapping=lambda: mapping, quit=lambda: None)
    monkeypatch.setattr(gamepad_manager, "pygame", SimpleNamespace(
        joystick=SimpleNamespace(Joystick=lambda index: joystick),
    ))
    monkeypatch.setattr(gamepad_manager, "sdl_controller", SimpleNamespace(
        init=lambda: None, is_controller=lambda index: True,
        Controller=lambda index: mapped_controller,
    ), raising=False)
    manager = GamepadManager(controls.servo_types(), (None, None, None, (45, 120), None, None), {
        "left_trigger": "gamepad_callbacks.set_paired_angle(side='left',servonumber=3)",
        "left_bumper": "gamepad_callbacks.set_paired_angle(side='left',servonumber=3)",
    })
    manager.joystick = manager._open_joystick(0)
    manager.apply_controls(client, controls)
    assert client.commands == [("angle", (3, 45, False))]
    joystick.axes[2] = 1
    manager.apply_controls(client, controls)
    assert client.commands[-1] == ("angle", (3, 120, False))
    joystick.axes[4] = 1
    count = len(client.commands)
    manager.apply_controls(client, controls)
    assert len(client.commands) == count


@pytest.mark.parametrize("missing_backend", [True, False])
def test_sdl_mapping_failure_keeps_raw_joystick_fallback(monkeypatch, missing_backend):
    from types import SimpleNamespace

    import gamepad_manager

    def unavailable():
        raise RuntimeError("SDL mapping unavailable")

    joystick = FakeJoystick()
    monkeypatch.setattr(gamepad_manager, "pygame", SimpleNamespace(
        error=RuntimeError, joystick=SimpleNamespace(Joystick=lambda index: joystick),
    ))
    monkeypatch.setattr(gamepad_manager, "sdl_controller", None if missing_backend else SimpleNamespace(init=unavailable))
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(controls.servo_types(), (None,) * proto.SERVO_COUNT)
    assert manager._open_joystick(0) is joystick
    assert manager._axis_indices == gamepad_manager.JOYSTICK_AXIS_DEFAULTS


def test_track_mapping_revalidates_live_types_and_restores_unchanged_input():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(controls.servo_types(), (None,) * proto.SERVO_COUNT, {
        "left_stick_x": "gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)",
        "left_stick_y": "gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)",
    })
    manager.joystick = FakeJoystick(axes=[0, -1, 0, 0, -1, -1])
    manager.apply_controls(client, controls)
    controls.channels[0].servo_type = proto.SERVO_TYPE_180
    client.commands.clear()
    manager.apply_controls(client, controls)
    assert client.commands == []
    controls.channels[0].servo_type = proto.SERVO_TYPE_CONTINUOUS
    manager.apply_controls(client, controls)
    assert client.commands == [("speed", (0, 100, False)), ("speed", (1, 100, False))]


def test_disconnect_and_reconnect_respect_limits_and_replay_same_input(monkeypatch):
    from types import SimpleNamespace

    import gamepad_manager

    client = FakeCommandClient()
    controls = _controls(client)
    controls.channels[4].servo_type = proto.SERVO_TYPE_270
    manager = GamepadManager(controls.servo_types(), (None, None, None, (45, 120), (140, 270), None), {
        "left_stick_y": "gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)",
    })
    joystick = FakeJoystick(axes=[0, -1, 0, 0, -1, -1])
    manager.joystick = joystick
    manager.apply_controls(client, controls)
    controls.channels[2].servo_type = proto.SERVO_TYPE_CONTINUOUS
    client.commands.clear()
    events = [SimpleNamespace(type=2, instance_id=7), SimpleNamespace(type=1, device_index=0)]
    monkeypatch.setattr(gamepad_manager, "pygame", SimpleNamespace(
        JOYDEVICEADDED=1, JOYDEVICEREMOVED=2, JOYBUTTONDOWN=3, JOYBUTTONUP=4,
        event=SimpleNamespace(get=lambda: events),
    ))
    monkeypatch.setattr(manager, "_open_joystick", lambda index: joystick)
    manager.handle_events(client, controls)
    assert client.commands[:5] == [
        ("speed", (0, 0, True)), ("speed", (1, 0, True)), ("speed", (2, 0, True)),
        ("angle", (3, 45, True)), ("angle", (4, 140, True)),
    ]
    manager.apply_controls(client, controls)
    assert client.commands[-2:] == [("speed", (0, 100, False)), ("speed", (1, 100, False))]


def test_optional_pygame_unavailable_is_graceful(monkeypatch):
    import gamepad_manager

    client = FakeCommandClient()
    controls = _controls(client)
    monkeypatch.setattr(gamepad_manager, "pygame", None)
    manager = GamepadManager(controls.servo_types(), (None,) * proto.SERVO_COUNT)
    manager.initialize()
    manager.handle_events(client, controls)
    manager.apply_controls(client, controls)
    manager.shutdown()
    assert client.commands == []


@pytest.mark.parametrize("filename", ["sensorscreen.conf", "sensorscreen.conf.example"])
def test_shipped_configuration_drives_requested_channels_and_limits(filename):
    config_path = Path(__file__).resolve().parent.parent / filename
    config = load_config(["--config", str(config_path), "--ip", "127.0.0.1", "--token", "00000"])
    client = FakeCommandClient()
    controls = ServoControls(client, 600, 400, config.servo_types)
    manager = GamepadManager(config.servo_types, config.servo_angle_limits, config.gamepad_actions)
    manager.joystick = FakeJoystick(axes=[0, -1, 0, 1, -1, -1])
    manager.apply_controls(client, controls)
    assert client.commands == [
        ("speed", (0, 100, False)), ("speed", (1, 100, False)),
        ("angle", (3, 45, False)), ("angle", (4, 140, False)),
    ]


def test_joystick_updates_commands_and_rendered_cursor_values():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    manager.joystick = FakeJoystick()

    manager.apply_controls(client, controls)

    assert client.commands == [
        ("speed", (0, -43, False)),
        ("speed", (1, -43, False)),
        ("angle", (3, 270, False)),
        ("angle", (4, 0, False)),
    ]
    assert [controls.channels[channel].value for channel in (0, 1, 3, 4)] == [-43, -43, 270, 0]


def test_unchanged_joystick_values_do_not_repeat_servo_commands():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    joystick = FakeJoystick()
    manager.joystick = joystick

    manager.apply_controls(client, controls)
    first_count = len(client.commands)
    manager.apply_controls(client, controls)

    assert len(client.commands) == first_count


def test_safe_positions_update_commands_and_rendered_cursor_values():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    for channel, value in enumerate((-50, 25, 270, 180)):
        controls.set_external_value(channel, value)

    manager.set_safe_positions(client, controls)

    assert client.commands == [
        ("speed", (0, 0, True)),
        ("speed", (1, 0, True)),
        ("angle", (2, 0, True)),
        ("angle", (3, 0, True)),
        ("angle", (4, 0, True)),
        ("angle", (5, 0, True)),
    ]
    assert [channel.value for channel in controls.channels[:6]] == [0, 0, 0, 0, 0, 0]


def test_incompatible_mapping_does_not_send_invalid_commands():
    client = FakeCommandClient()
    controls = ServoControls(client, 600, 400, (proto.SERVO_TYPE_180,) * proto.SERVO_COUNT)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    manager.joystick = FakeJoystick()

    manager.apply_controls(client, controls)

    assert client.commands == []
    assert [channel.value for channel in controls.channels[:4]] == [0, 0, 0, 0]


def test_released_trigger_noise_does_not_move_positional_servos():
    client = FakeCommandClient()
    controls = _controls(client)
    joystick = FakeJoystick(axes=[0.0, 0.0, 0.0, 0.0, -0.96, -0.95])
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    manager.joystick = joystick

    manager.apply_controls(client, controls)

    assert client.commands == [
        ("speed", (0, 0, False)),
        ("speed", (1, 0, False)),
        ("angle", (3, 0, False)),
        ("angle", (4, 0, False)),
    ]


def test_left_and_right_bumpers_override_trigger_positions():
    client = FakeCommandClient()
    controls = _controls(client)
    joystick = FakeJoystick(axes=[0.0] * 6, buttons=[0, 0, 0, 0, 1, 1])
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
    )
    manager.joystick = joystick

    manager.apply_controls(client, controls)

    assert client.commands == [
        ("speed", (0, 0, False)),
        ("speed", (1, 0, False)),
        ("angle", (3, 270, False)),
        ("angle", (4, 180, False)),
    ]


def test_custom_angle_limits_are_applied_to_trigger_mapping():
    client = FakeCommandClient()
    controls = _controls(client)
    joystick = FakeJoystick(axes=[0.0] * 6, buttons=[0, 0, 0, 0, 1, 0])
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None, None, None, (20, 200), (10, 90), None),
    )
    manager.joystick = joystick

    manager.apply_controls(client, controls)

    assert client.commands == [
        ("speed", (0, 0, False)),
        ("speed", (1, 0, False)),
        ("angle", (3, 200, False)),
        ("angle", (4, 47, False)),
    ]


def test_load_config_parses_per_servo_angle_limits(tmp_path):
    config_path = tmp_path / "sensorscreen.conf"
    config_path.write_text(
        """[bot]
bot_ip = 127.0.0.1

[servos]
s1_type = continuous
s2_type = continuous
s3_type = angle270
s3_min_angle = 30
s3_max_angle = 200
s4_type = angle180
s4_min_angle = 10
s4_max_angle = 170
s5_type = angle180
s6_type = angle180
""",
        encoding="utf-8",
    )

    config = load_config(["--config", str(config_path)])

    assert config.servo_angle_limits[0] is None
    assert config.servo_angle_limits[1] is None
    assert config.servo_angle_limits[2] == (30, 200)
    assert config.servo_angle_limits[3] == (10, 170)


def test_load_config_rejects_angle_limits_for_continuous_servo(tmp_path):
    config_path = tmp_path / "sensorscreen.conf"
    config_path.write_text(
        """[bot]
bot_ip = 127.0.0.1

[servos]
s1_type = continuous
s1_min_angle = 10
s2_type = continuous
s3_type = angle270
s4_type = angle270
s5_type = angle180
s6_type = angle180
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        load_config(["--config", str(config_path)])


def test_load_config_parses_gamepad_action_mapping(tmp_path):
    config_path = tmp_path / "sensorscreen.conf"
    config_path.write_text(
        """[bot]
bot_ip = 127.0.0.1

[servos]
s1_type = continuous
s2_type = continuous
s3_type = angle270
s4_type = angle270
s5_type = angle180
s6_type = angle180

[gamepad]
left_bumber = gamepad_callbacks.set_angle(servonumber=2,minvalue=0,maxvalue=270,bumpervalue=$value)
button_a = gamepad_callbacks.set_led(red=255,green=0,blue=0,buttonvalue=$value)
""",
        encoding="utf-8",
    )

    config = load_config(["--config", str(config_path)])

    assert "left_bumper" in config.gamepad_actions
    assert "left_bumber" not in config.gamepad_actions
    assert "button_a" in config.gamepad_actions


def test_load_config_rejects_unknown_gamepad_key(tmp_path):
    config_path = tmp_path / "sensorscreen.conf"
    config_path.write_text(
        """[bot]
bot_ip = 127.0.0.1

[servos]
s1_type = continuous
s2_type = continuous
s3_type = angle270
s4_type = angle270
s5_type = angle180
s6_type = angle180

[gamepad]
button_start = gamepad_callbacks.set_led(red=255,green=0,blue=0,buttonvalue=$value)
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        load_config(["--config", str(config_path)])


def test_configured_button_action_uses_boolean_value():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "button_a": "gamepad_callbacks.set_led(red=255,green=0,blue=0,buttonvalue=$value)",
        },
    )

    manager._run_action("button_a", True, client, controls)
    manager._run_action("button_a", False, client, controls)

    assert client.commands == [
        ("led", (proto.LED_MASK_ALL, 255, 0, 0, 255)),
        ("led", (proto.LED_MASK_ALL, 0, 0, 0, 255)),
    ]


def test_configured_stick_mapping_routes_to_custom_servo_channel():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "left_stick_y": "gamepad_callbacks.set_speed(servonumber=1,speedvalue=$value)",
        },
    )
    manager.joystick = FakeJoystick(axes=[0.0, 0.4, 0.0, 0.0, -1.0, -1.0])

    manager.apply_controls(client, controls)

    assert client.commands == [("speed", (1, -40, False))]
    assert controls.channels[1].value == -40


def test_configured_right_stick_x_mapping_routes_to_custom_servo_channel():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "right_stick_x": "gamepad_callbacks.set_speed(servonumber=1,speedvalue=$value)",
        },
    )
    manager.joystick = FakeJoystick(axes=[0.0, 0.0, -0.35, 0.0, -1.0, -1.0])

    manager.apply_controls(client, controls)

    assert client.commands == [("speed", (1, 35, False))]
    assert controls.channels[1].value == 35


def test_constant_boolean_mapping_without_value_placeholder_is_supported():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "button_guide": "gamepad_callbacks.set_led(red=0,green=0,blue=0,buttonvalue=true)",
        },
    )

    manager._run_action("button_guide", True, client, controls)

    assert client.commands == [
        ("led", (proto.LED_MASK_ALL, 0, 0, 0, 255)),
    ]


def test_button_action_without_value_placeholder_runs_once_on_press_only():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "button_guide": "gamepad_callbacks.play(filename=\"jarvis.wav\")",
        },
    )

    manager._run_action("button_guide", True, client, controls)
    manager._run_action("button_guide", False, client, controls)

    assert client.commands == [
        ("play", ("jarvis.wav",)),
    ]


def test_runtime_callback_error_isolated_without_crash():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "left_trigger": "gamepad_callbacks.set_angle(servonumber=0,minvalue=0,maxvalue=180)",
        },
    )

    manager._run_action("left_trigger", 0.5, client, controls)

    assert client.commands == []


def test_invalid_servo_channel_mapping_does_not_crash_control_loop():
    client = FakeCommandClient()
    controls = _controls(client)
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None,) * proto.SERVO_COUNT,
        {
            "left_stick_y": "gamepad_callbacks.set_speed(servonumber=99,speedvalue=$value)",
        },
    )
    manager.joystick = FakeJoystick(axes=[0.0, 0.5, 0.0, 0.0, -1.0, -1.0])

    manager.apply_controls(client, controls)

    assert client.commands == []