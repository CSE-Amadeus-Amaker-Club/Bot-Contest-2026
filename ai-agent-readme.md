# AI Agent Guide: K10 Bot UDP Client

For sound-only clients, start with [Sound: Convert, Store, and Play](ai-udp-client.md#sound-convert-store-and-play):
SoX unsigned 8-bit mono 11025 Hz conversion, curl list/upload/delete, and
Python HTTP/UDP playback. Sound control requires no master registration;
motion control still needs the registration and heartbeat lifecycle below.

This bundle is for an AI agent or developer writing a client for the K10 bot from the files served in `/data/www/help`.

The active control path is the existing binary bot protocol. Do not invent a new authentication header. The expected flow is:

1. Read the 5-character token from the K10 TFT App Info screen.
2. Register master with action `0x41` over UDP or HTTP `/botserver?cmd=<hex>`.
3. Keep heartbeat action `0x43` running after master registration.
4. Send read/write commands through UDP or HTTP using the same binary frames.
5. Stop DC motors, zero any continuous servos individually, and unregister
	with action `0x42` when finished. Heartbeat timeout does not release master.

## Start Here

| Page | Purpose |
|---|---|
| [ai-mandatory-checklist.md](ai-mandatory-checklist.md) | Steps a client must not skip |
| [ai-wiring.md](ai-wiring.md) | Expected board, sensor, servo, and power wiring; uses `wiring.png` as the cable source of truth |
| [ai-capabilities.md](ai-capabilities.md) | Sensors, servos, motors, LEDs, camera, sound, logs, and limits |
| [ai-udp-client.md](ai-udp-client.md) | Client implementation pattern with examples |
| [ai-services.md](ai-services.md) | Available UDP services and command groups |
| [quickstart.md](quickstart.md) | Minimal register-and-control flow |
| [binary-protocol.md](binary-protocol.md) | Full command reference |
| [communication.md](communication.md) | UDP and HTTP transport behavior |
| [ai-controller-prompt.md](ai-controller-prompt.md) | Copy-ready prompt for code-generation tasks |
| [participant-AGENTS.md](participant-AGENTS.md) | Reusable safety and source-of-truth instructions |

## Implementation Rule

Use the current master registration flow first, then make later HTTP or UDP calls from the same controller context. There is no `X-Bot-Token` API in the current firmware.

Before generating controller code, review the mandatory checklist and client
pattern. Do not copy old snippets without verifying their action IDs against
the active protocol reference. Never use a fabricated token or issue live
motion commands without explicit authorization.

## Web Management Surface Available From `/data`

Static pages can call the existing endpoints:

| Area | Existing runtime support |
|---|---|
| WiFi settings | Binary protocol `GET_WIFI`, `SET_WIFI`, `RESET_WIFI` through `/botserver` |
| Bot settings | Binary protocol `GET_NAME`, `SET_NAME` through `/botserver` |
| Bot actions | Raw binary command dispatch through `/botserver?cmd=<hex>` |
| User scripts/actions | `/scripts`, `/scripts/<name>` GET/POST/DELETE |
| Camera | `/cam/snapshot`, `/cam/stream` |
| Build info | `/api/buildinfo.json`, `/buildinfo.json` |
| Logs | Visible on the TFT log screens; no HTTP log CRUD endpoint exists in `/data` alone |

Because this implementation is restricted to `/data`, new firmware routes cannot be added here. Pages and docs must use the endpoints already exposed by the firmware.
