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
| `0x05` | LEDService | Unified LED color and off commands |
| `0x06` | AmakerBotUIService | Next/previous/set TFT screen |
| `0x07` | HuskyLensService | Light and stream controls |
| `0x08` | LidarService | Distance/intensity scan, stats, config, stream controls |
| `0x09` | GeomagService | Heading, field, stream, config, calibration |
| `0x0A` | ImuService | Acceleration, stream, config, bump config/events |

These services describe the current remote-control surface, not every feature of the underlying hardware. See [Sensors](ai-sensors.html) for the distinction.

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

## UDP Action Executor Pattern

Send the binary frame bytes directly to UDP port 24642:

```python
sock.sendto(bytes([0x44, 0xAA, 0xBB, 0xCC, 0xDD]), (BOT_IP, 24642))
data, _ = sock.recvfrom(64)
```

This sends PING with ID bytes `aa bb cc dd` and returns raw binary bytes. See [ai-udp-client.md](ai-udp-client.md) for a complete client skeleton.
