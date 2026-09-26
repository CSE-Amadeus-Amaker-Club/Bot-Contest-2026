# UDP Client Implementation Pattern

This page gives an AI agent enough structure to write a safe K10 bot client.

## Core Rules

- Use UDP `:24642` for real-time control.
- Use HTTP `/botserver?cmd=<hex>` for browser tools and debugging.
- Register master with `0x41` before master-protected commands.
- Keep heartbeat `0x43` running every 25-30 ms after registration.
- Stop motion outputs before exit.
- Parse standard responses as `[action][resp_code][payload...]` except PING.
- ACK format is `[action][resp_code]` (no full-frame echo).
- Over UDP, non-empty replies append an 8-byte diagnostics trailer:
    `[rx_seq_be32][server_millis_be32]`.

## Python Skeleton

```python
import socket
import struct
import threading
import time

BOT_IP = "192.168.1.100"
BOT_PORT = 24642
TOKEN = "UROCK"

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


def split_udp_reply(resp: bytes):
    """Return (protocol_bytes, rx_seq, server_millis).

    Non-empty UDP replies in current firmware append an 8-byte diagnostics trailer.
    """
    if len(resp) >= 10:
        proto = resp[:-8]
        rx_seq = int.from_bytes(resp[-8:-4], "big")
        server_ms = int.from_bytes(resp[-4:], "big")
        return proto, rx_seq, server_ms
    return resp, None, None


def heartbeat_loop():
    while heartbeat_running:
        sock.sendto(bytes([0x43]), (BOT_IP, BOT_PORT))
        time.sleep(0.030)


def register_master():
    resp = send(bytes([0x41]) + TOKEN.encode("ascii"))
    proto, _, _ = split_udp_reply(resp)
    require_ok(proto, 0x41)


def unregister_master():
    resp = send(bytes([0x42]))
    proto, _, _ = split_udp_reply(resp)
    require_ok(proto, 0x42)


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
    proto, _, _ = split_udp_reply(resp)
    require_ok(proto, 0x22)


def set_servo_angle(mask: int, angle: int):
    payload = struct.pack(">h", angle)
    resp = send(bytes([0x24, mask & 0x3F]) + payload)
    proto, _, _ = split_udp_reply(resp)
    require_ok(proto, 0x24)


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

## HTTP Helper Pattern

```python
import urllib.request

BOT = "http://192.168.1.100"


def http_frame(frame: bytes) -> bytes:
    url = f"{BOT}/botserver?cmd={frame.hex()}"
    with urllib.request.urlopen(url, timeout=1) as resp:
        if resp.status == 204:
            return b""
        return resp.read()

# Register token UROCK
print(http_frame(bytes([0x41]) + b"UROCK").hex())

# Later calls are still protected by registered master IP; no X-Bot-Token header exists.
print(http_frame(bytes([0x45])).decode("latin1", errors="replace"))
```

## Sensor Stream Handling

Streams are asynchronous UDP frames. A robust client separates:

| Loop | Purpose |
|---|---|
| Heartbeat loop | Sends `0x43` every 25-30 ms |
| Command/reply loop | Sends commands and waits for matching replies |
| Stream receive loop | Accepts frames such as LiDAR, geomag, IMU, HuskyLens |

Use action byte to identify frames. For example, LiDAR distance stream uses service `0x08` with command nibble `0x0F`, action `0x8F`.

## HuskyLens controls

HuskyLens commands use service ID `0x07`. Keep them separate from K10 UI and LED
commands:

| Action | Purpose | Payload |
|---|---|---|
| `0x74` | Select HuskyLens algorithm | `[0..5]` |
| `0x76` | HuskyLens RGB/status-light request | `[0|1]`; V1 currently reports unsupported |
| `0x77` | HuskyLens LCD/display request | `[0|1]`; V1 currently reports unsupported |
| `0x78` | Read HuskyLens control support/state | none |

Do not map `0x76` to the K10 NeoPixel service and do not map `0x77` to K10 TFT
screen navigation. They are reserved for HuskyLens-only control state.

## Error Handling

| Response code | Client behavior |
|---|---|
| `0x00` | Continue |
| `0x01` / `0x02` | Fix payload shape or values |
| `0x03` | Operation failed; check hardware readiness |
| `0x04` | Service not started; retry only after checking boot/hardware |
| `0x05` / `0x06` | Wrong service or command byte |
| `0x07` | Register master again from this sender IP |
