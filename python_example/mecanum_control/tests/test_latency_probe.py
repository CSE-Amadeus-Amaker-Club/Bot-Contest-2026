import json
import socket
import struct
import threading
from unittest.mock import MagicMock

import pytest

from mecanum_control import latency_probe, protocol


class LoopbackPing:
    def __init__(self, mode="ok"):
        self.mode = mode
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.02)
        self.port = self.sock.getsockname()[1]
        self.frames = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        trailer = struct.pack(">II", 7, 1234)
        while not self.stop.is_set():
            try:
                frame, sender = self.sock.recvfrom(128)
            except TimeoutError:
                continue
            self.frames.append(frame)
            if self.mode == "drop":
                continue
            if self.mode == "late":
                if len(self.frames) == 1:
                    continue
                self.sock.sendto(self.frames[0] + trailer, sender)
            if self.mode == "invalid":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as wrong_sender:
                    wrong_sender.sendto(frame + trailer, sender)
                self.sock.sendto(b"\x51\x00" + trailer, sender)
                request_id = struct.unpack(">I", frame[1:])[0]
                self.sock.sendto(protocol.ping((request_id + 1) & 0xFFFFFFFF) + trailer, sender)
                for length in range(8):
                    self.sock.sendto(frame + trailer[:length], sender)
                self.sock.sendto(frame + trailer + b"\x00", sender)
                self.sock.sendto(b"\x44\x00" + frame[1:] + trailer, sender)
                self.sock.sendto(b"\x44\x07" + trailer, sender)
            self.sock.sendto(frame + trailer, sender)

    def close(self):
        self.stop.set()
        self.thread.join(1)
        self.sock.close()


@pytest.mark.parametrize("request_id", [0, 0x01020304, 0xFFFFFFFF])
def test_ping_be32(request_id):
    assert protocol.ping(request_id) == b"\x44" + struct.pack(">I", request_id)


@pytest.mark.parametrize("request_id", [-1, 2**32, True, 1.5])
def test_ping_rejects_invalid_id(request_id):
    with pytest.raises(ValueError):
        protocol.ping(request_id)


def test_probe_validated_reply_and_unique_ids(monkeypatch):
    monkeypatch.setattr(latency_probe.secrets, "randbits", lambda _bits: 0xFFFFFFFF)
    bot = LoopbackPing()
    records = []
    try:
        summary = latency_probe.run_probe("127.0.0.1", bot.port, count=3,
                                          period=0.01, timing_observer=records.append)
        assert summary["replies"] == summary["attempted"] == 3
        assert summary["timeouts"] == summary["errors"] == 0
        assert [record["probe_id"] for record in records] == [0xFFFFFFFF, 0, 1]
        assert bot.frames == [protocol.ping(record["probe_id"]) for record in records]
        for record in records:
            assert record["action"] == 0x44 and record["status"] is None
            assert record["diagnostics"] == {"rx_sequence": 7, "server_millis": 1234}
            assert 0 <= record["rtt_ms"] < 100
            assert record["sent_monotonic_s"] <= record["ack_monotonic_s"] <= record["finished_monotonic_s"]
        ordered = sorted(record["rtt_ms"] for record in records)
        assert summary["median_ms"] == ordered[1]
        assert summary["p95_ms"] == summary["p99_ms"] == summary["max_ms"] == ordered[-1]
    finally:
        bot.close()


def test_probe_ignores_wrong_sender_action_id_and_diagnostics():
    bot = LoopbackPing("invalid")
    records = []
    try:
        summary = latency_probe.run_probe("127.0.0.1", bot.port, count=1, timing_observer=records.append)
        assert summary["replies"] == 1 and summary["timeouts"] == 0
        assert records[0]["rx_counts"] == {
            "received": 15, "wrong_sender": 1, "wrong_action": 1,
            "wrong_id": 1, "malformed": 11, "late": 0,
        }
    finally:
        bot.close()


def test_probe_timeout_drops_cadence_slots_without_catch_up():
    bot = LoopbackPing("drop")
    records = []
    try:
        summary = latency_probe.run_probe("127.0.0.1", bot.port, count=2,
                                          deadline=0.03, period=0.01, timing_observer=records.append)
        assert summary["timeouts"] == summary["attempted"] == 2
        assert summary["replies"] == 0
        assert summary["median_ms"] is summary["p95_ms"] is summary["p99_ms"] is summary["max_ms"] is None
        assert len(bot.frames) == 2 and bot.frames[0] != bot.frames[1]
        assert records[1]["sent_monotonic_s"] - records[0]["finished_monotonic_s"] >= 0.009
        assert all(record["error"] == "TimeoutError" and record["rtt_ms"] is None for record in records)
    finally:
        bot.close()


