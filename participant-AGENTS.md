# K10 Bot Controller Instructions

Use these instructions when generating code that controls a K10 bot over UDP.

## Source of truth

- The active firmware handlers and protocol implementation define supported commands, payloads, limits, and behavior.
- Use `binary-protocol.md` for documented frames, `communication.md` for transport and master ownership, and `ai-mandatory-checklist.md` for lifecycle and safety.
- The operational SensorsScreen under `python_example/sensorscreen/` is a secondary example, not authority when it differs from firmware.
- Do not infer commands or payload layouts from sensor manufacturer libraries or older examples. Ask for missing protocol facts.

## Required control behavior

- Take the token at runtime from the user or a protected configuration source. Never commit, log, or invent it.
- Register with action `0x41` before master-protected writes. Keep an independent heartbeat running every 25-30 ms while control is active.
- Validate sender, action, response status, and payload length. Non-empty UDP replies append an 8-byte diagnostics trailer; PING has no status byte, and heartbeat has no reply. Use one receive dispatcher per socket when handling streams and acknowledgments together.
- Configure servo types before motion. Use action `0x24` for positional servo angles; `0x2A` is not implemented.
- On shutdown, exceptions, or interruption, best-effort send speed zero separately to each continuous servo configured by this client, then `0x28` to stop DC motors, then unregister with `0x42`. A lost packet cannot guarantee physical safety.
- Heartbeat timeout stops DC motors only; it does not stop continuous servos or release master ownership. Never treat it as a complete shutdown procedure.
- Never replay stale motion after a timeout. Do not issue live motion commands unless the user explicitly authorizes it.
- Sound-only controls do not require master registration. During playback, shock detection, LiDAR, HuskyLens, and UI refresh pause; do not rely on shock protection.

## Verification

- Run new control code against mocks or loopback first. Test failed registration, unexpected sender/action, status and length validation, UDP diagnostics, timeouts, and cleanup.
- Do not refer to a simulator unless one is provided. Do not claim hardware validation without testing on the actual device.
