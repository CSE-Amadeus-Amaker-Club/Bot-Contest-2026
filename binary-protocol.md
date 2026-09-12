# Binary Protocol Reference

Complete command reference for the K10 bot binary protocol.  
All commands apply to **UDP port 24642** and **HTTP `/botserver`**.  
See [communication.md](communication.md) for transport details, [quickstart.md](quickstart.md) for the minimal flow.

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

**Example:** `0x24` = service 0x02 (MotorServo), command 0x04 (SET_SERVOS_ANGLE)

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

### Service and hardware availability

Use `resp_not_started` when the target service or one of its required dependencies
has not started. Use `resp_operation_failed` when the service is running but a
hardware transaction, sensor read, or persistence operation fails. Sensor query
responses retain their normal payload shape when returning `resp_operation_failed`;
the payload must be treated as invalid until a later response returns `resp_ok`.

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

## Service 0x02 — MotorServoService

Controls 4 DC motors and 6 servo channels on the DFR1216 expansion board.

### Channel encoding

**Motors** — 1-indexed hardware, 0-indexed in the mask:

| Bit | Motor |
|-----|-------|
| 0   | Motor 1 |
| 1   | Motor 2 |
| 2   | Motor 3 |
| 3   | Motor 4 |

`MOTOR_MASK_ALL = 0x0F`

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
| `0x21` | SET_MOTORS_SPEED       | `[motor_mask][speed: i8]`                   | `[0x21][status]`                                               | Speed: −100 to +100. Positive = forward       |
| `0x22` | SET_SERVO_TYPE         | `[servo_mask][type: u8]`                    | `[0x22][status]`                                               | type > 2 → `resp_invalid_values`              |
| `0x23` | SET_SERVOS_SPEED       | `[servo_mask][speed: i8]`                   | `[0x23][status]`                                               | Continuous servos only; −100 to +100          |
| `0x24` | SET_SERVOS_ANGLE       | `[servo_mask][angle_hi][angle_lo]`          | `[0x24][status]`                                               | Big-endian signed i16; −360 to +360           |
| `0x25` | INCREMENT_SERVOS_ANGLE | `[servo_mask][delta_hi][delta_lo]`          | `[0x25][status]`                                               | Big-endian signed i16 delta; clamped to type range |
| `0x26` | GET_MOTORS_SPEED       | `[motor_mask]`                              | `[0x26][0x00][motor_mask][speed₀][speed₁…: i8]`               | One i8 per set bit, LSB-first                 |
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

## Service 0x03 — DFR1216Board

Controls the onboard LEDs and battery monitoring on the DFR1216 expansion board.

> **Index vs. mask:** This service uses a **`led_index` integer (0–2)**, not a bitmask.  
> Compare with LEDService (0x05) which uses a bitmask.

| Action | Name          | Request payload                            | Response                                               | Notes                               |
|--------|---------------|--------------------------------------------|--------------------------------------------------------|-------------------------------------|
| `0x31` | SET_LED_COLOR | `[led_index: u8][r][g][b][brightness]`     | `[0x31][status]`                                       | led_index > 2 → `resp_invalid_values` |
| `0x32` | TURN_OFF_LED  | `[led_index: u8]`                          | `[0x32][status]`                                       | led_index > 2 → `resp_invalid_values` |
| `0x33` | TURN_OFF_ALL  | *(none)*                                   | `[0x33][status]`                                       |                                     |
| `0x34` | GET_LED_STATUS | *(none)*                                  | `[0x34][0x00][JSON string]`                            | See format below                    |
| `0x35` | GET_BATTERY   | *(none)*                                   | `[0x35][0x00][level: u8]`                              | 0–100 %                             |

### GET_LED_STATUS JSON format

```json
{
  "leds": [
    { "id": 0, "red": 255, "green": 0, "blue": 128 },
    { "id": 1, "red": 0,   "green": 0, "blue": 0   },
    { "id": 2, "red": 0,   "green": 64,"blue": 0   }
  ]
}
```

The JSON payload starts at byte[2] (after action + resp_ok). Parse as UTF-8.

---

## Service 0x05 — LEDService

Controls the 3 K10 NeoPixels and 2 DFR1216 WS2812 LEDs through a unified **bitmask**.

