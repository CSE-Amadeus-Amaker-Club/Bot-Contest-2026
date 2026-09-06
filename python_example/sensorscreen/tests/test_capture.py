import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture import LidarCapture
from protocol import LidarFrame


def test_capture_writes_complete_lidar_record(tmp_path):
    path = tmp_path / "captures" / "lidar.jsonl"
    capture = LidarCapture(path)
    capture.write(LidarFrame(frame_id=7, timestamp_ms=1234, values=[100, 2500, 5000]))
    capture.close()

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["frame_id"] == 7
    assert record["sensor_timestamp_ms"] == 1234
    assert record["point_count"] == 3
    assert record["distances_mm"] == [100, 2500, 5000]
    assert isinstance(record["host_time_unix_s"], float)
