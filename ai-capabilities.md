# Bot Capabilities

This page summarizes what a client can control or read through the active protocol.

## Motion

| Feature | Capability |
|---|---|
| DC motors | 4 channels, speed `-100..100` |
| Servos | 6 channels, 180 degree, 270 degree, or continuous mode |
| Emergency stop | `STOP_ALL_MOTORS` action `0x28` |
| Battery | Query battery level as `0..100` percent |

## LEDs

| Feature | Capability |
|---|---|
| K10 RGB LEDs | 3 onboard NeoPixels |
| DFR1216 LEDs | 2 expansion WS2812 LEDs through unified LED service |
| Color command | RGB plus brightness |

## Sensors

See [Sensors](ai-sensors.html) for hardware specifications, firmware exposure limits, and manufacturer references.

| Service | Capability |
|---|---|
| LiDAR | 64x8 distance scan, intensity scan, stats, stream enable/config |
| Geomag | Heading, magnetic field, stream enable/config, hard-iron calibration |
| IMU | Acceleration query/stream and bump events |
| HuskyLens | AI vision sensor state/light/stream behavior depending on hardware readiness |

The Unihiker K10 and expansion board include additional sensing and input hardware that is not exposed by the current UDP firmware.

## Settings

| Setting | Current path |
|---|---|
| Bot name | Binary command `GET_NAME` / `SET_NAME` |
| STA WiFi | Binary command `GET_WIFI` / `SET_WIFI` / `RESET_WIFI` |

WiFi changes are saved to NVS by the firmware. Reconnect/reboot behavior depends on the UDP command path currently in use.

## Logs

The firmware has rolling loggers for bot, service, debug, and ESP logs. Logs are visible through the K10 TFT log screens. Use Button A to change screen.

## Limits for AI Agents

- There is no current `/api/v1/logs` endpoint.
- There is no current `X-Bot-Token` header auth.
- PING replies do not include a response-code byte.
- HEARTBEAT and REBOOT produce no response body.
