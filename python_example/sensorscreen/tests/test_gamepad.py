import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main
import protocol as proto
from servo_controls import ServoControls


class FakeCommandClient:
    def __init__(self):
        self.commands: list[tuple[str, tuple]] = []

    def queue_set_servo_speed(self, channel, speed, force=False):
        self.commands.append(("speed", (channel, speed, force)))

    def queue_set_servo_angle(self, channel, angle, force=False):
        self.commands.append(("angle", (channel, angle, force)))


class FakeJoystick:
    def __init__(self):
        self.axes = [0.0, 0.5, 0.0, -0.25, 1.0, -1.0]
        self.buttons = [0] * 6

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
    previous = {}

    main._apply_gamepad_controls(
        client,
        FakeJoystick(),
        tuple(channel.servo_type for channel in controls.channels),
        previous,
        controls,
    )

    assert client.commands == [
        ("speed", (0, -50, False)),
        ("speed", (1, 25, False)),
        ("angle", (2, 270, False)),
        ("angle", (3, 0, False)),
    ]
    assert [channel.value for channel in controls.channels[:4]] == [-50, 25, 270, 0]


def test_safe_positions_update_commands_and_rendered_cursor_values():
    client = FakeCommandClient()
    controls = _controls(client)
    for channel, value in enumerate((-50, 25, 270, 180)):
        controls.set_external_value(channel, value)

    main._set_gamepad_safe_positions(
        client,
        controls,
        tuple(channel.servo_type for channel in controls.channels),
    )

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

    main._apply_gamepad_controls(
        client,
        FakeJoystick(),
        tuple(channel.servo_type for channel in controls.channels),
        {},
        controls,
    )

    assert client.commands == []
    assert [channel.value for channel in controls.channels[:4]] == [0, 0, 0, 0]