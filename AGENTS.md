# AGENTS.md — K10 Bot LLM Code Generation Guide

**For AI agents writing K10 bot clients: this is your protocol reference and code generation template.**

This document synthesizes the binary protocol, safety rules, sensor workflows, and testing patterns into a single LLM-optimized reference. Use this to generate fast, correct client code without re-reading the full specification.

---

## Quick Start

1. **What you're building**: A UDP client on port 24642 that controls motors, servos, LEDs, and reads sensors.
2. **Token**: Get a 5-character ASCII token from the bot's TFT display or app.
3. **Core flow**: `REGISTER (0x41)` → `HEARTBEAT (0x43)` loop → commands → `STOP_ALL_MOTORS (0x28)` → `UNREGISTER (0x42)`.
4. **Heartbeat**: **Must** send `0x43` every 25–30 ms after registration; missing heartbeat = loss of control authority.
5. **Master**: Only the registered master IP can write to motion, LEDs, and settings. Read queries usually don't require master.

**For detailed background**: See [ai-agent-readme.md](ai-agent-readme.md) (full entry point), [ai-udp-client.md](ai-udp-client.md) (Python skeleton + patterns), or [communication.md](communication.md) (transport overview).

---

## Master Registration Lifecycle

Every client **must** follow this exact sequence for master-protected operations:

### 1. Register
```
Request:  [0x41] + TOKEN  (TOKEN = 5 ASCII bytes, e.g., "D4AAA")
Response: [0x41] [status]
```
- `status = 0x00` → OK, sender IP is now the registered master
- `status ≠ 0x00` → Registration failed (wrong token, or master already registered from another IP)

**Critical**: Only one IP can be master. If the bot is already registered from another client, this will fail with `0x07` (resp_not_master).

### 2. Keep Heartbeat Running
```
Send every 25–30 ms (e.g., in a separate thread):
  [0x43]
Response: (none — heartbeat gets no reply)
```

- **Must** maintain this loop while master is active
- Failure to send heartbeat for >50 ms will cause loss of master authority
- Heartbeat thread should be daemon/background to avoid blocking main control loop

### 3. Send Master-Protected Commands
Only after registration can you:
- Move motors/servos
- Change LEDs
- Configure sensors
- Modify bot settings (name, WiFi)

### 4. Unregister
```
Request:  [0x42]
Response: [0x42] [status]
```
- `status = 0x00` → OK, sender IP is no longer master
- Always unregister before exit, even on error

### 5. Full Lifecycle Example (25ms heartbeat)
```
Register → Start heartbeat thread every 25ms → Wait 100ms → Send servo command → 
  Keep heartbeat running → Receive reply → Stop motors → Stop heartbeat → Unregister
```

---

## Service Architecture

All commands use this action byte structure:
```
action_byte = (service_id << 4) | cmd_id
```

### 10 UDP Services (Service ID Reference)

| ID | Service | Purpose | Common Commands |
|----|---------|---------|-----------------|
| `0x02` | MotorServo | Motor speed, servo type/angle/speed | `0x20`–`0x2A` |
| `0x03` | DFR1216Board | Expansion board LEDs, battery | `0x30`–`0x33` |
| `0x04` | AmakerBotService | Register, heartbeat, identity | `0x41`–`0x4A` |
| `0x05` | LEDService | Unified K10/DFR1216 LED color control | `0x50`–`0x52` |
| `0x06` | AmakerBotUIService | TFT screen navigation | `0x60`–`0x62` |
| `0x07` | HuskyLensService | AI vision, illumination, algorithm | `0x71`–`0x78` |
| `0x08` | LidarService | Distance/intensity scan, stream, config | `0x80`–`0x8F` |
| `0x09` | GeomagService | Heading, field, calibration, stream | `0x90`–`0x9F` |
| `0x0A` | ImuService | Acceleration, bump events | `0xA0`–`0xAF` |
| `0x0B` | SoundService | Play WAV files, stop, status | `0xB1`–`0xB4` |

