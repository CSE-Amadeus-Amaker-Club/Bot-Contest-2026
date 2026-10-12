"""Standalone read-only PING timing; never registers or sends actuator commands."""

from __future__ import annotations

import argparse
import json
import math
import secrets
import socket
import statistics
import struct
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from . import protocol
from .camera import CameraStream
from .timing import JsonlObserver

DEFAULT_PERIOD = 0.04
DEFAULT_DEADLINE = 0.1
DEFAULT_COUNT = 100


def _validate_options(port: int, count: int, period: float, deadline: float) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if type(count) is not int or not 1 <= count <= 2**32:
        raise ValueError("Count must be between 1 and 2**32 (no repeated IDs)")
    if any(not math.isfinite(value) or value <= 0 for value in (period, deadline)):
        raise ValueError("Period and deadline must be finite and positive")


def _ping_once(sock: socket.socket, address: tuple[str, int], request_id: int,
               deadline: float, stop: threading.Event, counts: dict[str, int]) -> dict[str, object]:
    sent_at = time.monotonic()
    acknowledged_at = None
    error_name = None
    diagnostics = None
    try:
        sock.sendto(protocol.ping(request_id), address)
        expires_at = sent_at + deadline
        while not stop.is_set():
            remaining = expires_at - time.monotonic()
            if remaining <= 0:
                error_name = "TimeoutError"
                break
            sock.settimeout(min(remaining, 0.02))
            try:
                frame, sender = sock.recvfrom(2048)
            except TimeoutError:
                continue
            received_at = time.monotonic()
            counts["received"] += 1
            if received_at >= expires_at:
                counts["late"] += 1
                error_name = "TimeoutError"
                break
            if sender != address:
                counts["wrong_sender"] += 1
                continue
            try:
                action, status, payload = protocol.decode_reply(frame)
            except ValueError:
                counts["malformed"] += 1
                continue
            if action != protocol.PING or status is not None:
                counts["wrong_action"] += 1
                continue
            if struct.unpack(">I", payload)[0] != request_id:
                counts["wrong_id"] += 1
                continue
            rx_sequence, server_millis = struct.unpack(">II", frame[-8:])
            diagnostics = {"rx_sequence": rx_sequence, "server_millis": server_millis}
            acknowledged_at = received_at
            break
    except KeyboardInterrupt:
        stop.set()
        error_name = "KeyboardInterrupt"
    except OSError as error:
        error_name = type(error).__name__
    finished_at = time.monotonic()
    if acknowledged_at is None and stop.is_set():
        outcome = "cancelled"
        error_name = error_name or "Cancelled"
    elif error_name == "TimeoutError":
        outcome = "timeout"
    else:
        outcome = "error" if error_name else "ok"
    return {
        "kind": "ping", "action": protocol.PING, "status": None,
        "probe_id": request_id, "sent_monotonic_s": sent_at,
        "ack_monotonic_s": acknowledged_at, "finished_monotonic_s": finished_at,
        "rtt_ms": (None if acknowledged_at is None else (acknowledged_at - sent_at) * 1000),
        "duration_ms": (finished_at - sent_at) * 1000,
        "outcome": outcome, "error": error_name, "diagnostics": diagnostics,
        "rx_counts": counts,
    }


