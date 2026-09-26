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

| Service | Capability |
|---|---|
| LiDAR | 64x8 distance scan, intensity scan, stats, stream enable/config |
| Geomag | Heading, magnetic field, stream enable/config, hard-iron calibration |
| IMU | Acceleration query/stream and bump events |
| HuskyLens | V1 AI vision state, algorithm selection, learned-ID count, and UDP stream controls |

### HuskyLens V1 control limits

The current client protocol exposes HuskyLens algorithm, stream, and control-state
queries. RGB/status-light and LCD power/backlight requests are not verified V1
features and must not be treated as controls for K10 LEDs or the TFT display.

## Camera

The HTTP server exposes:

| Endpoint | Purpose |
|---|---|
| `/cam/snapshot` | Single JPEG snapshot |
| `/cam/stream` | MJPEG stream |

## Settings

| Setting | Current path |
|---|---|
| Bot name | Binary command `GET_NAME` / `SET_NAME` |
| STA WiFi | Binary command `GET_WIFI` / `SET_WIFI` / `RESET_WIFI` |
| Scripts | HTTP `/scripts` CRUD endpoints |

WiFi changes are saved to NVS by the firmware. Reconnect/reboot behavior depends on the firmware command path currently in use.

## Logs

The firmware has rolling loggers for bot, service, debug, and ESP logs. Current `/data`-only pages cannot expose live log CRUD unless firmware already provides a log HTTP endpoint. Logs are visible through the K10 TFT log screens.

## Limits for AI Agents

- There is no current `/api/v1/logs` endpoint.
- There is no current `X-Bot-Token` header auth.
- `/botserver` returns raw binary, not JSON.
- PING replies do not include a response-code byte.
- HEARTBEAT and REBOOT produce no response body.
