# UDP Client Implementation Pattern

This page gives an AI agent enough structure to write a safe K10 bot client.

## Sound: Convert, Store, and Play

SoundService plays stored WAV files through the onboard speaker. Use HTTP on
port 80 for file management and HTTP or UDP on port 24642 for playback.
Sound-only commands do not require a master token, registration, or heartbeat.
Clients that also control motion must still register, maintain heartbeats, and
stop motors before exiting.

### Make a Small WAV with SoX

Install SoX with your Linux package manager (on Debian/Ubuntu, `sudo apt install sox`).
Convert a local WAV into a different output file:

```bash
sox input.wav -r 11025 -c 1 -b 8 -e unsigned-integer alert.wav
soxi alert.wav
wc -c < alert.wav
```

`-r 11025` selects 11,025 samples per second, `-c 1` mixes to mono,
`-b 8` uses one byte per sample, and `-e unsigned-integer` selects unsigned
PCM encoding. Check that `soxi` reports one channel, 11025 Hz, 8-bit precision,
and unsigned integer PCM. Renaming another audio format to `.wav` is not conversion.

This minimalist preset uses **11,025 bytes/second (about 10.8 KiB/second)**
of PCM, excluding WAV headers and metadata. Compared with 44,100 Hz stereo
16-bit PCM (176,400 bytes/second), it is **16 times smaller**. Smaller files
save flash space, shorten transfers, and allow more sounds in the bounded
PSRAM cache. The tradeoff is reduced high-frequency detail, amplitude
resolution, and stereo separation; listen to the result before deploying it.
It is a recommendation for short effects, not the only supported format.

The bot accepts uncompressed PCM WAV (format 1): unsigned 8-bit or signed
16-bit, mono or stereo, and sample rates from 8,000 to 48,000 Hz.
Compressed and WAVE_FORMAT_EXTENSIBLE files are unsupported. The **complete
file must be at most 300 KiB (307,200 bytes)**, and uploads must leave
128 KiB free. Prefer simple ASCII filenames such as `alert.wav`, no more
than 48 bytes including the lowercase `.wav` extension. Do not use paths,
`..`, `/`, `\`, `:`, or NUL in filenames.

### List and Upload Files

Connect to the bot's network and replace the IP below. Only upload audio
you have permission to use. The browser alternative is
`http://<bot-ip>/soundservice.html`.

```bash
BOT=http://192.168.1.100
curl -fsS --max-time 10 "$BOT/sounds"
curl -fsS --max-time 30 -X POST -H 'Content-Type: audio/wav' \
  --data-binary @alert.wav "$BOT/sounds/alert.wav"
curl -fsS --max-time 10 "$BOT/sounds"
```

`GET /sounds` returns JSON: `sounds` is the filename array; `free_bytes`
reports remaining shared filesystem space. `playback_state`, `active_sound`,
and `last_error` describe playback. Upload the **raw file body**, not
multipart form data (`curl -F`), base64, or hex. A successful upload returns
HTTP 200 `OK` after WAV validation; failure returns 400. Re-uploading the
same filename replaces it and invalidates its cached PCM. Uploads and
deletes are rejected while playback is active; playback is rejected during
an upload. Coordinate clients so file changes and play requests cannot race.

### Play, Stop, and Delete Files

```bash
curl -fsS --max-time 10 -X POST "$BOT/sounds/volume?value=50"
curl -fsS --max-time 10 -X POST "$BOT/sounds/alert.wav/play"
curl -fsS --max-time 10 "$BOT/sounds"
curl -fsS --max-time 10 -X POST "$BOT/sounds/stop"
curl -fsS --max-time 10 "$BOT/sounds"
```

HTTP play returns 200 when accepted, not when playback completes. Inspect
`playback_state` and `last_error` for asynchronous failures. Playing another
sound replaces the active sound after its cleanup; this is not a playlist.
Volume is a percentage from 0 to 100, defaulting to 100 after boot.

Stop is asynchronous. After the stop request, poll `GET /sounds` until
`playback_state` is no longer `starting`, `playing`, or `stopping`, with a
bounded timeout (for example, 10 seconds). Do not use `playing: false` alone:
startup or cleanup may still be active. If the timeout expires, do not delete.
Once inactive, delete the disposable example and verify the list:

```bash
curl -fsS --max-time 10 -X DELETE "$BOT/sounds/alert.wav"
curl -fsS --max-time 10 "$BOT/sounds"
```

Delete returns 200 on success. Play/delete return 404 for missing files or
refused operations, including busy conditions; check state before assuming
the file is absent. File management uses direct HTTP routes, not `/botserver`.

### Trigger Playback from Python over HTTP

This standalone example uses only the Python standard library and an already
uploaded `alert.wav`. HTTP failures and timeouts raise exceptions.

