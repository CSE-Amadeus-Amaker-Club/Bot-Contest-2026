# Quick Start: Register & Control Servos

## Sound-Only Quick Start

Sound-only control does not require master registration or heartbeat. See
[Sound: Convert, Store, and Play](ai-udp-client.md#sound-convert-store-and-play)
for conversion, upload, playback, and safe cleanup instructions. Sound playback
pauses shock detection and several sensor/UI activities; do not rely on shock
protection while audio is active.

## Motion Control

Connect to the Wi-Fi network shown on the bot's screen. The bot accepts UDP
commands on port `24642`. Read the five-character master token from Screen 1
(App Info); pass that exact token as ASCII bytes, not as a hard-coded example.

Register with action `0x41`, then keep an independent heartbeat (`0x43`)
running every 25-30 ms while controlling the bot. A heartbeat timeout stops
DC motors only and does not release master ownership. `STOP_ALL_MOTORS`
(`0x28`) also stops DC motors only. Before unregistering or exiting, send
speed zero (`0x23`) individually to each continuous servo configured by your
client, then send `0x28` and unregister with `0x42`. These are best-effort
network commands, not a guarantee of physical safety.

| Action | Frame | Notes |
|---|---|---|
| Register | `41 <five uppercase-hex ASCII token bytes>` | Token is shown on the bot screen. |
| Heartbeat | `43` | No reply; send every 25-30 ms. |
| Unregister | `42` | Does not happen automatically on heartbeat timeout. |
| Set servo type | `22 <mask> <type>` | `0=180 degree`, `1=270 degree`, `2=continuous`. |
| Set servo speed | `23 <mask> <speed>` | Continuous servos only; signed speed from -100 to 100. |
| Set positional angle | `24 <mask> <hi> <lo>` | Big-endian signed 16-bit angle; configure type first. |
| Stop DC motors | `28` | Does not stop continuous servos. |

`0x2A` is declared in a firmware header but is not implemented by the active
handler. Do not send it; use configured `0x24` for positional servo angles.
Standard responses begin `[action][status]`; non-empty UDP replies append an
8-byte diagnostics trailer. PING (`0x44`) is an exception and has no status
byte.

Use the [validated Python controller example](ai-udp-client.md#python-skeleton)
for registration, concurrent heartbeat, response validation, timeout handling,
continuous-servo cleanup, and unregister sequencing. The [binary protocol](binary-protocol.md)
is the complete command reference; [communication](communication.md) documents
UDP and HTTP behavior.

---

*More commands: [binary-protocol](binary-protocol.html) · Full transport details: [communication](communication.html)*
