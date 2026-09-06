# Quick Start: Register & Control Servos

The smallest possible program to take control of the bot and move a servo.

---
## 0. Setup

Plug the board with screen in the slot near the battery with the screen facing outside an camera the inside.
Switch on the board.
Once booted, your board will start its own **wifi access point** wich name is shown on screen, and password is **amaker-club**.
Connect to it with your laptop. Control commands are sent directly to the board with UDP on port **24642**.

## 1. Find the token

On screen the bot shows a **5-character token** on the TFT screen (Screen 1 — App Info, row `Master`: `REG: XXXXX`).  
You must send this exact token to claim master control.

---

## 2. The three mandatory steps

```
① REGISTER   — claim master control with the token
② SEND HEARTBEAT  — keep-alive, must repeat every ≤ 50 ms once started
③ SEND COMMANDS
```

> **Heartbeat watchdog**: after the first `HEARTBEAT` frame arrives, the bot checks every tick whether another heartbeat arrived within **50 ms**. If not, it calls the emergency-stop callback (all motors/servos halted). Send heartbeats every **~30 ms** to stay safe.

---

## 3. Binary frames at a glance

All frames start with one **action byte** = `(service_id << 4) | command_id`.

| What | Frame (hex) | Notes |
|---|---|---|
| **Register** | `41 <token>` | token = 5 ASCII bytes, e.g. `41 44 34 41 41 41` for "D4AAA" |
| **Heartbeat** | `43` | no reply sent by the bot |
| **Unregister** | `42` | |
| **Attach servo** (continuous) | `22 <mask> 02` | mask bit *n* = servo channel *n* |
| **Attach servo** (270°) | `22 <mask> 01` | |
| **Set servo speed** | `23 <mask> <speed>` | speed = signed byte −100…+100 |
| **Set servo angle (270°)** | `2A <mask> <hi> <lo>` | angle 0–270, big-endian u16 |
| **Stop all** | `28` | emergency stop, no master check |

**Response** for every command (except heartbeat):
```
[action_byte] [0x00=OK | 0x07=not_master | …]
```

---

## 4. Transport

| Transport | Host | Port | Endpoint |
|---|---|---|---|
| UDP | `<bot-ip>` | **24642** | — |

---

## 5. Minimal Python example — UDP

```python
#!/usr/bin/env python3
"""Minimal K10 Bot controller: register, move servo 0, unregister."""
import socket, time

BOT_IP   = "192.168.1.100"  # ← change
BOT_PORT = 24642
TOKEN    = "D4AAA"          # ← change

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)

def send(data: list[int]):
    sock.sendto(bytes(data), (BOT_IP, BOT_PORT))

def recv() -> list[int]:
    try:
        return list(sock.recvfrom(64)[0])
    except Exception:
        return []

# ① Register
send([0x41] + list(TOKEN.encode()))
resp = recv()
assert resp[1] == 0x00, f"Register failed: {resp}"
print("Registered ✓")

# ② First heartbeat
send([0x43])
last_hb = time.time()

# ③ Attach servo 0 as continuous
send([0x22, 0x01, 0x02])
recv()

# ④ Spin forward 2 s
end = time.time() + 2.0
while time.time() < end:
    send([0x23, 0x01, 100])
    if time.time() - last_hb >= 0.030:
        send([0x43])
        last_hb = time.time()
    time.sleep(0.010)

# ⑤ Stop
send([0x23, 0x01, 0])

# ⑥ Unregister
send([0x42])
recv()
print("Unregistered ✓")

sock.close()
```

---

## 6. Channel mask cheat-sheet

`servo_mask` is a bitmask — set bit *n* to target servo channel *n*.

| Channels to target | mask (hex) |
|---|---|
| Ch 0 only | `0x01` |
| Ch 1 only | `0x02` |
| Ch 0 + 1 | `0x03` |
| Ch 2 only | `0x04` |
| All 6 channels | `0x3F` |

```python
# Helper
def mask(*channels) -> int:
    return sum(1 << ch for ch in channels)

mask(0)      # → 0x01
mask(0, 1)   # → 0x03
mask(2, 3)   # → 0x0C
```

---

*More commands: [binary-protocol](binary-protocol.html) · Full transport details: [communication](communication.html)*