### Response Format
```
Standard:  [action] [resp_code] [payload...]
Exception: [0x44] PING has NO resp_code byte (just [0x44][id0][id1][id2][id3])
Exception: [0x43] HEARTBEAT has NO response
Exception: [0x4A] REBOOT has NO response if accepted
```

### Response Codes
| Code | Meaning | Action |
|------|---------|--------|
| `0x00` | OK | Continue |
| `0x01` | Invalid params | Fix payload (missing bytes, shape) |
| `0x02` | Invalid values | Clamp values to range (e.g., angle, speed) |
| `0x03` | Operation failed | Retry after checking hardware (sensor wiring, motor power) |
| `0x04` | Service not started | Retry after boot completes or check hardware |
| `0x05` | Unknown service | Check service ID is 0x02–0x0B |
| `0x06` | Unknown command | Check command nibble is valid for that service |
| `0x07` | Not master | Call `0x41` (REGISTER) again; another IP may hold master |

---

## Safety Guardrails

**These are non-negotiable. Violating any of these can cause motors to spin uncontrollably or sensors to produce invalid data.**

### 1. Always Stop Motors Before Exit
```python
# CRITICAL: Send this before unregistering or disconnecting
sock.sendto(bytes([0x28]), (BOT_IP, BOT_PORT))
```
- Action `0x28` = `STOP_ALL_MOTORS`
- Must be sent even if a command failed or an exception occurred
- Use a `finally` block or exception handler to guarantee this

### 2. Heartbeat Failure = Loss of Control
```python
# If heartbeat is not sent for >50 ms, the bot will:
# - Reject new motion commands (return 0x07 resp_not_master)
# - Assume the client crashed
# - Stay in last-commanded state (but do NOT keep executing)
```
- Heartbeat thread must be **robust**: survive temporary network hiccups
- If heartbeat fails more than N times, exit cleanly and unregister

### 3. Register Master BEFORE Master-Protected Commands
These **require** successful `0x41` registration:
- Motor speed, servo setup, servo angle/speed changes
- LED color/on/off commands
- Sensor stream toggles and config writes
- Bot name, WiFi, reboot commands

Sending these without master will get response `0x07` (resp_not_master). Do NOT retry the command; register master again from the same IP.

### 4. Sensor Calibration Prerequisites
| Sensor | Must calibrate before trusting data |
|--------|--------------------------------------|
| Geomag (BMM350) | Start calib → rotate bot 360° → stop calib → verify `state == calibrated` |
| 270° servos | Set servo type to 270° (cmd `0x22`) before using angle command |
| Continuous servos | Set servo type to continuous (cmd `0x22`) before using speed command `0x23` |
| LiDAR | Verify UART wiring and 5V power before enabling distance stream |
| IMU bump | Configure threshold/debounce (before treating bumps as facts) |

### 5. Value Clamping (Client Responsibility)
Before sending:
- **Motor speed**: clamp to `[-100, 100]`
- **Servo angle**: clamp to range for configured servo type (e.g., 0–180 for 180° mode)
- **Sound volume**: clamp to `[0, 100]`
- **Sound filename**: must end in `.wav`, max 48 bytes

### 6. Response Timeout Handling
```python
sock.settimeout(0.5)  # 500 ms per command
try:
    data, _ = sock.recvfrom(512)
except socket.timeout:
    # Heartbeat lost or network unreachable
    # Exit cleanly: stop motors, unregister
    raise RuntimeError("no response — heartbeat may have failed")
```

---

## Sensor Workflows

### LiDAR Distance Stream

**Prerequisite**: LiDAR UART wiring verified, 5V power confirmed, LiDAR service running.

