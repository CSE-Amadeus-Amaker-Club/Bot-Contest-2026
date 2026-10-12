# K10 Bot Client Agent Instructions

This repository publishes participant documentation and the SensorsScreen
Python client. Generate controllers against the existing firmware; do not
invent commands, authentication headers, endpoints, or hardware capabilities.

## Read Before Coding

| Reference | Owns |
|---|---|
| [binary-protocol.md](binary-protocol.md) | Command bytes, payloads, response layouts |
| [ai-mandatory-checklist.md](ai-mandatory-checklist.md) | Session lifecycle and safety requirements |
| [ai-udp-client.md](ai-udp-client.md) | Runnable controller and sound examples |
| [ai-sensors.md](ai-sensors.md) | Sensor prerequisites and decoding context |
| [ai-wiring.md](ai-wiring.md) | Physical connections |
| [ai-agent-readme.md](ai-agent-readme.md) | Code-generation prompt and required inputs |

When the sibling firmware repository is available, its active handlers in
`include/services` and `src/services` are the source of truth. Resolve any
documentation discrepancy against that code and report it. Without source
access, do not guess missing payload layouts; ask for the relevant reference.

## Mandatory Constraints

- Register before master-protected commands; use an independent heartbeat
  sender every 25-30 ms. After heartbeat starts, a timeout over 50 ms stops DC
  motors only; it does not release master ownership.
- Send speed zero individually to every continuous servo configured by the
  client, then best-effort `STOP_ALL_MOTORS` before unregistering on normal
  exit, exceptions, and interruption. `0x28` and heartbeat timeout stop DC
  motors only; neither guarantees physical safety or releases master ownership.
- Validate sender, action, status, and payload length. UDP non-empty replies
  append 8-byte diagnostics; strip them before decoding payloads. PING has no
  status byte, and heartbeat has no reply.
- Use one receive dispatcher per socket; route events and acknowledgments
  separately. Do not let competing receiver threads consume each other's packets.
- Configure servo type before motion, validate masks/ranges, and never replay
  stale motion after a timeout. `0x2A` is not implemented; use configured `0x24`.
- Sound-only clients need no registration. Use the
  [sound tutorial](ai-udp-client.md#sound-convert-store-and-play) for conversion,
  file management, playback, and sensor/shock-polling pause limitations.
- HuskyLens algorithm selection is exposed through `0x74`; RGB/LCD commands
  currently report unsupported. Training is performed on the sensor.
- Do not log WiFi credentials, hardcode participant tokens, change firmware
  timing, or send live motion commands without explicit user authorization.

## Verification

Compile/run new examples against mocks or loopback first. Cover failed
registration, wrong-action packets, diagnostics trailers, timeouts, and
cleanup. There is no maintained bot simulator in this repository; do not
reference a nonexistent simulator path. Use the
[SensorsScreen README](python_example/sensorscreen/README.md) for its actual
setup and tests, and scoped instructions when editing that client.

## Documentation Maintenance

Keep protocol tables in the protocol reference, runnable examples in the
client guide, and contest policy in the participant guide. Link to these
instead of copying them. Keep safety text literal; reserve humor for
participant tips. Firmware handlers own protocol behavior. Firmware
`/data/www/help` files are the source only for pages intentionally mirrored by
the publishing workflow; the participant contest guide is owned by this repository.
