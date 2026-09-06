# Binary Protocol Reference

Complete command reference for the aMaker bot binary protocol.  
All commands apply to **UDP port 24642**.
See [communication](communication.html) for transport details, [quickstart](quickstart.html) for the minimal flow.

---

## Frame Format

Every message is a raw binary string. Byte 0 is the **action byte**, all following bytes are the command payload.

```
Request:   [action_byte] [payload bytes…]
Response:  [action_byte] [resp_code] [payload bytes…]   ← standard
Response:  [action_byte] [payload bytes…]               ← PING only (no resp_code)
Empty:     (no bytes)                                   ← HEARTBEAT / REBOOT (no reply)
```

### Action byte encoding

```
action_byte = (service_id << 4) | cmd_id
```

| Field      | Bits | Range  |
|------------|------|--------|
| service_id | 7–4  | 0–15   |
| cmd_id     | 3–0  | 0–15   |

**Example:** `0x24` = service 0x02 (Servo), command 0x04 (SET_SERVOS_ANGLE)

---

## Response Codes

Byte 1 of every standard response:

| Code   | Constant              | Meaning                                     |
|--------|-----------------------|---------------------------------------------|
| `0x00` | `resp_ok`             | Command succeeded                           |
| `0x01` | `resp_invalid_params` | Missing, too short, or malformed payload    |
| `0x02` | `resp_invalid_values` | Payload present but value(s) out of range   |
| `0x03` | `resp_operation_failed` | Command understood, hardware/logic failed |
| `0x04` | `resp_not_started`    | Target service is not yet running           |
| `0x05` | `resp_unknown_service`| No handler for this service_id              |
| `0x06` | `resp_unknown_cmd`    | No handler for this cmd_id                  |
| `0x07` | `resp_not_master`     | Sender is not the registered master         |

---

## Service 0x04 — AmakerBotService

Handles session management, identity, and Wi-Fi.  
Most write commands require the sender to be the registered master.

| Action | Name          | Request payload               | Response                                    | Notes                              |
|--------|---------------|-------------------------------|---------------------------------------------|------------------------------------|
| `0x41` | REGISTER      | `[token: ASCII chars]`        | `[0x41][status]`                            | Token is 5 printable ASCII bytes   |
| `0x42` | UNREGISTER    | *(none)*                      | `[0x42][status]`                            | Master only                        |
| `0x43` | HEARTBEAT     | *(none)*                      | *(no reply)*                                | Must be sent every < 50 ms         |
| `0x44` | PING          | `[id: 4 bytes]`               | `[0x44][id: 4 bytes]`                       | ⚠ No resp_code byte in reply       |
| `0x45` | GET_NAME      | *(none)*                      | `[0x45][0x00][name: UTF-8 string]`          |                                    |
| `0x46` | SET_NAME      | `[name: UTF-8 string]`        | `[0x46][status]`                            | Master only; max 32 chars          |
| `0x47` | GET_WIFI      | *(none)*                      | `[0x47][0x00][ssid_len][ssid…][pass_len][pass…]` |                             |
| `0x48` | SET_WIFI      | `[ssid_len][ssid…][pass_len][pass…]` | `[0x48][status]`                   | Master only                        |
| `0x49` | RESET_WIFI    | *(none)*                      | `[0x49][status]`                            | Master only; clears stored SSID    |
| `0x4A` | REBOOT        | *(none)*                      | *(no reply)*                                | Master only; `ESP.restart()`       |

> **PING quirk:** The reply frame is `[0x44][id0][id1][id2][id3]` — exactly 5 bytes.  
> There is **no** resp_code byte. Use this to measure round-trip latency.

> **HEARTBEAT / REBOOT** return an empty string internally — the transports send nothing back.

---

## Service 0x02 — Servo

 Connected on the servo pins S0..S6 on the expansion board.

### Channel encoding

**Servos** — 0-indexed throughout:

| Bits | Channels |
|------|----------|
| 0–5  | Servo 0–5 |

`SERVO_MASK_ALL = 0x3F`

### Servo types

| Value | Type         | Valid angle commands     |
|-------|--------------|--------------------------|
| `0`   | 180° servo   | SET_SERVOS_ANGLE, INCREMENT |
| `1`   | 270° servo   | SET_SERVOS_ANGLE, INCREMENT, SET_SERVO270_ANGLE |
| `2`   | Continuous   | SET_SERVOS_SPEED only    |

Mixing angle and speed commands on the wrong servo type returns `resp_invalid_params`.

### Commands