**Workflow**:
1. Enable distance stream: `[0x8E][0x01]` → expect `[0x8E][0x00]`
2. Receive frames asynchronously: action `0x8F`, payload = distance data (64x8 = 512 uint16 values in big-endian, 2 bytes each = 1024 bytes)
3. Parse frame: read 512 distance values, each 2 bytes big-endian
4. Disable stream: `[0x8E][0x00]` → expect `[0x8E][0x00]`

**Code skeleton**:
```python
# Enable
sock.sendto(bytes([0x8E, 0x01]), (BOT_IP, BOT_PORT))
# Receive loop (separate thread)
while True:
    data, _ = sock.recvfrom(1024)
    if data[0] == 0x8F:
        # Parse 512 uint16 big-endian values
        distances = struct.unpack('>512H', data[1:])
```

### Geomagnetic Heading & Calibration

**Prerequisite**: Geomag service running.

**Workflow**:
1. Check calibration state: `[0x98]` → response includes calibration state byte
2. If not calibrated:
   - Start calibration: `[0x92][0x01]`
   - Physically rotate bot through all axes (roll, pitch, yaw) for ~10 seconds
   - Stop calibration: `[0x92][0x00]`
   - Verify state: `[0x98]` → check byte 2 == calibrated
3. Read heading: `[0x90]` → response `[0x90][0x00][heading_msb][heading_lsb]` (heading in 0.1° units, big-endian)
4. Optional: Enable heading stream: `[0x9E][0x01]` → receive `0x9F` frames asynchronously

**Code skeleton**:
```python
# Get heading (requires calibration first)
resp = sock.sendto(bytes([0x90]), (BOT_IP, BOT_PORT))
if resp[1] == 0x00:  # resp_ok
    heading = struct.unpack('>H', resp[2:4])[0] * 0.1  # degrees
```

### IMU Acceleration & Bump Events

**Prerequisite**: IMU service running.

**Workflow**:
1. Query acceleration: `[0xA0]` → response `[0xA0][0x00][ax_msb][ax_lsb][ay_msb][ay_lsb][az_msb][az_lsb]` (6 bytes payload, big-endian int16)
2. Configure bump threshold (before expecting bump events): `[0xA2][threshold]` where threshold is 0–255 (sensible: ~50–100)
3. Enable bump stream: `[0xAE][0x01]` → receive `0xAF` frames asynchronously (each frame = one bump event)

### HuskyLens V1 Vision

**Prerequisite**: HuskyLens mounted, service running, algorithm selected on device (NOT via UDP).

**Workflow**:
1. Enable illumination LED (on-device only): `[0x71][0x01]` (off: `[0x71][0x00]`)
2. Enable vision stream: `[0x7E][0x01]` → receive `0x7F` frames asynchronously
3. Parse frames: action `0x7F`, payload = vision results (format depends on selected algorithm; consult binary-protocol.md for frame details)

**Important**: Algorithm selection, model training, and screenshot functionality are **device-only**. Do not assume these are UDP-accessible.

---

## Code Patterns & Templates

### Minimal Register/Unregister Pattern (< 20 lines)
```python
import socket

BOT_IP = "192.168.1.100"
BOT_PORT = 24642
TOKEN = "D4AAA"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)

# Register
sock.sendto(bytes([0x41]) + TOKEN.encode("ascii"), (BOT_IP, BOT_PORT))
resp = sock.recvfrom(512)[0]
assert resp[1] == 0x00, f"register failed: {resp.hex()}"

# Unregister
sock.sendto(bytes([0x42]), (BOT_IP, BOT_PORT))
resp = sock.recvfrom(512)[0]
assert resp[1] == 0x00, f"unregister failed: {resp.hex()}"

sock.close()
```

### Heartbeat Loop (Thread-Safe)
```python
import threading
import time

heartbeat_running = False

def heartbeat_loop():
    while heartbeat_running:
        try:
            sock.sendto(bytes([0x43]), (BOT_IP, BOT_PORT))
            time.sleep(0.025)  # 25 ms
        except Exception as e:
            print(f"heartbeat error: {e}")
            break

def start_heartbeat():
    global heartbeat_running
    heartbeat_running = True
    thread = threading.Thread(target=heartbeat_loop, daemon=True)
    thread.start()
    return thread

def stop_heartbeat():
    global heartbeat_running
    heartbeat_running = False
```

