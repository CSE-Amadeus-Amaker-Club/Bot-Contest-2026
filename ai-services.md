# UDP Services and Command Groups

Every command begins with one action byte:

```text
action = (service_id << 4) | command_id
```

Use [binary-protocol.md](binary-protocol.md) for the full byte-level reference. This page is the quick map for client planning.

| Service ID | Service | Main actions |
|---|---|---|
| `0x02` | MotorServoService | Motor speed, servo type, servo speed, servo angle, stop all, battery |
| `0x03` | DFR1216Board | Expansion LEDs, board battery/status |
| `0x04` | AmakerBotService | Register, unregister, heartbeat, ping, bot name, WiFi, reboot |
| `0x05` | LEDService | Unified K10/DFR LED color and off commands |
| `0x06` | AmakerBotUIService | Next/previous/set TFT screen |
| `0x07` | HuskyLensService | Illumination LED, algorithm, and stream controls; RGB/LCD requests stay HuskyLens-only and report unsupported on verified V1 protocol |
| `0x08` | LidarService | Distance/intensity scan, stats, config, stream controls |
| `0x09` | GeomagService | Heading, field, stream, config, calibration |
| `0x0A` | ImuService | Acceleration, stream, config, bump config/events |
| `0x0B` | SoundService | Play, stop, and playback status for LittleFS WAV files |

## Sound controls

SoundService accepts canonical PCM WAV files through the HTTP `/sounds` API
and controls playback through either HTTP or binary actions. Supported files
are mono or stereo, 16-bit, 8-48 kHz, no larger than 300 KiB, with a lowercase
`.wav` extension.

| Action | Purpose | Payload |
|---|---|---|
| `0xB1` | Queue/play a stored WAV file | Filename bytes, without a terminator |
| `0xB2` | Stop playback and clear any queued replacement | None |
| `0xB3` | Read playback state | None |

The UDP `PLAY` acknowledgement confirms command acceptance, not that the file
was found or that I2S playback started. Use HTTP when an immediate missing-file
error is required.

## HuskyLens V1 controls

HuskyLensService targets the HuskyLens V1/SEN0305 over I2C. External clients send
UDP commands only to the K10; no UART transport is used by the Python client or
the firmware service.

The illumination LED command is supported by `0x71`. Firmware tries the MakeCode
V1 sensor command byte first (`0x31`) and falls back to the Arduino enum-derived
command byte (`0x3D`) if the device does not acknowledge the first attempt.

RGB/status-light and LCD/display requests are exposed as HuskyLens-only commands
(`0x76` and `0x77`) so clients can present those controls without touching K10
hardware. On verified public V1 protocol references they are unsupported and return
`resp_operation_failed`.

## Command Access Pattern

| Category | Client requirement |
|---|---|
| Read-only query | Usually allowed without master |
| Write/config/action | Register master first |
| Motion command | Register master and keep heartbeat active |
| Long-running stream | Plan async receive loop and heartbeat loop separately |

## Response Pattern

Most responses are:

```text
[action][resp_code][payload...]
```

Exceptions:

| Action | Exception |
|---|---|
| `0x44` PING | Response is `[0x44][id0][id1][id2][id3]` without `resp_code` |
| `0x43` HEARTBEAT | No response |
| `0x4A` REBOOT | No response if accepted |

## HTTP Action Executor Pattern

For browser tools, send the same binary frame as hex:

```text
GET /botserver?cmd=44aabbccdd
```

This sends PING with ID bytes `aa bb cc dd` and returns raw binary bytes.

A browser UI must decode the `ArrayBuffer` response instead of calling `response.json()`.
