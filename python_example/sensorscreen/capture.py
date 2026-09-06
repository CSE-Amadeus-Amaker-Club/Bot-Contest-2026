"""Raw LIDAR frame capture for diagnosing sensor and transport anomalies."""

from __future__ import annotations

import json
import time
from pathlib import Path

from protocol import LidarFrame


class LidarCapture:
    """Append complete received LIDAR frames to a JSONL file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("a", encoding="utf-8", buffering=1)
        self.path = path

    def write(self, frame: LidarFrame) -> None:
        record = {
            "host_time_unix_s": time.time(),
            "frame_id": frame.frame_id,
            "sensor_timestamp_ms": frame.timestamp_ms,
            "point_count": len(frame.values),
            "distances_mm": frame.values,
        }
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")

    def close(self) -> None:
        self._file.close()