### LED mask layout

| Bit | LED                        |
|-----|----------------------------|
| 0   | K10 NeoPixel 0             |
| 1   | K10 NeoPixel 1             |
| 2   | K10 NeoPixel 2             |
| 3   | DFR1216 WS2812 LED 0       |
| 4   | DFR1216 WS2812 LED 1       |

Convenience constants: `MASK_ALL_K10 = 0x07`, `MASK_ALL_DFR = 0x18`, `MASK_ALL = 0x1F`

### Commands

| Action | Name          | Request payload                                    | Response                                                      | Notes                      |
|--------|---------------|----------------------------------------------------|---------------------------------------------------------------|----------------------------|
| `0x51` | SET_COLOR     | `[led_mask][r: u8][g: u8][b: u8][brightness: u8]` | `[0x51][status]`                                             | Frame length must be ≥ 6   |
| `0x52` | TURN_OFF      | `[led_mask]`                                       | `[0x52][status]`                                             |                            |
| `0x53` | TURN_OFF_ALL  | *(none)*                                           | `[0x53][status]`                                             |                            |
| `0x54` | GET_COLOR     | `[led_mask]`                                       | `[0x54][0x00][led_mask][r₀][g₀][b₀][br₀][r₁][g₁][b₁][br₁]…`| 4 bytes per set bit, LSB-first |

### GET_COLOR response parsing

```python
# Example: led_mask=0x05 (bits 0 and 2) → 2 × 4 bytes after [action][ok][mask]
mask = 0x05
leds = []
offset = 3  # skip action, resp_ok, mask
for bit in range(5):
    if mask & (1 << bit):
        r, g, b, br = resp[offset:offset+4]
        leds.append({'bit': bit, 'r': r, 'g': g, 'b': b, 'brightness': br})
        offset += 4
```

---

## Service 0x06 — AmakerBotUIService (remote screen control)

Controls which TFT screen is shown on the K10 display.

| Action | Name        | Request payload   | Response             | Notes                              |
|--------|-------------|-------------------|----------------------|------------------------------------|
| `0x61` | NEXT_SCREEN | *(none)*          | `[0x61][status]`     | Wraps around (7 screens)           |
| `0x62` | PREV_SCREEN | *(none)*          | `[0x62][status]`     | Wraps around                       |
| `0x63` | SET_SCREEN  | `[index: u8]`     | `[0x63][status]`     | 0–6; index > 6 → `resp_invalid_values` |

Screen indices:

`0=splash`, `1=app-info`, `2=huskylens`, `3=app-log`, `4=svc-log`, `5=debug-log`, `6=esp-log`.

---

## Service 0x07 — HuskylensService

Commands for the HuskyLens V1/SEN0305 service. The firmware talks to the device
over I2C only; host clients talk to the K10 over UDP only. `SET_ILLUMINATION`
controls the HuskyLens illumination LED, not the K10 RGB LEDs and not the HuskyLens
LCD/backlight. The firmware first tries the MakeCode V1 sensor command `0x31`,
then falls back to the Arduino enum-derived `0x3D`, and caches the command that
returns `COMMAND_RETURN_OK`.

RGB/status-light and LCD/display requests are intentionally scoped to the HuskyLens
service so they cannot affect the K10 LED or screen services. For verified public
V1 protocol support, no RGB/status-light or LCD power/backlight command is known;
these requests currently return `resp_operation_failed`.

