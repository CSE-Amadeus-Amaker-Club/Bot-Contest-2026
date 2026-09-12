# Communication Guide

The K10 Bot currently exposes two active transports that both map to the same bot command set.

---

## Overview

```
Controller  ──────────────────────────────────┐
  │  UDP :24642         (Core 0, max priority) │  →  AmakerBotService → service handlers
  │  HTTP :80/botserver (Core 1, normal prio)  │
Controller  ──────────────────────────────────┘
```

| | UDP | HTTP |
|---|---|---|
| **Port** | 24642 | 80 |
| **Endpoint** | — | `/botserver?cmd=<hex>` |
| **Protocol** | Binary | Hex-encoded GET |
| **Connection** | Connectionless | One request per frame |
| **Reply** | Same source port | HTTP response body |
| **FreeRTOS core** | 0 (max priority) | 1 (normal priority) |
| **Multiple clients** | Yes (last sender wins) | Yes |
| **Best for** | Real-time control, Python scripts | Browser pages, curl/debugging |

---

## Sender identity and master control

Master registration is **per-sender-IP**.
Each transport extracts sender IP and passes it to `AmakerBotService::dispatch()`:

- **UDP** — `packet.remoteIP()` (source IP of the datagram)
- **HTTP** — HTTP client remote IP

Only one IP can hold master control at a time. A second `REGISTER` from a different IP fails with `resp_operation_failed (0x03)` until current master unregisters or heartbeat times out.

---

## Transport 1 — UDP

### Characteristics

- **Library**: `AsyncUDP`
- **Core**: 0 at maximum FreeRTOS priority
- **Delivery**: fire-and-forget, no connection state
- **Reply**: sent back to source IP + source port
- **Heartbeat**: watchdog timeout is **50 ms**; send every <= 30 ms to stay safe

### Frame exchange

```
Controller                          Bot (Core 0)
    │── [binary frame] ──────────────►│
    │◄─ [response] ───────────────────│  (only if response is non-empty)
```

Heartbeat (`0x43`) intentionally has no response payload.

### Python snippet

```python
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)

# REGISTER token "UROCK" -> [0x41, 'D', '4', 'A', 'A', 'A']
sock.sendto(bytes([0x41, 0x44, 0x34, 0x41, 0x41, 0x41]), ("192.168.1.100", 24642))
data, _ = sock.recvfrom(64)
print(hex(data[0]), hex(data[1]))
```

---

## Transport 2 — HTTP (`/botserver`)

### Characteristics

- **Library**: `ESPAsyncWebServer`
- **Core**: 1 at normal priority
- **Method**: `GET /botserver?cmd=<hex>`
- **Frame encoding**: bytes encoded as contiguous hex string (no separators)
- **Response encoding**: raw binary (`application/octet-stream`)

### HTTP status codes

| Situation | HTTP status | Body |
|---|---|---|
| Frame dispatched, non-empty response | **200** | Raw binary response |
| Frame dispatched, empty response (heartbeat/reboot) | **204** | Empty |
| Missing `cmd` parameter | **400** | Plain text error message |
| Invalid `cmd` hex string | **400** | Plain text error message |

### Static file serving

The same HTTP server also serves static pages from `/www` on LittleFS:

| Path | Source |
|---|---|
| `http://<bot-ip>/` | `/www/index.html` |
| `http://<bot-ip>/control.html` | `/www/control.html` |
| `http://<bot-ip>/camera.html` | `/www/camera.html` |
| `http://<bot-ip>/buildinfo.html` | `/www/buildinfo.html` |
| `http://<bot-ip>/soundservice.html` | `/www/soundservice.html` |
| `http://<bot-ip>/cam/snapshot` | Live JPEG from camera |
| `http://<bot-ip>/cam/stream` | MJPEG stream |
| `http://<bot-ip>/scripts` | Script CRUD API |
| `http://<bot-ip>/sounds` | Sound storage and playback API |

### Sound HTTP routes

The sound routes are direct HTTP operations, not hex-encoded `/botserver`
commands:

| Method and path | Success | Failure | Body |
|---|---|---|---|
| `GET /sounds` | `200` | - | JSON storage/playback summary |
| `POST /sounds/<name>` | `200` | `400` | Raw WAV upload; response is plain text |
| `DELETE /sounds/<name>` | `200` | `404` | Delete while playback is idle |
| `POST /sounds/<name>/play` | `200` | `404` | Start or replace playback |
| `POST /sounds/stop` | `200` | - | Stop playback |

The upload body must be the WAV bytes, with a known content length. Upload and
delete fail while playback is active. See the
[SoundService guide](../../../docs/user%20guides/SoundService.md) for limits and examples.

### curl examples

```bash
# REGISTER with token "UROCK" -> hex: 41 44 34 41 41 41
curl -s "http://192.168.1.100/botserver?cmd=414434414141" | xxd

# HEARTBEAT -> no body, HTTP 204
curl -s -o /dev/null -w "%{http_code}" "http://192.168.1.100/botserver?cmd=43"

# SET_SERVOS_SPEED servo 0, speed +100 -> hex: 23 01 64
curl -s "http://192.168.1.100/botserver?cmd=230164" | xxd

# GET_BATTERY -> hex: 29
curl -s "http://192.168.1.100/botserver?cmd=29" | xxd
```

---

## Concurrent use

UDP and HTTP can run simultaneously:

- A UDP controller can register and drive motors/servos at low latency.
- Browser/curl HTTP requests can read status commands.
- Master-protected commands still enforce single-master ownership by sender IP.
- Static browser pages must register master through `0x41` first, then send later `/botserver` calls from the same client IP. The current firmware does not implement an `X-Bot-Token` header.

---

## Diagnostics

App Info screen counters expose transport activity:

| Counter | Meaning |
|---|---|
| `#in` | Frames/requests successfully dispatched |
| `#out` | Responses sent |
| `#drop` | Frames rejected (bad hex, malformed payload, etc.) |

---

*See also: [binary-protocol.md](binary-protocol.md) · [quickstart.md](quickstart.md) · [architecture.md](architecture.md) · [ai-agent-readme.md](ai-agent-readme.md)*
