"""Direct K10 physical-display screen controls for the SensorsScreen dashboard."""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

import protocol as proto

FONT = cv2.FONT_HERSHEY_SIMPLEX
SCREEN_BAND_H = 52
SCREEN_BUTTONS = (
    ("SPLASH", proto.UI_SCREEN_SPLASH),
    ("APP INFO", proto.UI_SCREEN_APP_INFO),
    ("SENSORS", proto.UI_SCREEN_SENSORS),
    ("APP LOG", proto.UI_SCREEN_APP_LOG),
    ("SVC LOG", proto.UI_SCREEN_SERVICE_LOG),
    ("DEBUG", proto.UI_SCREEN_DEBUG_LOG),
    ("ESP LOG", proto.UI_SCREEN_ESP_LOG),
)


class ScreenCommandClient(Protocol):
    def queue_set_screen(self, screen: int) -> None: ...

    def command_status(self, status_key: str) -> str: ...


class ScreenControls:
    """Owns direct K10 screen selection buttons and their acknowledgement display."""

    def __init__(self, client: ScreenCommandClient, width: int, top: int) -> None:
        self.client = client
        self.width = width
        self.top = top
        self.selected_screen: int | None = None

    def _button_bounds(self, button_index: int) -> tuple[int, int, int, int]:
        margin = 8
        gap = 5
        button_width = (self.width - margin * 2 - gap * (len(SCREEN_BUTTONS) - 1)) // len(SCREEN_BUTTONS)
        x0 = margin + button_index * (button_width + gap)
        x1 = self.width - margin if button_index == len(SCREEN_BUTTONS) - 1 else x0 + button_width
        return x0, self.top + 5, x1, self.top + 31

    @staticmethod
    def _contains(bounds: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bounds
        return x0 <= x <= x1 and y0 <= y <= y1

    def handle_mouse(self, event: int, x: int, y: int) -> None:
        """Send the matching UI-service request when a screen button is clicked."""
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for button_index, (_, screen) in enumerate(SCREEN_BUTTONS):
            if self._contains(self._button_bounds(button_index), x, y):
                self.selected_screen = screen
                self.client.queue_set_screen(screen)
                return

    def render(self) -> np.ndarray:
        """Render a fixed-width row of direct display screen controls."""
        band = np.zeros((SCREEN_BAND_H, self.width, 3), dtype=np.uint8)
        band[:] = (24, 24, 24)
        for button_index, (label, screen) in enumerate(SCREEN_BUTTONS):
            x0, y0, x1, y1 = self._button_bounds(button_index)
            local_bounds = (x0, y0 - self.top, x1, y1 - self.top)
            selected = screen == self.selected_screen
            color = (95, 130, 55) if selected else (55, 55, 55)
            cv2.rectangle(band, local_bounds[:2], local_bounds[2:], color, -1)
            text_size = cv2.getTextSize(label, FONT, 0.37, 1)[0]
            text_x = local_bounds[0] + (local_bounds[2] - local_bounds[0] - text_size[0]) // 2
            cv2.putText(band, label, (text_x, local_bounds[1] + 18), FONT, 0.37, (240, 240, 240), 1, cv2.LINE_AA)

        status = self.client.command_status("k10-screen")
        status_color = (80, 220, 80) if status == "OK" else (80, 190, 240) if status in ("READY", "QUEUED", "SENT") else (70, 70, 230)
        cv2.putText(band, f"K10 DISPLAY: {status}", (8, 46), FONT, 0.36, status_color, 1, cv2.LINE_AA)
        return band