```python
import json
from urllib.request import Request, urlopen

bot_url = "http://192.168.1.100"
with urlopen(f"{bot_url}/sounds", timeout=10) as response:
    catalog = json.load(response)
if "alert.wav" not in catalog["sounds"]:
    raise RuntimeError("Upload alert.wav first")

request = Request(f"{bot_url}/sounds/alert.wav/play", method="POST")
with urlopen(request, timeout=10) as response:
    print(response.read().decode())
with urlopen(f"{bot_url}/sounds", timeout=10) as response:
    state = json.load(response)
print(state["playback_state"], state["last_error"])
```

### Trigger Playback from Python over UDP

Use a dedicated sound socket so sensor frames and other acknowledgments
cannot be mistaken for sound replies. Send the stored filename as ASCII
bytes without a NUL terminator, path, or URL encoding:

```python
import socket

bot_address = ("192.168.1.100", 24642)
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sound_socket:
    sound_socket.settimeout(1.0)
    sound_socket.sendto(b"\xB1" + b"alert.wav", bot_address)
    reply, sender = sound_socket.recvfrom(64)
    if sender != bot_address or len(reply) < 2 or reply[0] != 0xB1:
        raise RuntimeError("Unexpected sound reply")
    if reply[1] != 0:
        raise RuntimeError(f"Sound command rejected: 0x{reply[1]:02x}")
    print("Play request queued; inspect GET /sounds for playback state")
```

UDP replies append an 8-byte diagnostics trailer; status remains byte 1.
PLAY success only means the bounded command queue accepted the request:
file existence and playback are checked later. List the file before sending;
`GET /sounds` reports playback errors, but an invalid queued filename may be
rejected before a new playback state is recorded. A timeout is an uncertain
outcome: do not automatically resend PLAY and restart a sound that already began.

| Action | Request bytes | Response before UDP diagnostics |
|---|---|---|
| PLAY | `[0xB1][filename bytes]` | `[0xB1][status]` |
| STOP | `[0xB2]` | `[0xB2][status]` |
| STATUS | `[0xB3]` | `[0xB3][status][playing: 0 or 1]` |
| VOLUME | `[0xB4][percentage: 0..100]` | `[0xB4][status]` |

