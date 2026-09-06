"""Interactive six-channel servo controls for the SensorsScreen OpenCV dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Protocol

import cv2
import numpy as np

import protocol as proto

FONT = cv2.FONT_HERSHEY_SIMPLEX
SERVO_BAND_H = 220
DRAG_COMMAND_INTERVAL_S = 0.1
MODE_TYPES = (proto.SERVO_TYPE_180, proto.SERVO_TYPE_270, proto.SERVO_TYPE_CONTINUOUS)
MODE_LABELS = ("180", "270", "CONT")


class ServoCommandClient(Protocol):
    def queue_set_servo_type(self, channel: int, servo_type: int) -> None: ...

    def queue_set_servo_speed(self, channel: int, speed: int, force: bool = False) -> None: ...

    def queue_set_servo_angle(self, channel: int, angle: int, force: bool = False) -> None: ...

    def queue_stop_all_motors(self) -> None: ...

    def command_status(self, status_key: str) -> str: ...


@dataclass
class ServoChannel:
    servo_type: int
    value: int = 0
    last_sent_at: float = 0.0


class ServoControls:
    """Owns servo UI state, hit testing, and non-blocking command dispatch."""

    def __init__(self, client: ServoCommandClient, width: int, top: int, servo_types: tuple[int, ...]) -> None:
        if len(servo_types) != proto.SERVO_COUNT:
            raise ValueError(f"expected {proto.SERVO_COUNT} servo types")
        self.client = client
        self.width = width
        self.top = top
        self.channels = [ServoChannel(servo_type) for servo_type in servo_types]
        self.dragging_channel: int | None = None

    def _column_bounds(self, channel: int) -> tuple[int, int, int, int]:
        margin = 8
        column_width = (self.width - margin * 2) // (proto.SERVO_COUNT + 1)
        x0 = margin + column_width + channel * column_width
        x1 = self.width - margin if channel == proto.SERVO_COUNT - 1 else x0 + column_width - 4
        return x0, self.top + 6, x1, self.top + SERVO_BAND_H - 6

    def _mode_bounds(self, channel: int, mode_index: int) -> tuple[int, int, int, int]:
        x0, _, x1, _ = self._column_bounds(channel)
        button_width = (x1 - x0 - 8) // len(MODE_TYPES)
        left = x0 + mode_index * (button_width + 4)
        return left, self.top + 38, left + button_width, self.top + 60

    def _slider_bounds(self, channel: int) -> tuple[int, int, int, int]:
        x0, _, x1, _ = self._column_bounds(channel)
        return x0 + 8, self.top + 122, x1 - 8, self.top + 146

    def _stop_bounds(self, channel: int) -> tuple[int, int, int, int]:
        x0, _, x1, _ = self._column_bounds(channel)
        return x0 + 8, self.top + 171, x1 - 8, self.top + 198

    def _stop_all_bounds(self) -> tuple[int, int, int, int]:
        margin = 8
        column_width = (self.width - margin * 2) // (proto.SERVO_COUNT + 1)
        x0 = margin
        x1 = x0 + column_width - 4
        return x0, self.top + 6, x1, self.top + SERVO_BAND_H - 6

    @staticmethod
    def _contains(bounds: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bounds
        return x0 <= x <= x1 and y0 <= y <= y1

    def _max_value(self, channel: int) -> int:
        servo_type = self.channels[channel].servo_type
        if servo_type == proto.SERVO_TYPE_270:
            return proto.SERVO_270_ANGLE_MAX
        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            return proto.SERVO_SPEED_MAX
        return proto.SERVO_180_ANGLE_MAX

    def _value_from_x(self, channel: int, x: int) -> int:
        x0, _, x1, _ = self._slider_bounds(channel)
        ratio = max(0.0, min(1.0, (x - x0) / max(1, x1 - x0)))
        if self.channels[channel].servo_type == proto.SERVO_TYPE_CONTINUOUS:
            return round(proto.SERVO_SPEED_MIN + ratio * (proto.SERVO_SPEED_MAX - proto.SERVO_SPEED_MIN))
        return round(ratio * self._max_value(channel))

    def _x_from_value(self, channel: int) -> int:
        x0, _, x1, _ = self._slider_bounds(channel)
        value = self.channels[channel].value
        if self.channels[channel].servo_type == proto.SERVO_TYPE_CONTINUOUS:
            ratio = (value - proto.SERVO_SPEED_MIN) / (proto.SERVO_SPEED_MAX - proto.SERVO_SPEED_MIN)
        else:
            ratio = value / self._max_value(channel)
        return round(x0 + max(0.0, min(1.0, ratio)) * (x1 - x0))

    def set_external_value(self, channel: int, value: int) -> None:
        """Update a rendered channel value without dispatching a command."""
        if not 0 <= channel < proto.SERVO_COUNT:
            raise ValueError(f"invalid servo channel: {channel}")
        minimum = proto.SERVO_SPEED_MIN if self.channels[channel].servo_type == proto.SERVO_TYPE_CONTINUOUS else 0
        self.channels[channel].value = max(minimum, min(self._max_value(channel), value))

    def _send_value(self, channel: int, force: bool = False) -> None:
        state = self.channels[channel]
        now = time.monotonic()
        if not force and now - state.last_sent_at < DRAG_COMMAND_INTERVAL_S:
            return
        if state.servo_type == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, state.value, force)
        else:
            self.client.queue_set_servo_angle(channel, state.value, force)
        state.last_sent_at = now

    def _set_mode(self, channel: int, servo_type: int) -> None:
        state = self.channels[channel]
        if state.servo_type == servo_type:
            return
        if state.servo_type == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, 0, force=True)
        state.servo_type = servo_type
        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            state.value = 0
            self.client.queue_set_servo_type(channel, servo_type)
            self.client.queue_set_servo_speed(channel, 0, force=True)
        else:
            state.value = max(0, min(state.value, self._max_value(channel)))
            self.client.queue_set_servo_type(channel, servo_type)

    def _set_value_from_x(self, channel: int, x: int, force: bool = False) -> None:
        self.channels[channel].value = self._value_from_x(channel, x)
        self._send_value(channel, force)

    def handle_mouse(self, event: int, x: int, y: int, flags: int, _param: object | None = None) -> None:
        """Handle OpenCV mouse events for mode buttons, sliders, and stop controls."""
        if event == cv2.EVENT_LBUTTONDOWN:
            if self._contains(self._stop_all_bounds(), x, y):
                self.client.queue_stop_all_motors()
                return
            for channel in range(proto.SERVO_COUNT):
                for mode_index, servo_type in enumerate(MODE_TYPES):
                    if self._contains(self._mode_bounds(channel, mode_index), x, y):
                        self._set_mode(channel, servo_type)
                        return
                if self._contains(self._stop_bounds(channel), x, y):
                    if self.channels[channel].servo_type == proto.SERVO_TYPE_CONTINUOUS:
                        self.channels[channel].value = 0
                        self._send_value(channel, force=True)
                    return
                if self._contains(self._slider_bounds(channel), x, y):
                    self.dragging_channel = channel
                    self._set_value_from_x(channel, x)
                    return
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging_channel is not None:
            if flags & cv2.EVENT_FLAG_LBUTTON:
                self._set_value_from_x(self.dragging_channel, x)
            else:
                self.dragging_channel = None
        elif event == cv2.EVENT_LBUTTONUP and self.dragging_channel is not None:
            self._set_value_from_x(self.dragging_channel, x, force=True)
            self.dragging_channel = None

    def render(self) -> np.ndarray:
        """Render the full-width six-channel control band."""
        band = np.zeros((SERVO_BAND_H, self.width, 3), dtype=np.uint8)
        band[:] = (24, 24, 24)
        stop_x0, stop_y0, stop_x1, stop_y1 = self._stop_all_bounds()
        stop_bounds = (stop_x0, stop_y0 - self.top, stop_x1, stop_y1 - self.top)
        cv2.rectangle(band, stop_bounds[:2], stop_bounds[2:], (30, 30, 150), -1)
        text_size = cv2.getTextSize("STOP", FONT, 0.9, 2)[0]
        text_x = stop_bounds[0] + (stop_bounds[2] - stop_bounds[0] - text_size[0]) // 2
        mid_y = (stop_bounds[1] + stop_bounds[3]) // 2
        cv2.putText(band, "STOP", (text_x, mid_y - 4), FONT, 0.9, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(band, "ALL", (text_x, mid_y + 30), FONT, 0.9, (255, 255, 255), 2, cv2.LINE_AA)

        for channel, state in enumerate(self.channels):
            x0, y0, x1, y1 = self._column_bounds(channel)
            local_bounds = (x0, y0 - self.top, x1, y1 - self.top)
            cv2.rectangle(band, local_bounds[:2], local_bounds[2:], (70, 70, 70), 1)
            cv2.putText(band, f"S{channel + 1}", (x0 + 8, 22), FONT, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
            status = self.client.command_status(f"servo-{channel}")
            status_color = (80, 220, 80) if status == "OK" else (80, 190, 240) if status in ("READY", "QUEUED", "SENT") else (70, 70, 230)
            cv2.putText(band, status, (x0 + 38, 22), FONT, 0.36, status_color, 1, cv2.LINE_AA)

            for mode_index, servo_type in enumerate(MODE_TYPES):
                mx0, my0, mx1, my1 = self._mode_bounds(channel, mode_index)
                bounds = (mx0, my0 - self.top, mx1, my1 - self.top)
                selected = state.servo_type == servo_type
                color = (95, 130, 55) if selected else (55, 55, 55)
                cv2.rectangle(band, bounds[:2], bounds[2:], color, -1)
                cv2.putText(band, MODE_LABELS[mode_index], (bounds[0] + 3, bounds[1] + 15), FONT, 0.34, (240, 240, 240), 1, cv2.LINE_AA)

            sx0, sy0, sx1, sy1 = self._slider_bounds(channel)
            sy = (sy0 + sy1) // 2 - self.top
            cv2.line(band, (sx0, sy), (sx1, sy), (100, 100, 100), 2, cv2.LINE_AA)
            if state.servo_type == proto.SERVO_TYPE_CONTINUOUS:
                center = (sx0 + sx1) // 2
                cv2.line(band, (center, sy - 7), (center, sy + 7), (120, 120, 120), 1, cv2.LINE_AA)
                value_text = f"{state.value:+d}%"
            else:
                value_text = f"{state.value} deg"
            cv2.circle(band, (self._x_from_value(channel), sy), 7, (0, 190, 255), -1, cv2.LINE_AA)
            cv2.putText(band, value_text, (sx0, sy + 34), FONT, 0.46, (230, 230, 230), 1, cv2.LINE_AA)

            bx0, by0, bx1, by1 = self._stop_bounds(channel)
            bounds = (bx0, by0 - self.top, bx1, by1 - self.top)
            enabled = state.servo_type == proto.SERVO_TYPE_CONTINUOUS
            cv2.rectangle(band, bounds[:2], bounds[2:], (35, 35, 120) if enabled else (48, 48, 48), -1)
            cv2.putText(band, "STOP" if enabled else "HOLD", (bounds[0] + 8, bounds[1] + 19), FONT, 0.44, (240, 240, 240) if enabled else (130, 130, 130), 1, cv2.LINE_AA)
        return band