def run_probe(host: str, port: int = 24642, *, count: int = DEFAULT_COUNT,
              period: float = DEFAULT_PERIOD, deadline: float = DEFAULT_DEADLINE,
              stop: threading.Event | None = None,
              timing_observer: Callable[[dict[str, object]], None] | None = None) -> dict[str, object]:
    """Send finite sequential PINGs on a dedicated socket; callbacks must be cheap.

    IDs are unique on this socket. Missed cadence slots are dropped, never replayed.
    Stop/interrupt closes the socket; no heartbeat, registration or cleanup commands
    are sent. Percentiles use nearest rank and only validated, in-deadline replies.
    """
    _validate_options(port, count, period, deadline)
    stop = stop if stop is not None else threading.Event()
    started_at = time.monotonic()
    rtts: list[float] = []
    outcomes = {"ok": 0, "timeout": 0, "cancelled": 0, "error": 0}
    totals = {name: 0 for name in ("received", "wrong_sender", "malformed", "wrong_action", "wrong_id", "late")}
    first_id = secrets.randbits(32)
    attempted = 0
    try:
        if not stop.is_set():
            address = (socket.gethostbyname(host), port)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for sample in range(count):
                    if stop.is_set():
                        break
                    counts = dict.fromkeys(totals, 0)
                    record = _ping_once(sock, address, (first_id + sample) & 0xFFFFFFFF,
                                        deadline, stop, counts)
                    record["sample"] = sample
                    attempted += 1
                    for outcome in outcomes:
                        outcomes[outcome] += int(record["outcome"] == outcome)
                    for name in totals:
                        totals[name] += counts[name]
                    rtt = record["rtt_ms"]
                    if isinstance(rtt, float):
                        rtts.append(rtt)
                    if timing_observer is not None:
                        try:
                            timing_observer(record)
                        except BaseException:
                            pass
                    if record["outcome"] in ("cancelled", "error") or sample + 1 == count:
                        break
                    sent_at = record["sent_monotonic_s"]
                    assert isinstance(sent_at, float)
                    delay = sent_at + period - time.monotonic()
                    stop.wait(delay if delay > 0 else period)
    except KeyboardInterrupt:
        stop.set()
    finished_at = time.monotonic()
    ordered = sorted(rtts)
    return {
        "kind": "summary", "action": protocol.PING,
        "started_monotonic_s": started_at, "finished_monotonic_s": finished_at,
        "requested": count, "attempted": attempted, "replies": outcomes["ok"],
        "timeouts": outcomes["timeout"], "cancelled": outcomes["cancelled"],
        "errors": outcomes["error"], "stopped": stop.is_set(),
        "period_ms": period * 1000, "deadline_ms": deadline * 1000,
        "achieved_hz": attempted / (finished_at - started_at) if attempted else 0.0,
        "median_ms": statistics.median(ordered) if ordered else None,
        "p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
        "p99_ms": ordered[math.ceil(len(ordered) * 0.99) - 1] if ordered else None,
        "max_ms": max(ordered) if ordered else None,
        "percentile_method": "nearest_rank", "rx_counts": totals,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Explicit bot IPv4 address or hostname")
    parser.add_argument("--port", type=int, default=24642)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--period-ms", type=float, default=DEFAULT_PERIOD * 1000)
    parser.add_argument("--deadline-ms", type=float, default=DEFAULT_DEADLINE * 1000)
    parser.add_argument("--output", type=Path, required=True, help="Append-only JSONL capture path")
    parser.add_argument("--video", action="store_true", help="Open one existing /cam/stream consumer")
    parser.add_argument("--http-port", type=int, default=80)
    args = parser.parse_args(argv)
    try:
        _validate_options(args.port, args.count, args.period_ms / 1000, args.deadline_ms / 1000)
        _validate_options(args.http_port, 1, DEFAULT_PERIOD, DEFAULT_DEADLINE)
    except ValueError as error:
        parser.error(str(error))
    camera = CameraStream(f"http://{args.host}:{args.http_port}/cam/stream") if args.video else None
    video_frames = 0
    video_bytes = 0
    try:
        with JsonlObserver(args.output) as observer:
            def observe(record: dict[str, object]) -> None:
                nonlocal video_frames, video_bytes
                if camera is not None:
                    record["video_status"] = camera.status
                    latest = camera.take_frame()
                    if latest is not None:
                        video_frames += 1
                        video_bytes += len(latest[0])
                observer(record)

            if camera is not None:
                camera.start()
            try:
                summary = run_probe(args.host, args.port, count=args.count,
                                    period=args.period_ms / 1000, deadline=args.deadline_ms / 1000,
                                    timing_observer=observe)
                summary["video"] = {
                    "requested": args.video,
                    "status_at_finish": camera.status if camera is not None else None,
                    "latest_frames_observed": video_frames, "latest_bytes_observed": video_bytes,
                }
                observer(summary)
            finally:
                if camera is not None:
                    camera.close()
                    camera.join()
        summary["capture"] = observer.stats()
        print(json.dumps(summary, allow_nan=False))
        if summary["stopped"]:
            return 130
        return int(bool(summary["timeouts"] or summary["errors"] or summary["capture"]["dropped"]))
    except OSError as error:
        parser.exit(2, f"Probe failed: {type(error).__name__}\n")


if __name__ == "__main__":
    raise SystemExit(main())