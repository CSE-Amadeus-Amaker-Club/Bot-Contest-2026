import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from servo_controls import ServoControls
from state import SensorState
from udp_client import SensorUDPClient


class FakeCommandClient:
    def __init__(self):
        self.commands: list[tuple[str, tuple]] = []

    def queue_set_servo_type(self, *args):
        self.commands.append(("type", args))

    def queue_set_servo_speed(self, channel, speed, force=False):
        self.commands.append(("speed", (channel, speed, force)))

    def queue_set_servo_angle(self, *args):
        self.commands.append(("angle", args))

    def queue_stop_all_motors(self):
        self.commands.append(("stop-all", ()))

    def command_status(self, _status_key):
        return "READY"


def test_positional_drag_sends_current_value_and_final_release_value():
    client = FakeCommandClient()
    controls = ServoControls(client, 600, 400, (proto.SERVO_TYPE_180,) * proto.SERVO_COUNT)
    x0, y0, x1, y1 = controls._slider_bounds(0)
    y = (y0 + y1) // 2

    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, x1, y, cv2.EVENT_FLAG_LBUTTON)
    controls.handle_mouse(cv2.EVENT_LBUTTONUP, x1, y, 0)

    assert client.commands == [("angle", (0, 180, False)), ("angle", (0, 180, True))]


def test_continuous_mode_stops_before_and_after_mode_transition():
    client = FakeCommandClient()
    controls = ServoControls(client, 600, 400, (proto.SERVO_TYPE_180,) * proto.SERVO_COUNT)
    x0, y0, x1, y1 = controls._mode_bounds(0, 2)

    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (x0 + x1) // 2, (y0 + y1) // 2, cv2.EVENT_FLAG_LBUTTON)

    assert client.commands == [
        ("type", (0, proto.SERVO_TYPE_CONTINUOUS)),
        ("speed", (0, 0, True)),
    ]


def test_runtime_queue_coalesces_drag_updates_until_acknowledged():
    client = SensorUDPClient("127.0.0.1", proto.DEFAULT_PORT, "00000", 0.1, SensorState())
    sent: list[bytes] = []
    client._send = sent.append
    try:
        client.queue_set_servo_angle(0, 10)
        client.queue_set_servo_angle(0, 20)
        client.queue_set_servo_angle(0, 30)

        assert sent == [proto.build_set_servos_angle(0x01, 10)]
        client._dispatch(bytes([0x24, proto.RESP_OK]))
        assert sent == [
            proto.build_set_servos_angle(0x01, 10),
            proto.build_set_servos_angle(0x01, 30),
        ]
        client._dispatch(bytes([0x24, proto.RESP_OK]))
        assert client.command_status("servo-0") == "OK"
    finally:
        client.sock.close()