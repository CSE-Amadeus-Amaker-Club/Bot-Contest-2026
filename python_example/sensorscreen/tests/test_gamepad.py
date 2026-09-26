import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from config import load_config
from gamepad_manager import GamepadManager
import protocol as proto
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


def _controls(client):
    return ServoControls(
        client,
        600,
        400,
        (proto.SERVO_TYPE_CONTINUOUS, proto.SERVO_TYPE_CONTINUOUS,
         proto.SERVO_TYPE_270, proto.SERVO_TYPE_270,
         proto.SERVO_TYPE_180, proto.SERVO_TYPE_180),
    )


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
        ("speed", (0, -50, False)),
        ("speed", (1, 25, False)),
        ("angle", (2, 270, False)),
        ("angle", (3, 0, False)),
    ]
    assert [channel.value for channel in controls.channels[:4]] == [-50, 25, 270, 0]


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
    ]
    assert [channel.value for channel in controls.channels[:4]] == [0, 0, 0, 0]


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
        ("angle", (2, 0, False)),
        ("angle", (3, 0, False)),
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
        ("angle", (2, 270, False)),
        ("angle", (3, 270, False)),
    ]


def test_custom_angle_limits_are_applied_to_trigger_mapping():
    client = FakeCommandClient()
    controls = _controls(client)
    joystick = FakeJoystick(axes=[0.0] * 6, buttons=[0, 0, 0, 0, 1, 0])
    manager = GamepadManager(
        tuple(channel.servo_type for channel in controls.channels),
        (None, None, (20, 200), (10, 90), None, None),
    )
    manager.joystick = joystick

    manager.apply_controls(client, controls)

    assert client.commands == [
        ("speed", (0, 0, False)),
        ("speed", (1, 0, False)),
        ("angle", (2, 200, False)),
        ("angle", (3, 47, False)),
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