### Servo Control (with type setup)
```python
def set_servo_type(servo_mask: int, servo_type: int):
    """servo_type: 0=180deg, 1=270deg, 2=continuous"""
    resp = sock.sendto(bytes([0x22, servo_mask & 0x3F, servo_type & 0xFF]), (BOT_IP, BOT_PORT))
    resp_data = sock.recvfrom(512)[0]
    assert resp_data[1] == 0x00, f"set_servo_type failed: {resp_data.hex()}"

def set_servo_angle(servo_mask: int, angle: int):
    """angle: 0-180 for 180deg servos, 0-270 for 270deg"""
    import struct
    payload = struct.pack(">h", int(angle))
    resp_data = sock.sendto(bytes([0x24, servo_mask & 0x3F]) + payload, (BOT_IP, BOT_PORT))
    resp_data = sock.recvfrom(512)[0]
    assert resp_data[1] == 0x00, f"set_servo_angle failed: {resp_data.hex()}"

# Usage:
set_servo_type(0x01, 0)      # Servo 0 as 180 degree
set_servo_angle(0x01, 90)    # Move to 90 degrees
```

### Motor Speed Control
```python
def set_motor_speed(motor_mask: int, speed: int):
    """motor_mask: bits 0-3 for motors 1-4. speed: -100 to 100"""
    speed = max(-100, min(100, speed))  # clamp
    resp_data = sock.sendto(bytes([0x21, motor_mask & 0x0F, speed & 0xFF]), (BOT_IP, BOT_PORT))
    resp_data = sock.recvfrom(512)[0]
    assert resp_data[1] == 0x00, f"set_motor_speed failed: {resp_data.hex()}"

# Usage:
set_motor_speed(0x0F, 50)    # All motors at 50% forward
set_motor_speed(0x01, -100)  # Motor 1 at full reverse
```

### Stop All Motors (CRITICAL)
```python
def stop_all_motors():
    """MUST be called before unregistering or exiting"""
    sock.sendto(bytes([0x28]), (BOT_IP, BOT_PORT))
```

### LED Color Control
```python
def set_led_color(led_mask: int, r: int, g: int, b: int, brightness: int = 255):
    """
    led_mask: 0x01 (K10 RGB), 0x02 (DFR1216 LED1), 0x04 (DFR1216 LED2)
    r, g, b: 0-255
    brightness: 0-255
    """
    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    brightness = max(0, min(255, brightness))
    resp_data = sock.sendto(bytes([0x51, led_mask & 0x07, r, g, b, brightness]), (BOT_IP, BOT_PORT))
    resp_data = sock.recvfrom(512)[0]
    assert resp_data[1] == 0x00, f"set_led_color failed: {resp_data.hex()}"

# Usage:
set_led_color(0x01, 255, 0, 0)    # K10 red
set_led_color(0x02, 0, 255, 0)    # DFR1216 LED1 green
```

### Full Session Template (with exception handling)
```python
import socket
import struct
import threading
import time

BOT_IP = "192.168.1.100"
BOT_PORT = 24642
TOKEN = "D4AAA"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(0.5)
heartbeat_running = False

def send_command(action: int, payload: bytes = b"") -> bytes:
    """Send command, expect response"""
    sock.sendto(bytes([action]) + payload, (BOT_IP, BOT_PORT))
    return sock.recvfrom(512)[0]

def heartbeat_loop():
    while heartbeat_running:
        sock.sendto(bytes([0x43]), (BOT_IP, BOT_PORT))
        time.sleep(0.025)

try:
    # Register
    resp = send_command(0x41, TOKEN.encode("ascii"))
    assert resp[1] == 0x00, "register failed"
    
    # Start heartbeat
    heartbeat_running = True
    hb_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    hb_thread.start()
    
    # Do work here
    time.sleep(1)
    
finally:
    # Cleanup
    heartbeat_running = False
    sock.sendto(bytes([0x28]), (BOT_IP, BOT_PORT))  # stop all motors
    try:
        send_command(0x42)  # unregister
    except:
        pass
    sock.close()
```