def test_probe_late_id_cannot_match_next_request():
    bot = LoopbackPing("late")
    records = []
    try:
        summary = latency_probe.run_probe("127.0.0.1", bot.port, count=2, deadline=0.02,
                                          period=0.01, timing_observer=records.append)
        assert summary["timeouts"] == summary["replies"] == 1
        assert records[0]["outcome"] == "timeout"
        assert records[1]["rx_counts"]["wrong_id"] == 1
    finally:
        bot.close()


def test_probe_cancelled_wait_closes_without_more_commands():
    bot = LoopbackPing("drop")
    stop = threading.Event()
    timer = threading.Timer(0.02, stop.set)
    timer.start()
    try:
        summary = latency_probe.run_probe("127.0.0.1", bot.port, count=3, deadline=0.5, stop=stop)
        assert summary["cancelled"] == summary["attempted"] == 1
        assert summary["stopped"] and len(bot.frames) == 1
        assert bot.frames[0][0] == 0x44
    finally:
        timer.cancel()
        timer.join()
        bot.close()


def test_probe_pre_cancelled_never_opens_socket(monkeypatch):
    stop = threading.Event()
    stop.set()
    sock = MagicMock()
    monkeypatch.setattr(latency_probe.socket, "socket", sock)
    summary = latency_probe.run_probe("127.0.0.1", count=3, stop=stop)
    sock.assert_not_called()
    assert summary["attempted"] == 0 and summary["stopped"]


def test_probe_send_failure_and_observer_exception_are_isolated(monkeypatch):
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.sendto.side_effect = OSError("Do not export exception contents")
    monkeypatch.setattr(latency_probe.socket, "socket", lambda *_args: sock)
    records = []

    def observer(record):
        records.append(record)
        raise RuntimeError("Observer failed")

    summary = latency_probe.run_probe("127.0.0.1", count=3, timing_observer=observer)
    assert summary["errors"] == summary["attempted"] == 1
    assert records[0]["error"] == "OSError" and records[0]["rtt_ms"] is None
    assert "Do not export" not in repr(records)
    sock.__exit__.assert_called_once()


@pytest.mark.parametrize("kwargs", [
    {"count": 0}, {"port": 0}, {"period": 0}, {"deadline": float("nan")},
])
def test_probe_invalid_options_never_open_socket(monkeypatch, kwargs):
    sock = MagicMock()
    monkeypatch.setattr(latency_probe.socket, "socket", sock)
    with pytest.raises(ValueError):
        latency_probe.run_probe("127.0.0.1", **kwargs)
    sock.assert_not_called()


def test_probe_cli_jsonl_and_optional_camera_lifecycle(monkeypatch, tmp_path, capsys):
    camera = MagicMock()
    camera.status = "Video live"
    camera.take_frame.return_value = (b"jpeg", 1.0)
    constructor = MagicMock(return_value=camera)
    monkeypatch.setattr(latency_probe, "CameraStream", constructor)

    def run_probe(_host, _port, **kwargs):
        kwargs["timing_observer"]({"kind": "ping"})
        return {"kind": "summary", "timeouts": 0, "errors": 0, "stopped": False}

    monkeypatch.setattr(latency_probe, "run_probe", run_probe)
    output = tmp_path / "probe.jsonl"
    result = latency_probe.main(["--host", "127.0.0.1", "--video", "--output", str(output)])
    assert result == 0
    constructor.assert_called_once_with("http://127.0.0.1:80/cam/stream")
    camera.start.assert_called_once()
    camera.close.assert_called_once()
    camera.join.assert_called_once()
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [record["kind"] for record in records] == ["ping", "summary"]
    assert records[0]["video_status"] == "Video live"
    summary = json.loads(capsys.readouterr().out)
    assert summary["video"]["latest_frames_observed"] == 1
    assert summary["video"]["latest_bytes_observed"] == 4
    assert summary["capture"] == {"written": 2, "dropped": 0, "error": None}