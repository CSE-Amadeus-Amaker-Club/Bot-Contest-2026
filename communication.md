# Communication Guide

The K10 Bot uses UDP to transport binary control messages. This guide describes the UDP control path, master ownership, heartbeat timing, and diagnostics.

---

## Overview

```
Controller  ──────────────────────────────────┐
  │  UDP :24642         (Core 0, max priority) │
    │                                          │  →  AmakerBotService → service handlers
Controller  ──────────────────────────────────┘
```

| | UDP |
|---|---|
| **Port** | 24642 |
| **Endpoint** | — |
| **Protocol** | Binary |
| **Connection** | Connectionless |
| **Reply** | Same source IP and source port |
| **FreeRTOS core** | 0 (max priority) |
| **Multiple clients** | Yes; master ownership is still single-IP |
| **Best for** | Real-time control and Python scripts |

---

## Sender identity and master control

Master registration is **per-sender-IP**.  
The UDP transport extracts the sender IP and passes it to `AmakerBotService::dispatch()`:

- **UDP** — `packet.remoteIP()` (the source IP of the UDP datagram)

Only one IP can hold master control at a time. A second `REGISTER` from a *different* IP fails with `resp_operation_failed (0x03)` until the current master unregisters or its heartbeat times out.

---

## Transport 1 — UDP

### Characteristics

- **Library**: `AsyncUDP` (ESP-IDF)
- **Core**: 0 at maximum FreeRTOS priority — lowest possible latency
- **Delivery**: fire-and-forget, no connection state
- **Reply**: sent back to the source IP + source port of the incoming datagram
- **Heartbeat**: bot bot-side timeout is **50 ms**; send every ≤ 30 ms to be safe

### Frame exchange

```
Controller                          Bot (Core 0)
    │── [binary frame] ──────────────►│
    │◄─ [response] ───────────────────│  (only if response is non-empty)
```

Heartbeat (`0x43`) sends no response at all — this is intentional to keep latency minimal.

### Python snippet

```python
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)

# Send raw binary
sock.sendto(bytes([0x41, 0x44, 0x34, 0x41, 0x41, 0x41]), ("192.168.1.100", 24642))

# Read response
data, _ = sock.recvfrom(64)
print(hex(data[0]), hex(data[1]))  # action echo, response code
```

### Notes

- No connection handshake — the first packet can be the `REGISTER` frame
- If the router does NAT, the bot replies to the *external* port of the sender; ensure your firewall does not block it
- Multiple controllers can send UDP packets; whichever registers first holds master control

---

## Concurrent use

Multiple UDP clients can send packets to the board, but only one sender IP can own master control at a time.

- A Python UDP controller can register as master and send heartbeats at 30 ms.
- Other clients can send read commands such as `GET_BATTERY`, `GET_NAME`, or `PING` without registering.

Only **master-protected commands** (motor/servo write, WiFi change, reboot) enforce the single-master rule. Read commands (`GET_NAME`, `GET_BATTERY`, `PING`) work from any sender without registration.

---

## Diagnostics

The UDP server exposes live counters accessible from the **App Info** screen (Screen 1) on the TFT display and via `getRxCount()` / `getTxCount()` / `getDroppedCount()` in C++:

| Counter | Meaning |
|---|---|
| `#in` | Frames/requests successfully dispatched |
| `#out` | Responses sent |
| `#drop` | Frames rejected, for example zero-length or malformed packets |

---

*See also: [binary-protocol](binary-protocol.html) · [quickstart](quickstart.html)*