| Action | Name                   | Request payload                             | Response                                                        | Notes                                         |
|--------|------------------------|---------------------------------------------|-----------------------------------------------------------------|-----------------------------------------------|
| `0x22` | SET_SERVO_TYPE         | `[servo_mask][type: u8]`                    | `[0x22][status]`                                               | type > 2 → `resp_invalid_values`              |
| `0x23` | SET_SERVOS_SPEED       | `[servo_mask][speed: i8]`                   | `[0x23][status]`                                               | Continuous servos only; −100 to +100          |
| `0x24` | SET_SERVOS_ANGLE       | `[servo_mask][angle_hi][angle_lo]`          | `[0x24][status]`                                               | Big-endian signed i16; −360 to +360           |
| `0x25` | INCREMENT_SERVOS_ANGLE | `[servo_mask][delta_hi][delta_lo]`          | `[0x25][status]`                                               | Big-endian signed i16 delta; clamped to type range |
| `0x27` | GET_SERVOS_ANGLE       | `[servo_mask]`                              | `[0x27][0x00][servo_mask][ang₀_hi][ang₀_lo][ang₁_hi]…`        | Big-endian i16 per set bit, LSB-first         |
| `0x28` | STOP_ALL_MOTORS        | *(none)*                                    | `[0x28][status]`                                               | No master check; emergency stop               |
| `0x29` | GET_BATTERY            | *(none)*                                    | `[0x29][0x00][level: u8]`                                      | 0–100 %                                       |
| `0x2A` | SET_SERVO270_ANGLE     | `[servo_mask][angle_hi][angle_lo]`          | `[0x2A][status]`                                               | Calibrated PWM; unsigned 0–270 (u16), clamped |

### Angle byte encoding

```python
# Signed i16 → two bytes, big-endian
angle = -45
hi = (angle >> 8) & 0xFF
lo = angle & 0xFF
frame = bytes([0x24, servo_mask, hi, lo])

# Decode response angle
angle = struct.unpack('>h', bytes([ang_hi, ang_lo]))[0]
```

### GET response value ordering

`GET_MOTORS_SPEED` and `GET_SERVOS_ANGLE` echo the mask as byte[2], then return one value per **set bit in LSB-first order** (bit 0 first, then bit 1, etc.):

```python
# Example: motor_mask=0x05 (bits 0 and 2 set) → returns [speed_motor1, speed_motor3]
mask = 0x05
speeds = []
for bit in range(4):
    if mask & (1 << bit):
        speeds.append(response_payload[idx]); idx += 1
```

---

## Service 0x03 — Expansion board

Battery monitoring.

| Action | Name          | Request payload                            | Response                                               | Notes                               |
|--------|---------------|--------------------------------------------|--------------------------------------------------------|-------------------------------------|
`                            | See format below                    |
| `0x35` | GET_BATTERY   | *(none)*                                   | `[0x35][0x00][level: u8]`                              | 0–100 %                             |
---

## Service 0x06 — AmakerBotUIService (remote screen control)

Controls which TFT screen is shown on the K10 display.

| Action | Name        | Request payload   | Response             | Notes                              |
|--------|-------------|-------------------|----------------------|------------------------------------|
| `0x61` | NEXT_SCREEN | *(none)*          | `[0x61][status]`     | Wraps around (6 screens)           |
| `0x62` | PREV_SCREEN | *(none)*          | `[0x62][status]`     | Wraps around                       |
| `0x63` | SET_SCREEN  | `[index: u8]`     | `[0x63][status]`     | 0–5; index > 5 → `resp_invalid_values` |

---

## Master protection summary

| Requires master | Open to all senders    |
|-----------------|------------------------|
| UNREGISTER      | REGISTER               |
| SET_NAME        | HEARTBEAT              |
| SET_WIFI        | PING                   |
| RESET_WIFI      | GET_NAME               |
| REBOOT          | GET_WIFI               |
| SET_MOTORS_SPEED| STOP_ALL_MOTORS        |
| SET_SERVO_TYPE  | GET_MOTORS_SPEED       |
| SET_SERVOS_SPEED| GET_SERVOS_ANGLE       |
| SET_SERVOS_ANGLE| GET_BATTERY (any svc)  |
| INCREMENT_SERVOS_ANGLE |                 |
| SET_SERVO270_ANGLE |                     |
| SET_COLOR (LED) |                        |
| TURN_OFF (LED)  |                        |

---

## Quick Python snippet

```python
import socket

HOST = "192.168.x.x"
UDP_PORT = 24642

def send_udp(frame: bytes) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1.0)
        s.sendto(frame, (HOST, UDP_PORT))
        try:
            data, _ = s.recvfrom(256)
            return data
        except socket.timeout:
            return b""

# Set motor 1 to 50% forward  (motor_mask=0x01, speed=50)
resp = send_udp(bytes([0x21, 0x01, 50]))
print(f"action={resp[0]:#04x}  code={resp[1]:#04x}")

# Set servo 0 to 90°  (servo_mask=0x01, angle=90 → 0x00 0x5A)
resp = send_udp(bytes([0x24, 0x01, 0x00, 0x5A]))

# Turn all K10 NeoPixels blue at half brightness
resp = send_udp(bytes([0x51, 0x07, 0, 0, 255, 128]))

# Emergency stop
resp = send_udp(bytes([0x28]))
```

---

*See also: [quickstart](quickstart.html) · [communication](communication.html)*