| Action | Name      | Request payload      | Response         | Notes |
|--------|-----------|----------------------|------------------|-------|
| `0x71` | SET_ILLUMINATION (SET_LIGHT) | `[state: u8]` | `[0x71][status]` | `0=off`, `1=on`; illumination LED only. Firmware tries V1 sensor command `0x31`, then falls back to `0x3D`. |
| `0x72` | SET_STREAM | `[enabled: u8][hz: u8]` | `[0x72][status]` | `enabled=0/1`; `hz=0` keeps current interval, otherwise `1..20`. |
| `0x73` | GET_STREAM | *(none)* | `[0x73][status][enabled][hz]` | Returns current HuskyLens UDP stream state. |
| `0x74` | SET_ALGORITHM | `[algorithm: u8]` | `[0x74][status]` | Algorithms: `0=face`, `1=object tracking`, `2=object recognition`, `3=line`, `4=color`, `5=tag`. |
| `0x75` | GET_ALGORITHM | *(none)* | `[0x75][status][algorithm][learned_id_count:u16le]` | Returns last acknowledged algorithm and learned-ID count from the latest info frame. |
| `0x76` | SET_RGB_LIGHT | `[state: u8]` | `[0x76][status]` | HuskyLens RGB/status light only; V1 public protocol has no verified command, so returns `resp_operation_failed`. |
| `0x77` | SET_DISPLAY | `[state: u8]` | `[0x77][status]` | HuskyLens LCD/display only; V1 public protocol has no verified power/backlight command, so returns `resp_operation_failed`. |
| `0x78` | GET_CONTROLS | *(none)* | `[0x78][status][illumination][illumination_supported][rgb][rgb_supported][display][display_supported][sensor_cmd]` | State/support readback for HuskyLens-only controls. |

`GET_CONTROLS.sensor_cmd` is `0` until illumination has succeeded at least once,
then the selected V1 sensor command byte is returned (`0x31` or `0x3D`).

---

## Sensor services

Sensor request actions use the service ID in the high nibble. The low nibble
is local to each service, so the same command number may be reused by different
services without creating a collision. Asynchronous actions are reserved for
stream and event frames and are not request commands.

### Service 0x08 — LidarService

| Action | Name | Request payload | Response / event |
|--------|------|-----------------|------------------|
| `0x81` | QUERY_SCAN | *(optional subset)* | `[action][status][frame_id:u16le][point_count:u16le][distances:u16le...]` |
| `0x82` | QUERY_STATS | *(none)* | Statistics response |
| `0x83` | SET_STREAM | `[enabled:u8][rate_hz:u8][subset:u8]` | `[0x83][status]` |
| `0x84` | GET_STREAM | *(none)* | Stream state and rate |
| `0x85` | SET_CONFIG | Configuration payload | `[0x85][status]` |
| `0x86` | GET_CONFIG | *(none)* | Configuration response |
| `0x87` | RESET_CONFIG | *(none)* | `[0x87][status]` |
| `0x88` | QUERY_INTENSITY | *(optional subset)* | Intensity response |
| `0x89` | SET_STREAM_INTENSITY | `[enabled:u8][rate_hz:u8][subset:u8]` | `[0x89][status]` |
| `0x8A` | GET_STREAM_INTENSITY | *(none)* | Stream state and rate |
| `0x8E` | INTENSITY_STREAM | *(event)* | Asynchronous intensity frame |
| `0x8F` | DISTANCE_STREAM | *(event)* | Asynchronous distance frame |

### Service 0x09 — GeomagService

| Action | Name | Request payload | Response |
|--------|------|-----------------|----------|
| `0x91` | QUERY_HEADING | *(none)* | Heading response |
| `0x92` | QUERY_FIELD | *(none)* | Magnetic-field response |
| `0x93` | SET_STREAM | `[enabled:u8][rate_hz:u16be]` | `[0x93][status]` |
| `0x94` | GET_STREAM | *(none)* | Stream state and rate |
| `0x95` | SET_CONFIG | Configuration payload | `[0x95][status]` |
| `0x96` | GET_CONFIG | *(none)* | Configuration response |
| `0x97` | CALIBRATE | Calibration payload | `[0x97][status]` |
| `0x9F` | STREAM | *(event)* | Asynchronous heading/field frame |

### Service 0x0A — ImuService

