"""HTTP transport wrapper for board sound endpoints."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import quote
from urllib.request import Request, urlopen


class SoundHttpClient:
    """Small independent client for sound-related board HTTP requests."""

    def __init__(self, ip: str, timeout: float) -> None:
        self.base_url = f"http://{ip}"
        self.timeout = timeout

    def request(self, path: str, method: str = "GET") -> bytes:
        request = Request(f"{self.base_url}{path}", method=method)
        with urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def request_text(self, path: str, method: str = "GET") -> str:
        return self.request(path, method=method).decode("utf-8", errors="replace")

    def request_first_text(self, paths: Iterable[str], method: str = "GET") -> tuple[str, str]:
        last_error: Exception | None = None
        for path in paths:
            try:
                return path, self.request_text(path, method=method)
            except OSError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise OSError("no HTTP paths provided")

    def list_sounds(self) -> bytes:
        return self.request("/sounds", method="GET")

    def stop_sound(self) -> None:
        self.request("/sounds/stop", method="POST")

    def play_sound(self, filename: str) -> None:
        encoded = quote(filename, safe="")
        self.request(f"/sounds/{encoded}/play", method="POST")