---

## Testing Strategy

### Offline Bot Simulator (No Hardware Required)

The `python_example/bot_simulator/` directory contains a fake bot for testing.

**Workflow**:
1. Change `BOT_IP` to `127.0.0.1` or `localhost`
2. Start bot simulator: `python bot_simulator.py`
3. Run client against simulator
4. Verify register/unregister, heartbeat, motor/servo commands work

**Validation checklist**:
- ✓ Register succeeds and returns `0x00`
- ✓ Heartbeat loop runs without exceptions
- ✓ Motor/servo commands succeed after register
- ✓ Unregister succeeds
- ✓ Stop-all-motors is called on exit

### Unit Test Pattern (pytest)
```python
# tests/test_client.py
import socket
from unittest.mock import Mock, patch

def test_register():
    with patch('socket.socket') as mock_socket:
        mock_sock_instance = Mock()
        mock_socket.return_value = mock_sock_instance
        mock_sock_instance.recvfrom.return_value = (bytes([0x41, 0x00]), ("localhost", 24642))
        
        # Your register code here
        resp = mock_sock_instance.recvfrom()
        assert resp[0][1] == 0x00, "should return resp_ok"
```

### Integration Test Checklist (Live Device)

Before running on a real bot:
1. **Hardware check**: Motors powered, LiDAR UART wired, servos seated
2. **Registration**: Get token from TFT, verify register succeeds
3. **Heartbeat**: Run 1 second, verify no timeouts
4. **Motor test**: Send one `0x21` command (motor speed), verify response `0x00`, listen for motor sound
5. **Servo test**: Set servo type, move servo 0 to 90°, verify movement
6. **Stop**: Send `0x28`, verify all motion stops
7. **Unregister**: Send `0x42`, verify response `0x00`
8. **Exit**: Confirm no exceptions in heartbeat thread

### Validation Sequence (Recommended)
```
1. Offline simulator (register/heartbeat/commands)
   ↓
2. Unit tests (mocked bot responses)
   ↓
3. Live device, single command (register → servo move → unregister)
   ↓
4. Live device, streaming (LiDAR distance stream for 5 seconds)
   ↓
5. Live device, stress test (rapid motor commands + heartbeat)
```

---

## Constraints & Boundaries

### What is NOT exposed over UDP (Hard Limits)

| Feature | Why not UDP | Alternative |
|---------|------------|-------------|
| HuskyLens algorithm selection | Device-only, requires onboard menu | Select algorithm on device before using UDP control |
| HuskyLens model training | Not exposed | Train on device using HuskyLens native interface |
| LiDAR custom calibration | Firmware-only | Use factory defaults or recalibrate on device |
| Motor speed ramp profiles | Not exposed | Send discrete speed steps from client |
| Arbitrary onboard sensor data (AHT20 temp/humidity, LTR303 light, onboard mic) | Not documented over UDP | Read via HTTP endpoints if available; not current |
| WiFi password retrieval | Security policy | Passwords are write-only; cannot be read back |
| Live bot logs via UDP | Not exposed | Logs visible on TFT or via HTTP `/data` endpoint |
| Custom HuskyLens RGB/LCD control | V1 protocol unsupported | RGB/LCD requests report `resp_operation_failed` |

### Capability Hierarchy

```
Hardware capability ≠ Firmware capability ≠ UDP-exposed feature

Example: HuskyLens hardware supports many algorithms
         → Firmware loads some algorithms
         → UDP exposes only streaming + illumination LED + device state queries
         → Algorithm selection is device-only
```

