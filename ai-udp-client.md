# UDP Client Implementation Pattern

This page gives an AI agent enough structure to write a safe K10 bot client.

## Core Rules

- Use UDP `:24642` for real-time control.
- Register master with `0x41` before master-protected commands.
- Keep heartbeat `0x43` running every ~30 ms after registration (the bot enforces a 50 ms watchdog timeout).
- Stop motion outputs before exit.
- Parse standard responses as `[action][resp_code][payload...]` except PING.

## Python Skeleton

```python
import socket
import struct
import threading
import time

BOT_IP = "192.168.1.100"
BOT_PORT = 24642
TOKEN = "D4AAA"

RESP_OK = 0x00
RESP_NOT_MASTER = 0x07

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)
heartbeat_running = False


def send(frame: bytes, expect_reply=True, size=512) -> bytes:
    sock.sendto(frame, (BOT_IP, BOT_PORT))
    if not expect_reply:
        return b""
    data, _ = sock.recvfrom(size)
    return data


def require_ok(resp: bytes, action: int):
    if len(resp) < 2 or resp[0] != action or resp[1] != RESP_OK:
        raise RuntimeError(f"action 0x{action:02x} failed: {resp.hex()}")


def heartbeat_loop():
    while heartbeat_running:
        sock.sendto(bytes([0x43]), (BOT_IP, BOT_PORT))
        time.sleep(0.030)


def register_master():
    resp = send(bytes([0x41]) + TOKEN.encode("ascii"))
    require_ok(resp, 0x41)


def unregister_master():
    resp = send(bytes([0x42]))
    require_ok(resp, 0x42)


def start_heartbeat():
    global heartbeat_running
    heartbeat_running = True
    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return thread


def stop_all_motors():
    send(bytes([0x28]), expect_reply=True)


def set_servo_type(mask: int, servo_type: int):
    resp = send(bytes([0x22, mask & 0x3F, servo_type & 0xFF]))
    require_ok(resp, 0x22)


def set_servo_angle(mask: int, angle: int):
    payload = struct.pack(">h", angle)
    resp = send(bytes([0x24, mask & 0x3F]) + payload)
    require_ok(resp, 0x24)


try:
    register_master()
    hb = start_heartbeat()
    set_servo_type(0x01, 0)      # servo 0 as 180 degree positional
    set_servo_angle(0x01, 90)
finally:
    heartbeat_running = False
    stop_all_motors()
    try:
        unregister_master()
    finally:
        sock.close()
```

## Sensor Stream Handling

Streams are asynchronous UDP frames. A robust client separates:

| Loop | Purpose |
|---|---|
| Heartbeat loop | Sends `0x43` every 25-30 ms |
| Command/reply loop | Sends commands and waits for matching replies |
| Stream receive loop | Accepts frames such as LiDAR, geomag, IMU, HuskyLens |

Use action byte to identify frames. For example, LiDAR distance stream uses service `0x08` with command nibble `0x0F`, action `0x8F`.

## Error Handling

On `0x07` (not master), register master again from this sender IP. On `0x01`/`0x02`, fix the payload shape or values before retrying. See [binary-protocol.md](binary-protocol.md#response-codes) for the full response code table.
