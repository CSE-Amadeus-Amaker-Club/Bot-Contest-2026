"""Interactive HuskyLens controls for the SensorsScreen dashboard."""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
PANEL_W = 480
ILLUMINATION_BOUNDS = (318, 5, 368, 31)
RGB_LIGHT_BOUNDS = (372, 5, 422, 31)
DISPLAY_BOUNDS = (426, 5, PANEL_W - 10, 31)
BUTTON_BOUNDS = ILLUMINATION_BOUNDS
ALGORITHM_BOUNDS = (92, 5, 308, 31)
ALGORITHM_PREVIOUS_BOUNDS = (92, 5, 120, 31)
ALGORITHM_NEXT_BOUNDS = (280, 5, 308, 31)
ALGORITHMS = (
    (0, "FACE"),
    (1, "TRACK"),
    (2, "OBJECT"),
    (3, "LINE"),
    (4, "COLOR"),
    (5, "TAG"),
)


class HuskylensControlClient(Protocol):
    def queue_set_huskylens_illumination(self, enabled: bool) -> None: ...

    def queue_set_huskylens_algorithm(self, algorithm: int) -> None: ...

    def queue_set_huskylens_rgb_light(self, enabled: bool) -> None: ...

    def queue_set_huskylens_display(self, enabled: bool) -> None: ...

    def command_status(self, status_key: str) -> str: ...


class HuskylensLightControl:
    """Owns the HuskyLens illumination and algorithm controls."""

    def __init__(self, client: HuskylensControlClient) -> None:
        self.client = client
        self.enabled = False
        self.rgb_light_enabled = False
        self.display_enabled = True
        self.algorithm_index = len(ALGORITHMS) - 1

    @staticmethod
    def _contains(x: int, y: int) -> bool:
        x0, y0, x1, y1 = BUTTON_BOUNDS
        return x0 <= x <= x1 and y0 <= y <= y1

    @staticmethod
    def _contains_bounds(x: int, y: int, bounds: tuple[int, int, int, int]) -> bool:
        x0, y0, x1, y1 = bounds
        return x0 <= x <= x1 and y0 <= y <= y1

    def handle_mouse(self, event: int, x: int, y: int) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if self._contains(x, y):
            self.enabled = not self.enabled
            self.client.queue_set_huskylens_illumination(self.enabled)
        elif self._contains_bounds(x, y, RGB_LIGHT_BOUNDS):
            self.rgb_light_enabled = not self.rgb_light_enabled
            self.client.queue_set_huskylens_rgb_light(self.rgb_light_enabled)
        elif self._contains_bounds(x, y, DISPLAY_BOUNDS):
            self.display_enabled = not self.display_enabled
            self.client.queue_set_huskylens_display(self.display_enabled)
        elif self._contains_bounds(x, y, ALGORITHM_PREVIOUS_BOUNDS):
            self._select_algorithm(-1)
        elif self._contains_bounds(x, y, ALGORITHM_NEXT_BOUNDS):
            self._select_algorithm(1)

    def _select_algorithm(self, offset: int) -> None:
        self.algorithm_index = (self.algorithm_index + offset) % len(ALGORITHMS)
        self.client.queue_set_huskylens_algorithm(ALGORITHMS[self.algorithm_index][0])

    def render(self, panel: np.ndarray) -> None:
        self._render_toggle(panel, ILLUMINATION_BOUNDS, "LED", self.enabled, "huskylens-illumination")
        self._render_toggle(panel, RGB_LIGHT_BOUNDS, "RGB", self.rgb_light_enabled, "huskylens-rgb-light")
        self._render_toggle(panel, DISPLAY_BOUNDS, "LCD", self.display_enabled, "huskylens-display")

        ax0, ay0, ax1, ay1 = ALGORITHM_BOUNDS
        previous_x0, _, previous_x1, _ = ALGORITHM_PREVIOUS_BOUNDS
        next_x0, _, next_x1, _ = ALGORITHM_NEXT_BOUNDS
        algorithm_status = self.client.command_status("huskylens-algorithm")
        algorithm_label = f"MODE {ALGORITHMS[self.algorithm_index][1]}"
        status_color = self._status_color(algorithm_status)
        cv2.rectangle(panel, (ax0, ay0), (ax1, ay1), (55, 55, 55), -1)
        cv2.rectangle(panel, (previous_x0, ay0), (previous_x1, ay1), (75, 75, 75), -1)
        cv2.rectangle(panel, (next_x0, ay0), (next_x1, ay1), (75, 75, 75), -1)
        cv2.putText(panel, "<", (previous_x0 + 9, ay0 + 18), FONT, 0.52, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(panel, ">", (next_x0 + 8, ay0 + 18), FONT, 0.52, (240, 240, 240), 1, cv2.LINE_AA)
        text_size = cv2.getTextSize(algorithm_label, FONT, 0.35, 1)[0]
        text_x = ax0 + (ax1 - ax0 - text_size[0]) // 2
        cv2.putText(panel, algorithm_label, (text_x, ay0 + 13), FONT, 0.35, (240, 240, 240), 1, cv2.LINE_AA)
        text_size = cv2.getTextSize(algorithm_status, FONT, 0.25, 1)[0]
        text_x = ax0 + (ax1 - ax0 - text_size[0]) // 2
        cv2.putText(panel, algorithm_status, (text_x, ay0 + 24), FONT, 0.25, status_color, 1, cv2.LINE_AA)

    @staticmethod
    def _status_color(status: str) -> tuple[int, int, int]:
        if status == "OK":
            return (80, 220, 80)
        if status in ("READY", "QUEUED", "SENT"):
            return (80, 190, 240)
        return (70, 70, 230)

    @staticmethod
    def _short_status(status: str) -> str:
        if status == "resp_operation_failed":
            return "UNSUP"
        if status == "SEND FAILED":
            return "SEND"
        if status.startswith("resp_"):
            return status[5:10].upper()
        return status[:5]

    def _render_toggle(self, panel: np.ndarray, bounds: tuple[int, int, int, int], label: str, enabled: bool, status_key: str) -> None:
        x0, y0, x1, y1 = bounds
        status = self.client.command_status(status_key)
        status_color = self._status_color(status)
        button_color = (55, 130, 55) if enabled else (55, 55, 55)
        cv2.rectangle(panel, (x0, y0), (x1, y1), button_color, -1)
        cv2.rectangle(panel, (x0, y0), (x1, y1), status_color, 1)
        text_size = cv2.getTextSize(label, FONT, 0.33, 1)[0]
        cv2.putText(panel, label, (x0 + (x1 - x0 - text_size[0]) // 2, y0 + 13), FONT, 0.33, (240, 240, 240), 1, cv2.LINE_AA)
        short_status = self._short_status(status)
        text_size = cv2.getTextSize(short_status, FONT, 0.22, 1)[0]
        cv2.putText(panel, short_status, (x0 + (x1 - x0 - text_size[0]) // 2, y0 + 24), FONT, 0.22, status_color, 1, cv2.LINE_AA)