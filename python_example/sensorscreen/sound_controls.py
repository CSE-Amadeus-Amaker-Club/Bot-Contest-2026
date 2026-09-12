"""HTTP sound selection and playback controls for the SensorsScreen dashboard."""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import cv2
import numpy as np

logger = logging.getLogger("sensorscreen.sounds")
FONT = cv2.FONT_HERSHEY_SIMPLEX
SOUND_BAND_H = 170
DROP_DOWN_BOUNDS = (8, 5, 350, 31)
PLAY_BOUNDS = (358, 5, 430, 31)
REFRESH_BOUNDS = (438, 5, 472, 31)
OPTION_TOP = 36
OPTION_H = 24
MAX_VISIBLE_SOUNDS = 5
REFRESH_INTERVAL_S = 5.0


SCROLLBAR_W = 14
SCROLLBAR_PAD = 2


def parse_sound_list(payload: bytes | str) -> list[str]:
    """Extract displayable sound filenames from a GET /sounds response."""
    data = json.loads(payload)
    sounds = data.get("sounds", [])
    if not isinstance(sounds, list):
        return []
    return sorted({sound for sound in sounds if isinstance(sound, str) and sound}, key=str.casefold)


class SoundControls:
    """Owns board sound discovery, dropdown selection, and HTTP playback."""

    def __init__(self, ip: str, timeout: float) -> None:
        self.base_url = f"http://{ip}"
        self.timeout = timeout
        self.sounds: list[str] = []
        self.selected_sound: str | None = None
        self.expanded = False
        self.scroll_offset = 0
        self.dragging_scrollbar = False
        self.status = "LOADING"
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._refresh_requested = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="sound-controls", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._refresh_requested.set()
        self._thread.join(timeout=self.timeout + 0.5)

    def _request(self, path: str) -> bytes:
        request = Request(f"{self.base_url}{path}", method="GET")
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _max_scroll_offset(self) -> int:
        return max(0, len(self.sounds) - MAX_VISIBLE_SOUNDS)

    def _clamp_scroll(self) -> None:
        self.scroll_offset = max(0, min(self.scroll_offset, self._max_scroll_offset()))

    def _refresh(self) -> None:
        try:
            sounds = parse_sound_list(self._request("/sounds"))
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Unable to refresh board sounds: %s", exc)
            with self._lock:
                self.status = "OFFLINE"
            return
        with self._lock:
            self.sounds = sounds
            if self.selected_sound not in sounds:
                self.selected_sound = sounds[0] if sounds else None
            self.status = f"{len(sounds)} SOUND{'S' if len(sounds) != 1 else ''}"
            self._clamp_scroll()

    def _worker(self) -> None:
        next_refresh = 0.0
        while not self._stop_event.is_set():
            if self._refresh_requested.is_set() or time.monotonic() >= next_refresh:
                self._refresh_requested.clear()
                self._refresh()
                next_refresh = time.monotonic() + REFRESH_INTERVAL_S
            self._stop_event.wait(0.25)

    def _play_selected(self) -> None:
        with self._lock:
            sound = self.selected_sound
            if not sound:
                self.status = "NO SOUNDS"
                return
            self.status = "PLAYING..."
        try:
            request = Request(f"{self.base_url}/sounds/{quote(sound, safe='')}/play", method="POST")
            with urlopen(request, timeout=self.timeout):
                pass
        except (HTTPError, URLError, OSError) as exc:
            logger.debug("Unable to play %s: %s", sound, exc)
            with self._lock:
                self.status = "PLAY FAILED"
            return
        with self._lock:
            self.status = f"PLAYING {sound[:22]}"

    @staticmethod
    def _contains(bounds: tuple[int, int, int, int], x: int, y: int) -> bool:
        x0, y0, x1, y1 = bounds
        return x0 <= x <= x1 and y0 <= y <= y1

    def _scrollbar_track_bounds(self, visible_count: int) -> tuple[int, int, int, int]:
        x1 = DROP_DOWN_BOUNDS[2] - SCROLLBAR_PAD
        x0 = x1 - SCROLLBAR_W
        y0 = OPTION_TOP
        y1 = OPTION_TOP + OPTION_H * visible_count
        return x0, y0, x1, y1

    def _scrollbar_thumb_bounds(self, visible_count: int, total_count: int) -> tuple[int, int, int, int]:
        tx0, ty0, tx1, ty1 = self._scrollbar_track_bounds(visible_count)
        track_h = ty1 - ty0
        if total_count <= visible_count or track_h <= 0:
            return tx0, ty0, tx1, ty1
        thumb_h = max(16, round(track_h * (visible_count / total_count)))
        max_offset = total_count - visible_count
        offset_ratio = self.scroll_offset / max_offset if max_offset > 0 else 0.0
        thumb_y0 = ty0 + round(offset_ratio * (track_h - thumb_h))
        thumb_y1 = thumb_y0 + thumb_h
        return tx0, thumb_y0, tx1, thumb_y1

    def _scroll_to_y(self, y: int, visible_count: int, total_count: int) -> None:
        tx0, ty0, tx1, ty1 = self._scrollbar_track_bounds(visible_count)
        track_h = ty1 - ty0
        if track_h <= 0 or total_count <= visible_count:
            return
        thumb_h = max(16, round(track_h * (visible_count / total_count)))
        usable_h = max(1, track_h - thumb_h)
        rel_y = max(0, min(usable_h, y - ty0 - thumb_h // 2))
        max_offset = total_count - visible_count
        self.scroll_offset = round((rel_y / usable_h) * max_offset)
        self._clamp_scroll()

    def handle_mouse(self, event: int, x: int, y: int, flags: int = 0) -> None:
        """Handle dropdown, scrolling, refresh, and play clicks in local band coordinates."""
        visible_count = min(len(self.sounds), MAX_VISIBLE_SOUNDS)
        total_count = len(self.sounds)
        needs_scrollbar = self.expanded and total_count > MAX_VISIBLE_SOUNDS

        if event == cv2.EVENT_MOUSEWHEEL:
            if self.expanded:
                # In OpenCV, flags carries the wheel delta (positive = up / scroll backwards, negative = down)
                # Some OpenCV versions or platforms pass wheel step sign directly in flags or high word of flags.
                # A positive delta scrolls up (offset decreases), negative scrolls down (offset increases).
                # If flags > 0, scroll up (-1 offset), if flags < 0, scroll down (+1 offset).
                if flags > 0:
                    self.scroll_offset = max(0, self.scroll_offset - 1)
                elif flags < 0:
                    self.scroll_offset = min(self._max_scroll_offset(), self.scroll_offset + 1)
                else:
                    # Fallback if flags is 0: if event triggered, advance down
                    self.scroll_offset = min(self._max_scroll_offset(), self.scroll_offset + 1)
            return

        if event == cv2.EVENT_LBUTTONUP:
            self.dragging_scrollbar = False
            return

        if event == cv2.EVENT_MOUSEMOVE:
            if self.dragging_scrollbar and needs_scrollbar:
                self._scroll_to_y(y, visible_count, total_count)
            return

        if event != cv2.EVENT_LBUTTONDOWN:
            return

        if self._contains(DROP_DOWN_BOUNDS, x, y):
            self.expanded = not self.expanded
            self.dragging_scrollbar = False
            if self.expanded:
                self._clamp_scroll()
            return

        if self._contains(REFRESH_BOUNDS, x, y):
            self.status = "LOADING"
            self._refresh_requested.set()
            return

        if self._contains(PLAY_BOUNDS, x, y):
            threading.Thread(target=self._play_selected, name="sound-play", daemon=True).start()
            return

        if self.expanded and OPTION_TOP <= y < OPTION_TOP + OPTION_H * visible_count:
            if needs_scrollbar and self._contains(self._scrollbar_track_bounds(visible_count), x, y):
                self.dragging_scrollbar = True
                self._scroll_to_y(y, visible_count, total_count)
                return

            row_index = (y - OPTION_TOP) // OPTION_H
            actual_index = self.scroll_offset + row_index
            with self._lock:
                if 0 <= actual_index < len(self.sounds):
                    self.selected_sound = self.sounds[actual_index]
            self.expanded = False
            self.dragging_scrollbar = False
            return

        # Clicking outside closes dropdown if expanded
        if self.expanded:
            self.expanded = False
            self.dragging_scrollbar = False

    def render(self) -> np.ndarray:
        """Render the sound dropdown and playback controls."""
        band = np.zeros((SOUND_BAND_H, 480, 3), dtype=np.uint8)
        band[:] = (24, 24, 24)
        with self._lock:
            selected = self.selected_sound or "NO SOUNDS FOUND"
            status = self.status
            sounds = list(self.sounds)
        self._clamp_scroll()

        cv2.putText(band, "SOUNDS", (8, SOUND_BAND_H - 10), FONT, 0.38, (150, 150, 150), 1, cv2.LINE_AA)
        cv2.rectangle(band, DROP_DOWN_BOUNDS[:2], DROP_DOWN_BOUNDS[2:], (55, 55, 55), -1)
        cv2.putText(band, selected[:37], (16, 22), FONT, 0.42, (240, 240, 240), 1, cv2.LINE_AA)
        arrow = "^" if self.expanded else "v"
        cv2.putText(band, arrow, (335, 22), FONT, 0.45, (180, 180, 180), 1, cv2.LINE_AA)
        for bounds, label in ((PLAY_BOUNDS, "PLAY"), (REFRESH_BOUNDS, "R")):
            cv2.rectangle(band, bounds[:2], bounds[2:], (55, 100, 55) if label == "PLAY" else (55, 55, 55), -1)
            text_size = cv2.getTextSize(label, FONT, 0.38, 1)[0]
            x = bounds[0] + (bounds[2] - bounds[0] - text_size[0]) // 2
            cv2.putText(band, label, (x, 22), FONT, 0.38, (240, 240, 240), 1, cv2.LINE_AA)
        cv2.putText(band, status[:58], (90, SOUND_BAND_H - 10), FONT, 0.38, (100, 210, 120), 1, cv2.LINE_AA)

        if self.expanded and sounds:
            visible_count = min(len(sounds), MAX_VISIBLE_SOUNDS)
            total_count = len(sounds)
            has_scroll = total_count > MAX_VISIBLE_SOUNDS
            item_right = DROP_DOWN_BOUNDS[2] - (SCROLLBAR_W + SCROLLBAR_PAD * 2) if has_scroll else DROP_DOWN_BOUNDS[2]

            visible_slice = sounds[self.scroll_offset : self.scroll_offset + visible_count]
            for index, sound in enumerate(visible_slice):
                y0 = OPTION_TOP + index * OPTION_H
                cv2.rectangle(band, (DROP_DOWN_BOUNDS[0], y0), (item_right, y0 + OPTION_H), (65, 65, 65), -1)
                cv2.rectangle(band, (DROP_DOWN_BOUNDS[0], y0), (item_right, y0 + OPTION_H), (45, 45, 45), 1)
                text_len = 38 if has_scroll else 42
                cv2.putText(band, sound[:text_len], (16, y0 + 17), FONT, 0.38, (240, 240, 240), 1, cv2.LINE_AA)

            if has_scroll:
                tx0, ty0, tx1, ty1 = self._scrollbar_track_bounds(visible_count)
                cv2.rectangle(band, (tx0, ty0), (tx1, ty1), (40, 40, 40), -1)
                cv2.rectangle(band, (tx0, ty0), (tx1, ty1), (55, 55, 55), 1)
                bx0, by0, bx1, by1 = self._scrollbar_thumb_bounds(visible_count, total_count)
                cv2.rectangle(band, (bx0 + 1, by0 + 1), (bx1 - 1, by1 - 1), (110, 110, 110), -1)

        return band