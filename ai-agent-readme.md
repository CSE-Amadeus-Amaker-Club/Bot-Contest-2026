# AI Agent Guide: K10 Bot UDP Client

This bundle is for an AI agent or developer writing a client for the K10 bot from the files served in `/data/www/help`.

The active control path is the existing binary bot protocol. Do not invent a new authentication header. The expected flow is:

1. Read the 5-character token from the K10 TFT App Info screen.
2. Register master with action `0x41` over UDP or HTTP `/botserver?cmd=<hex>`.
3. Keep heartbeat action `0x43` running after master registration.
4. Send read/write commands through UDP or HTTP using the same binary frames.
5. Stop motion outputs and unregister with action `0x42` when finished.

## Start Here

| Page | Purpose |
|---|---|
| [mandatory-checklist.md](ai-mandatory-checklist.md)[ / html](ai-mandatory-checklist.html) | Steps a client must not skip |
| [quickstart.md](quickstart.md)[ / html](quickstart.html) | Minimal register-and-control flow |
| [wiring.md](ai-wiring.md)[ / html](ai-wiring.html) | Expected board, sensor, servo, and power wiring; uses `wiring.png` as the cable source of truth |
| [capabilities.md](ai-capabilities.md)[ / html](ai-capabilities.html) | Sensors, servos, motors, LEDs, camera, sound, logs, and limits |
| [udp-client.md](ai-udp-client.md)[ / html](ai-udp-client.html) | Client implementation pattern with examples |
| [services.md](ai-services.md)[ / html](ai-services.html) | Available UDP services and command groups |
| [binary-protocol.md](binary-protocol.md)[ / html](binary-protocol.html) | Full command reference |
| [communication.md](communication.md)[ / html](communication.html) | UDP and HTTP transport behavior |

## Implementation Rule

Use the current master registration flow first, then make later HTTP or UDP calls from the same controller context. There is no `X-Bot-Token` API in the current firmware.

## Web Management Surface Available From `/data`

Static pages can call the existing endpoints:

| Area | Existing runtime support |
|---|---|
| WiFi settings | Binary protocol `GET_WIFI`, `SET_WIFI`, `RESET_WIFI` through `/botserver` |
| Bot settings | Binary protocol `GET_NAME`, `SET_NAME` through `/botserver` |
| Bot actions | Raw binary command dispatch through `/botserver?cmd=<hex>` |
| User scripts/actions | `/scripts`, `/scripts/<name>` GET/POST/DELETE |
| Camera | `/cam/snapshot`, `/cam/stream` |
| Sound files | `/sounds` list/upload/delete/play/stop API and `/soundservice.html` |
| Build info | `/api/buildinfo.json`, `/buildinfo.json` |
| Logs | Visible on the TFT log screens; no HTTP log CRUD endpoint exists in `/data` alone |

Because this implementation is restricted to `/data`, new firmware routes cannot be added here. Pages and docs must use the endpoints already exposed by the firmware.