| Action | Name | Request payload | Response |
|--------|------|-----------------|----------|
| `0xA1` | QUERY_ACCEL | *(none)* | `[action][status][x:i16le][y:i16le][z:i16le]` (8 bytes) |
| `0xA2` | SET_STREAM | `[enabled:u8][rate_hz:u16be]` | `[0xA2][status]`; rate `1..400` even when disabled |
| `0xA3` | GET_STREAM | *(none)* | `[action][status][enabled:u8][rate_hz:u16le]` |
| `0xA4` | SET_CONFIG | `[range:u8][rate_hz:u16be][power:u8][hpf:u8]` | `[0xA4][status]` |
| `0xA5` | GET_CONFIG | *(none)* | `[action][status][range:u8][rate_hz:u16le][power:u8][hpf:u8]` |
| `0xA6` | RESET_CONFIG | *(none)* | `[0xA6][status]` |
| `0xA7` | SET_BUMP_CONFIG | `[threshold_mg:u16be][debounce_ms:u16be]` | `[0xA7][status]` |
| `0xA8` | GET_BUMP_CONFIG | *(none)* | `[action][status][threshold_mg:u16le][debounce_ms:u16le]` |
| `0xAF` | STREAM | *(event)* | `[0xAF][status][sample_id:u32le][x:i16le][y:i16le][z:i16le]` (12 bytes) |
| `0xA0` | BUMP_EVENT | *(event)* | `[0xA0][status][sample_id:u32le][direction:u8][x:i16le][y:i16le][z:i16le]` (13 bytes) |

The IMU uses a `DFRobot_LIS2DW12_I2C` sensor and is updated on Core 1. Its
commands and asynchronous frames are delivered through the shared UDP
transport on port `24642`; it has no dedicated HTTP endpoint.

---

## Service 0x0B — SoundService

Controls WAV playback from the `/sounds` directory on the 6 MiB LittleFS
`voice_data` partition. File upload, listing, and deletion use the HTTP API;
UDP carries only bounded playback commands and filenames.

| Action | Name | Request payload | Response | Notes |
|---|---|---|---|---|
| `0xB1` | PLAY | `[filename: ASCII bytes]` | `[0xB1][status]` | 1-48 bytes; the UDP acknowledgement confirms queueing only |
| `0xB2` | STOP | *(none)* | `[0xB2][status]` | Stops current playback and clears a queued replacement |
| `0xB3` | STATUS | *(none)* | `[0xB3][status][playing: u8]` | `playing` is `0` or `1` |
| `0xB4` | VOLUME | `[percent: u8]` | `[0xB4][status]` | `percent` must be `0` through `100` |

`PLAY` is deferred from the Core 0 UDP callback to Core 1. A successful UDP
acknowledgement does not prove that the named file exists or that playback
started. The HTTP play route validates file existence before returning success.

### WAV and storage limits

- Structurally valid RIFF/WAVE with PCM format and a bounded `data` chunk;
    metadata chunks may precede the audio data.
- Mono or stereo, unsigned 8-bit or signed 16-bit samples, 8-48 kHz sample rate.
- Lowercase `.wav` extension; filename length is at most 48 characters.
- Maximum file size is 300 KiB.
- Uploads must leave at least 128 KiB free in the shared partition.
- Upload and delete operations are rejected while a playback task is active.

### Playback execution

Playback runs on Core 1 at priority 6 with an 8 KiB task stack and streams in
4 KiB blocks. It takes the shared I2S mutex with a 250 ms timeout and handles
partial I2S writes before reading the next block. Core 0 remains reserved for
UDP transport.

### HTTP sound API

| Method and path | Behavior |
|---|---|
| `GET /sounds` | Returns storage totals, playback state, and stored filenames as JSON |
| `POST /sounds/<name>` | Streams a raw WAV request body into LittleFS |
| `DELETE /sounds/<name>` | Deletes a stored WAV when playback is idle |
| `POST /sounds/<name>/play` | Starts playback or replaces the current sound |
| `POST /sounds/stop` | Stops playback and clears a queued replacement |
| `POST /sounds/volume?value=<0-100>` | Sets speaker volume, including during active playback |

Command nibble `0x00` is reserved. An action is unique by its complete byte,
not by the low command nibble alone.

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
| INCREMENT_SERVOS_ANGLE | GET_LED_STATUS  |
| SET_SERVO270_ANGLE | SET_LED_COLOR (DFR) |
| SET_COLOR (LED) | TURN_OFF_ALL           |
| TURN_OFF (LED)  | SET_LIGHT (HuskyLens)  |
|                  | PLAY/STOP/STATUS (SoundService) |

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

*See also: [quickstart.md](quickstart.md) · [communication.md](communication.md) · [architecture.md](architecture.md)*
