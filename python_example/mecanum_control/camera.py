"""Bounded multipart MJPEG reader, independent from the control session."""

from __future__ import annotations

import threading
import time
from email.message import Message
from email.parser import BytesHeaderParser

import requests

MAX_FRAME = 1024 * 1024
MAX_HEADER = 4096


def stream_boundary(content_type: str) -> bytes:
    message = Message()
    message["content-type"] = content_type
    boundary = message.get_param("boundary")
    if message.get_content_type() != "multipart/x-mixed-replace" or not isinstance(boundary, str):
        raise ValueError("Camera did not return multipart MJPEG")
    if not boundary or len(boundary) > 70 or "\r" in boundary or "\n" in boundary:
        raise ValueError("Invalid multipart boundary")
    return boundary.encode("ascii")


class MultipartFrames:
    def __init__(self, boundary: bytes) -> None:
        self.marker = b"--" + boundary
        self.buffer = bytearray()
        self.length: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        self.buffer.extend(chunk)
        frames = []
        while True:
            if self.length is None:
                index = self.buffer.find(self.marker)
                if index < 0:
                    if len(self.buffer) > MAX_HEADER:
                        raise ValueError("Camera boundary not found")
                    break
                header_start = index + len(self.marker)
                header_end = self.buffer.find(b"\r\n\r\n", header_start)
                if header_end < 0:
                    if len(self.buffer) > MAX_HEADER:
                        raise ValueError("Camera headers too large")
                    break
                headers = BytesHeaderParser().parsebytes(bytes(self.buffer[header_start:header_end]).lstrip(b"\r\n"))
                if headers.get_content_type() != "image/jpeg":
                    raise ValueError("Camera part is not JPEG")
                try:
                    length = int(headers["content-length"])
                except (TypeError, ValueError) as error:
                    raise ValueError("Invalid camera Content-Length") from error
                if not 4 <= length <= MAX_FRAME:
                    raise ValueError("Camera frame size is invalid")
                del self.buffer[:header_end + 4]
                self.length = length
            if len(self.buffer) < self.length:
                break
            frame = bytes(self.buffer[:self.length])
            del self.buffer[:self.length]
            self.length = None
            if not frame.startswith(b"\xff\xd8") or not frame.endswith(b"\xff\xd9"):
                raise ValueError("Invalid JPEG frame")
            frames.append(frame)
        if len(self.buffer) > MAX_FRAME + MAX_HEADER:
            raise ValueError("Camera buffer limit exceeded")
        return frames


class CameraStream:
    def __init__(self, url: str) -> None:
        self.url = url
        self.status = "Video disconnected"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._frame: tuple[bytes, float] | None = None
        self._response: requests.Response | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="mecanum-camera", daemon=True)
        self._thread.start()

    def take_frame(self) -> tuple[bytes, float] | None:
        with self._lock:
            frame, self._frame = self._frame, None
            return frame

    def close(self) -> None:
        self._stop.set()

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float = 3) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        with requests.Session() as session:
            session.trust_env = False
            while not self._stop.is_set():
                self.status = "Connecting video"
                try:
                    with session.get(self.url, stream=True, timeout=(1, 1)) as response:
                        self._response = response
                        response.raise_for_status()
                        parser = MultipartFrames(stream_boundary(response.headers.get("content-type", "")))
                        for chunk in response.iter_content(chunk_size=1024):
                            if self._stop.is_set():
                                break
                            for frame in parser.feed(chunk):
                                with self._lock:
                                    self._frame = (frame, time.monotonic())
                                self.status = "Video live"
                        if not self._stop.is_set():
                            raise ValueError("Camera stream ended")
                except (requests.RequestException, ValueError) as error:
                    self.status = f"Video unavailable: {error}"
                    with self._lock:
                        self._frame = None
                finally:
                    self._response = None
                self._stop.wait(1)
        self.status = "Video disconnected"