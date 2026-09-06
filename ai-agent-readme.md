# AI Agent Guide: K10 Bot UDP Client

This bundle is for an AI agent or developer writing a client for the Unihiker K10 bot controller.

The active control path is the existing binary bot protocol. Do not invent a new authentication header. The expected flow is:

1. Human read the 5-character token from the TFT Info screen.
2. Register master with action `0x41` over UDP port 24642.
3. Keep heartbeat action `0x43` running after master registration.
4. Send read/write infos/commands through UDP using the same binary frames.
5. Stop motion outputs and unregister with action `0x42` when finished.

## Start Here

| Page | Purpose |
|---|---|
| [quickstart](quickstart.md) | Runtime environment, transport setup, and first control flow |
| [ai-mandatory-checklist](ai-mandatory-checklist.html) | Steps a client must not skip |
| [ai-wiring](ai-wiring.html) | Expected board, sensor, servo, and power wiring; uses `wiring.png` as the cable source of truth |
| [ai-capabilities](ai-capabilities.html) | Sensors, servos, motors, LEDs, logs, and limits |
| [ai-sensors](ai-sensors.html) | Sensor hardware capabilities and the subset exposed over UDP |
| [ai-udp-client](ai-udp-client.html) | Client implementation pattern with examples |
| [ai-services](ai-services.html) | Available UDP services and command groups |
| [binary-protocol](binary-protocol.html) | Full command reference |
| [communication](communication.html) | UDP transport behavior |

## Implementation Rule

Use the current master registration flow first, then make later UDP calls from the same controller context (based on IP address). There is **no** `X-Bot-Token` API in the current firmware.

## Available Control Surface

This branch documents UDP control only.

Use UDP port 24642 for WiFi settings, bot settings, bot actions, motion control, sensor reads, and streams. Logs are visible on the K10 TFT log screens.
