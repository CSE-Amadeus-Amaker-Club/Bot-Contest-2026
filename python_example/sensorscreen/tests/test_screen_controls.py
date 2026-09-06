import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from screen_controls import SCREEN_BUTTONS, ScreenControls


class FakeScreenClient:
    def __init__(self):
        self.screens: list[int] = []

    def queue_set_screen(self, screen: int) -> None:
        self.screens.append(screen)

    def command_status(self, _status_key: str) -> str:
        return "READY"


def test_each_screen_button_queues_its_firmware_index():
    client = FakeScreenClient()
    controls = ScreenControls(client, 976, 32)

    for button_index, (_, screen) in enumerate(SCREEN_BUTTONS):
        x0, y0, x1, y1 = controls._button_bounds(button_index)
        controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (x0 + x1) // 2, (y0 + y1) // 2)

    assert client.screens == list(range(proto.UI_SCREEN_COUNT))
    assert controls.selected_screen == proto.UI_SCREEN_ESP_LOG