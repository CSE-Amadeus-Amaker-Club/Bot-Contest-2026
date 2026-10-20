# Mandatory Checklist for UDP Clients

## Sound-only Exception

Sound-only commands need no master registration or heartbeat. During playback,
shock detection, LiDAR, HuskyLens, and UI refresh pause; do not rely on shock
protection. Use the [sound tutorial](ai-udp-client.md#sound-convert-store-and-play)
for file handling and playback details.

Use this checklist before driving motors, servos, LEDs, or changing board settings.

## Before Connecting

- Confirm the bot IP address from the TFT display or router/AP client list.
- Read the 5-character token from the TFT App Info screen.
- Confirm expected wiring and power, especially motors, servos, and LiDAR 5V power.
- Use UDP port `24642` for real-time control. See [communication.md](communication.md)
	for the HTTP alternative.

## Session Flow

1. Send `REGISTER` action `0x41` with the token as ASCII bytes.
2. Check response byte 1 is `0x00`.
3. Start sending `HEARTBEAT` action `0x43` every 25-30 ms.
4. Configure servo types before commanding servo motion.
5. Calibrate sensors when needed before relying on their readings.
6. On shutdown or failure, send speed zero individually to every continuous
	servo configured by this client, then send `STOP_ALL_MOTORS` (`0x28`).
7. Send `UNREGISTER` action `0x42` in cleanup. Updated firmware stops DC
	motors and configured continuous servos on heartbeat timeout, but does not
	release master ownership. Older firmware stops DC motors only.

## Master-Protected Actions

These require the sender IP to be registered master:

| Area | Examples |
|---|---|
| Bot settings | `SET_NAME`, `SET_WIFI`, `RESET_WIFI`, `REBOOT` |
| Motors/servos | Set speed, set type, set angle, increment angle |
| LEDs | Set color, turn off selected LEDs |
| Sensor configuration | Stream toggles and configuration writes where implemented |

Read-only queries generally do not require master control, but a client should still use one consistent flow for predictable behavior.

## Calibration and Setup

| Item | Required step |
|---|---|
| Geomag/BMM350 | Start calibration, rotate bot through all axes, stop calibration, verify calibrated state |
| Positional servos | Set the servo type before using `SET_SERVOS_ANGLE` action `0x24`; `0x2A` is not implemented. |
| Continuous servos | Set servo type to continuous before using speed command `0x23` |
| LiDAR | Verify UART wiring and 5V power before enabling streams |
| IMU bump events | Configure threshold/debounce before treating bump events as navigation facts |

## Safety Defaults

- Updated `STOP_ALL_MOTORS` action `0x28` stops DC motors and configured
	continuous servos, preserving positional holding and invalidating earlier
	deferred motion. Older firmware stops DC motors only. Always zero continuous
	servos individually before unregistering; network stops remain best-effort.
- Treat missing heartbeat as a control failure.
- Do not send repeated motion commands without a heartbeat loop.
- Clamp motor speed to `-100..100`.
- Clamp positional servo angles to the configured servo type range.
- Do not return stored WiFi passwords in logs or UI output.