During audio-exclusive playback, LiDAR, HuskyLens, UI refresh, and the shock
watcher pause; IMU/Geomag telemetry is best-effort at 10 Hz. Shock events are
not detected during this interval. Sound stop is **not** a motor emergency stop.
See [the protocol reference](binary-protocol.md#service-0x0b-soundservice).

## Core Rules

- Use UDP `:24642` for real-time control.
- Use HTTP `/botserver?cmd=<hex>` for browser tools and debugging.
- Register master with `0x41` before master-protected commands.
- Keep heartbeat `0x43` running every 25-30 ms after registration.
- Stop motion outputs before exit.
- Parse standard responses as `[action][resp_code][payload...]` except PING.
- ACK format is `[action][resp_code]` (no full-frame echo).
- Over UDP, non-empty replies append an 8-byte diagnostics trailer:
    `[rx_seq_be32][server_millis_be32]`.

## Python Skeleton

This is the canonical first-motion example. Run it with `--ip <bot-ip>` and
`--token <screen-token>`. Keep the mechanism unloaded and clear before moving
servo channel 0. It configures a 270-degree positional servo and requests 90
degrees. Match the type to your actual hardware before running.

```python
import argparse
import socket
import struct
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument("--ip", required=True)
parser.add_argument("--token", required=True)
args = parser.parse_args()
token = args.token.encode("ascii")
if len(token) != 5:
    raise ValueError("Use the five-character token from the bot screen")
bot_address = (socket.gethostbyname(args.ip), 24642)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
heartbeat_stop = threading.Event()
heartbeat_failed = threading.Event()
heartbeat_thread = None
registration_attempted = False
registered = False
continuous_channels = set()


def request(frame, *, cleanup=False):
    if heartbeat_failed.is_set() and not cleanup:
        raise RuntimeError("Heartbeat sender failed; stop the session")
    sock.sendto(frame, bot_address)
    deadline = time.monotonic() + 0.5
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("No matching reply; command outcome is uncertain")
        sock.settimeout(remaining)
        reply, sender = sock.recvfrom(2048)
        if sender != bot_address or len(reply) < 10:
            continue
        protocol_reply = reply[:-8]
        if len(protocol_reply) < 2 or protocol_reply[0] != frame[0]:
            continue
        if protocol_reply[1] != 0:
            raise RuntimeError(f"Command 0x{frame[0]:02x}: status 0x{protocol_reply[1]:02x}")
        return protocol_reply


def heartbeat_loop():
    while not heartbeat_stop.is_set():
        try:
            sock.sendto(b"\x43", bot_address)
        except OSError:
            heartbeat_failed.set()
            return
        heartbeat_stop.wait(0.025)


def set_servo_type(mask, servo_type):
    if not 1 <= mask <= 0x3F or servo_type not in (0, 1, 2):
        raise ValueError("Invalid servo mask/type")
    request(bytes([0x22, mask, servo_type]))
    for channel in range(6):
        if mask & (1 << channel):
            if servo_type == 2:
                continuous_channels.add(channel)
            else:
                continuous_channels.discard(channel)


def set_servo_angle(mask, angle, maximum=270):
    if not 1 <= mask <= 0x3F or not 0 <= angle <= maximum:
        raise ValueError("Invalid positional servo mask/angle")
    request(bytes([0x24, mask]) + struct.pack(">h", angle))


try:
    registration_attempted = True
    request(b"\x41" + token)
    registered = True
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    set_servo_type(0x01, 1)
    set_servo_angle(0x01, 90)
    time.sleep(0.2)
    if heartbeat_failed.is_set():
        raise RuntimeError("Heartbeat sender failed")
finally:
    if registered:
        stop_frames = [bytes([0x23, 1 << channel, 0]) for channel in sorted(continuous_channels)]
        stop_frames.extend((b"\x28", b"\x42"))
        for frame in stop_frames:
            try:
                request(frame, cleanup=True)
            except (OSError, RuntimeError) as error:
                print(f"Cleanup not confirmed for 0x{frame[0]:02x}: {error}")
    elif registration_attempted:
        try:
            request(b"\x42", cleanup=True)
        except (OSError, RuntimeError) as error:
            print(f"Unregister not confirmed after registration timeout: {error}")
    heartbeat_stop.set()
    try:
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=1)
    finally:
        sock.close()
```

The app uses the same `0x22`/`0x24` builders and stops continuous servos
individually before DC motors and unregistering. Updated `0x28` also stops
configured continuous servos and invalidates prior deferred motion while
preserving positional holding. Older firmware stops DC motors only. This
example tracks types changed in its own session, not types
configured by other clients. Do not change servo types concurrently.

This minimal example does not enable streams. Streaming clients need one
receiver that routes events and matching acknowledgments, as SensorsScreen
does. UDP has no per-command transaction ID: do not retry/replay motion after
a timeout or confuse a delayed acknowledgment with a newer command.

## HTTP Helper Pattern

```python
import urllib.request

BOT = "http://192.168.1.100"


def http_frame(frame: bytes) -> bytes:
    url = f"{BOT}/botserver?cmd={frame.hex()}"
    with urllib.request.urlopen(url, timeout=1) as resp:
        if resp.status == 204:
            return b""
        return resp.read()

# Register using the exact token shown on the bot screen.
token = input("Token shown on the bot screen: ")
if len(token) != 5 or any(char not in "0123456789ABCDEF" for char in token):
    raise ValueError("Expected the five-character uppercase hex token on the bot")
print(http_frame(b"\x41" + token.encode("ascii")).hex())

# Later calls are still protected by registered master IP; no X-Bot-Token header exists.
print(http_frame(bytes([0x45])).decode("latin1", errors="replace"))
```

## Sensor Stream Handling

Streams are asynchronous UDP frames. A robust client separates:

| Loop | Purpose |
|---|---|
| Heartbeat loop | Sends `0x43` every 25-30 ms |
| Command/reply loop | Sends commands and waits for matching replies |
| Stream receive loop | Accepts frames such as LiDAR, geomag, IMU, HuskyLens |

Use action byte to identify frames. For example, LiDAR distance stream uses service `0x08` with command nibble `0x0F`, action `0x8F`.

## HuskyLens controls

HuskyLens commands use service ID `0x07`. Keep them separate from K10 UI and LED
commands:

| Action | Purpose | Payload |
|---|---|---|
| `0x74` | Select HuskyLens algorithm | `[0..5]` |
| `0x76` | HuskyLens RGB/status-light request | `[0|1]`; V1 currently reports unsupported |
| `0x77` | HuskyLens LCD/display request | `[0|1]`; V1 currently reports unsupported |
| `0x78` | Read HuskyLens control support/state | none |

Do not map `0x76` to the K10 NeoPixel service and do not map `0x77` to K10 TFT
screen navigation. They are reserved for HuskyLens-only control state.

## Error Handling

| Response code | Client behavior |
|---|---|
| `0x00` | Continue |
| `0x01` / `0x02` | Fix payload shape or values |
| `0x03` | Operation failed; check hardware readiness |
| `0x04` | Service not started; retry only after checking boot/hardware |
| `0x05` / `0x06` | Wrong service or command byte |
| `0x07` | Register master again from this sender IP |
