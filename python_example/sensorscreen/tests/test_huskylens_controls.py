import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from huskylens_controls import (ALGORITHM_NEXT_BOUNDS, ALGORITHM_PREVIOUS_BOUNDS, DISPLAY_BOUNDS,
                                ILLUMINATION_BOUNDS, RGB_LIGHT_BOUNDS, HuskylensLightControl)


class FakeHuskylensClient:
    def __init__(self):
        self.illumination: list[bool] = []
        self.algorithms: list[int] = []
        self.rgb_light: list[bool] = []
        self.display: list[bool] = []

    def queue_set_huskylens_illumination(self, enabled: bool) -> None:
        self.illumination.append(enabled)

    def queue_set_huskylens_algorithm(self, algorithm: int) -> None:
        self.algorithms.append(algorithm)

    def queue_set_huskylens_rgb_light(self, enabled: bool) -> None:
        self.rgb_light.append(enabled)

    def queue_set_huskylens_display(self, enabled: bool) -> None:
        self.display.append(enabled)

    def command_status(self, _status_key: str) -> str:
        return "READY"


def test_algorithm_buttons_cycle_and_queue_the_selected_mode():
    client = FakeHuskylensClient()
    controls = HuskylensLightControl(client)
    previous_x0, previous_y0, previous_x1, previous_y1 = ALGORITHM_PREVIOUS_BOUNDS
    next_x0, next_y0, next_x1, next_y1 = ALGORITHM_NEXT_BOUNDS

    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (next_x0 + next_x1) // 2, (next_y0 + next_y1) // 2)
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (previous_x0 + previous_x1) // 2, (previous_y0 + previous_y1) // 2)
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (previous_x0 + previous_x1) // 2, (previous_y0 + previous_y1) // 2)

    assert client.algorithms == [proto.HUSKYLENS_ALGORITHM_FACE_RECOGNITION,
                                 proto.HUSKYLENS_ALGORITHM_TAG_RECOGNITION,
                                 proto.HUSKYLENS_ALGORITHM_COLOR_RECOGNITION]
    assert controls.algorithm_index == proto.HUSKYLENS_ALGORITHM_COLOR_RECOGNITION


def test_huskylens_control_buttons_queue_only_huskylens_requests():
    client = FakeHuskylensClient()
    controls = HuskylensLightControl(client)

    for bounds in (ILLUMINATION_BOUNDS, RGB_LIGHT_BOUNDS, DISPLAY_BOUNDS):
        x0, y0, x1, y1 = bounds
        controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (x0 + x1) // 2, (y0 + y1) // 2)

    assert client.illumination == [True]
    assert client.rgb_light == [True]
    assert client.display == [False]