**Always reference the UDP service documentation, not the hardware spec.**

### Response Format Exceptions

| Command | Response Format | Why |
|---------|-----------------|-----|
| `0x44` PING | `[0x44][id0][id1][id2][id3]` (5 bytes, NO resp_code) | Designed for latency measurement; minimizes overhead |
| `0x43` HEARTBEAT | (no response) | Unidirectional keep-alive; UDP is already unreliable |
| `0x4A` REBOOT | (no response) | Bot is restarting; connection will drop |

### Error Recovery

| Error | Client action |
|-------|---------------|
| `resp_not_started (0x04)` on first attempt | Retry after 1 second (service may still be booting) |
| `resp_not_master (0x07)` on motor command | Call `0x41` REGISTER again; another client may have taken master |
| Socket timeout on command | Heartbeat may have failed; exit cleanly (stop motors → unregister) |
| `resp_operation_failed (0x03)` on sensor read | Check hardware: wiring, 5V power, firmware logs on TFT |

---

## Links to Detailed Documentation

For deeper dives into specific topics:

- **[ai-agent-readme.md](ai-agent-readme.md)** — Full onboarding guide for AI agents; entry point with registration flow overview
- **[ai-udp-client.md](ai-udp-client.md)** — Comprehensive Python patterns, HTTP helper, HuskyLens controls, error handling reference
- **[ai-services.md](ai-services.md)** — Service table, command groups, HTTP executor pattern for browser tools
- **[ai-mandatory-checklist.md](ai-mandatory-checklist.md)** — Pre-flight checklist, master-protected actions, calibration procedures, safety defaults
- **[ai-sensors.md](ai-sensors.md)** — Sensor hardware specs vs. UDP-exposed features, LiDAR/Geomag/IMU/HuskyLens detailed capability matrix
- **[ai-capabilities.md](ai-capabilities.md)** — Complete list of exposed features (motion, LEDs, sensors, camera, sound, settings)
- **[ai-wiring.md](ai-wiring.html)** — Hardware wiring rules, DFR1216 board layout, motor/servo configuration
- **[binary-protocol.md](binary-protocol.md)** — Byte-level protocol detail; full frame and response code reference
- **[communication.md](communication.md)** — Transport overview (UDP vs. HTTP), network topology
- **[python_example/AGENTS.md](python_example/AGENTS.md)** — Python client framework guidelines, testing with `tox`, bot simulator usage
- **[quickstart.md](quickstart.md)** — Minimal working flow; good for zero-context onboarding

---

## For AI Agent Code Generation

**How to use this document as an LLM prompt context**:

1. **Copy the Quick Start** (1–2 minute onboarding for any LLM)
2. **Copy the Service Architecture section** (reference table for all commands)
3. **Copy Safety Guardrails** (prevents buggy generated code)
4. **Copy Code Patterns & Templates** (use as skeleton; LLM fills in specifics)
5. **Reference Sensor Workflows** (if LLM is generating sensor code)
6. **Provide the Constraints section** (prevents LLM from assuming unsupported features)

**Example prompt to an LLM**:
```
You are generating a K10 bot UDP client. Follow this protocol:

[Paste Quick Start + Service Architecture + Safety Guardrails + Code Patterns here]

Generate a Python client that:
1. Registers as master with token "D4AAA"
2. Starts a heartbeat loop (25 ms)
3. Reads LiDAR distance stream for 5 seconds
4. Stops motors and unregisters
5. Handles socket timeouts by exiting cleanly

Use the Code Patterns section as your skeleton. Follow all Safety Guardrails exactly.
```

---

**Last updated**: 2026-09-06  
**Protocol version**: Binary protocol as documented in [binary-protocol.md](binary-protocol.md)  
**For questions**: See [ai-agent-readme.md](ai-agent-readme.md) or the detailed topic docs listed above.
