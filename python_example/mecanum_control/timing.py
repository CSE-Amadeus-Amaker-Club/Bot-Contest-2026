"""Optional bounded, nonblocking timing collection with background JSONL writes."""

from __future__ import annotations

import json
import threading
from os import PathLike
from queue import Full, Queue


class JsonlObserver:
    """Append records on a writer thread; callbacks only attempt a queued copy.

    Construct before starting a session and close after joining it. Records must
    contain JSON-compatible values and must not be mutated after submission.
    Queue overflow or write failures discard records, never control requests.
    Only construction/close may block on disk; stats expose incomplete capture.
    """

    def __init__(self, path: str | PathLike[str], *, capacity: int = 1024) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Observer capacity must be positive")
        self._queue: Queue[dict[str, object] | None] = Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._closed = False
        self._written = 0
        self._dropped = 0
        self._error: str | None = None
        self._file = open(path, "a", encoding="utf-8", buffering=1)
        self._thread = threading.Thread(target=self._write_loop, name="mecanum-timing", daemon=True)
        self._thread.start()

    def __call__(self, record: dict[str, object]) -> None:
        with self._lock:
            if self._closed:
                self._dropped += 1
                return
            try:
                self._queue.put_nowait(dict(record))
            except Full:
                self._dropped += 1

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {"written": self._written, "dropped": self._dropped, "error": self._error}

    def close(self) -> None:
        with self._lock:
            first_close = not self._closed
            self._closed = True
        if first_close:
            self._queue.put(None)
        self._thread.join()

    def __enter__(self) -> JsonlObserver:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _write_loop(self) -> None:
        with self._file:
            while True:
                record = self._queue.get()
                if record is None:
                    return
                try:
                    self._file.write(json.dumps(record, allow_nan=False) + "\n")
                except Exception as error:
                    with self._lock:
                        self._dropped += 1
                        self._error = type(error).__name__
                else:
                    with self._lock:
                        self._written += 1