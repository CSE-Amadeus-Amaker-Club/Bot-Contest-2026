# K10 Bot — SensorsScreen (Python/OpenCV UDP replica)

Reproduces the device's on-board SensorsScreen (HuskyLens, Lidar, IMU, Geomag) on the host,
using the same UDP protocol as the firmware — no serial/USB connection needed.

## Setup

```bash
cd python_example/sensorscreen
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp sensorscreen.conf.example sensorscreen.conf
```

Edit `sensorscreen.conf` with the bot's IP and the 5-character master token shown on its screen.

Current firmware stream-rate limits enforced by this client:
- `lidar_hz`: `1..8`
- `geomag_hz`: `1..50`
- `imu_hz`: `1..25`
- `huskylens_hz`: `0..20`

Optional UDP command mode:
- `udp_fire_and_forget = true` in `sensorscreen.conf` sends commands without waiting for ACK replies.
- CLI equivalent: `--fire-and-forget`.

## Run

```bash
python main.py
# or override the config file:
python main.py --ip 192.168.4.1 --token abc12
# run in fire-and-forget mode:
python main.py --ip 192.168.4.1 --token abc12 --fire-and-forget
# record raw LIDAR distance frames as JSONL:
python main.py --ip 192.168.4.1 --token abc12 --capture captures/lidar.jsonl
```

Each captured line contains the host timestamp, firmware frame ID, sensor timestamp,
point count, and distance values in millimeters. The file is appended to when it already exists.

Press `q` or `Esc`, or close the window, to quit (this cleanly disables streaming and
unregisters as master on the bot).

## K10 display controls

The button row below the dashboard title changes the physical K10 display. Select
`SPLASH`, `APP INFO`, `SENSORS`, `APP LOG`, `SVC LOG`, `DEBUG`, or `ESP LOG` to
switch directly to that screen. The status under the buttons shows the latest K10
UDP acknowledgement.

## HuskyLens controls

The top HuskyLens panel header includes HuskyLens-only controls:

| Control | Firmware command | Behavior |
|---|---|---|
| `MODE < / >` | `0x74` | Cycles V1 algorithms: face, object tracking, object recognition, line, color, tag. |
| `RGB` | `0x76` | Sends a HuskyLens RGB/status-light request; V1 firmware reports unsupported until a verified command exists. |
| `LCD` | `0x77` | Sends a HuskyLens LCD/display request; V1 firmware reports unsupported until a verified command exists. |

These controls do not use serial/UART and do not call K10 LED or K10 display
services. The status text under each button shows the most recent UDP acknowledgement.

## Servo controls

The bottom control band exposes the six DFR1216 servo channels as `S1` through `S6`
(firmware channels `0` through `5`). Configure each channel in `sensorscreen.conf`:

```ini
[servos]
s1_type = angle180
s2_type = angle270
s3_type = continuous
```

Valid types are `angle180`, `angle270`, and `continuous`. SensorsScreen sends all six
configured types after it registers as UDP master. Continuous channels are immediately
commanded to speed `0` after their mode is set.

Click `180`, `270`, or `CONT` to change a channel during a session. Positional sliders
send angles in their valid range; continuous sliders send speed from `-100` to `100`.
Dragging sends at most 10 UDP commands per second and always sends the final value when
the mouse button is released. `STOP` sets a continuous channel to zero. `STOP ALL` first
sends individual zero-speed commands to continuous channels configured during this client
session, then sends firmware action `0x28` to stop DC motors. Action `0x28` alone does not
stop continuous servos.
 Unchanged servo values are suppressed. When a value changes, the UDP client sends at most two motion frames for that logical update, using the acknowledgement or command timeout to advance the bounded repeat. A newer value cancels remaining repeats for the older value, so stale stick or slider positions are not replayed. Heartbeats are separate and continue at the watchdog-safe 30 ms cadence.

## Gamepad action mapping

Gamepad mappings can be configured once at startup in `sensorscreen.conf` under `[gamepad]`.
Each key maps to a Python call expression. The app resolves callables during startup, and
injects runtime control values through `$value`.

Example:

```ini
[servos]
s1_type = continuous
s2_type = continuous
s4_type = angle270
s4_min_angle = 45
s4_max_angle = 120
s5_type = angle270
s5_min_angle = 140
s5_max_angle = 270

[gamepad]
left_stick_x = gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)
left_stick_y = gamepad_callbacks.set_track_drive(leftchannel=0,rightchannel=1)
left_bumper = gamepad_callbacks.set_paired_angle(side="left",servonumber=3)
left_trigger = gamepad_callbacks.set_paired_angle(side="left",servonumber=3)
right_bumper = gamepad_callbacks.set_paired_angle(side="right",servonumber=4)
right_trigger = gamepad_callbacks.set_paired_angle(side="right",servonumber=4)
button_a = gamepad_callbacks.set_led(red=0,green=255,blue=0,buttonvalue=$value)
```

Servo numbers are zero-based: S1=0, S2=1, S4=3, S5=4. `set_track_drive`
uses both left-stick axes: up/down drives both tracks forward/backward; left
turns S1 forward and S2 backward, and right reverses that turn. Inputs outside
the 12% centered deadzone are rescaled progressively; diagonal inputs are
proportionally limited to preserve steering without exceeding 100% speed.
The right stick does not drive the tracks in this mapping.

`set_paired_angle` reads both same-side controls from one snapshot. The trigger
sets position within `[servos]` limits; the bumper holds the maximum. Releasing
the bumper resumes the current trigger position. Releasing both returns to
the configured minimum. These same limits apply on controller disconnect.
With no `[gamepad]` actions, the built-in mapping uses the same S1/S2 and S4/S5
assignments. Existing `set_speed` and `set_angle` callbacks remain available
for independent custom mappings.

Recognized controllers use SDL's device-specific axis mapping, logged when
connected. For example, the USB Xbox 360 layout uses left-stick axes 0/1,
left trigger axis 2, right-stick axes 3/4, and right trigger axis 5.
Trigger axes are released=-1 and pressed=+1; bumper buttons remain 4/5.
If SDL mapping is unavailable, the client falls back to stick axes 0/1 and
2/3 with trigger axes 4/5. Verify the logged mapping, directions, and limits
with tracks raised before ground operation.

On exit or Stop All, the client cancels pending commands and explicitly sends
zero-speed packets individually to channels configured as continuous during
the session, before sending the DC-motor stop command. Separate packets prevent
a now-positional channel from causing firmware to reject the entire servo
stop mask. UDP stopping is best-effort, not a guaranteed hardware acknowledgement.

Supported keys:
- `left_stick_x`, `left_stick_y`, `right_stick_x`, `right_stick_y`
- `left_trigger`, `right_trigger`
- `left_bumper`, `right_bumper`
- `button_a`, `button_b`, `button_x`, `button_y`, `button_lb`, `button_rb`, `button_guide`

`$value` semantics:
- `button_*`: boolean (`true` on press, `false` on release)
- bumpers: boolean
- triggers: float in `0.0..1.0`
- sticks: integer speed in `-100..100`

Built-in helpers are in `gamepad_callbacks.py`, and you can also reference any importable
dotted callable path. Because callbacks can execute arbitrary Python code, treat the config
file as trusted input.

## Tests

```bash
# Local venv created in Setup
source venv/bin/activate
python -m pip install -e .[dev]
python -m pytest -q tests/

# Or using uv
uv sync --extra dev
uv run python -m pytest -q tests/
```



## Sound Controls

Yes, your board can play sounds, just for fun. **The problem with sound is that it takes highest priority on on one core** for quality: **during playback, LiDAR, HuskyLens, UI refresh, and shock detection pause !** and IMU/Geomag telemetry are on best-effort.

The sound dropdown lists stored WAV files from HTTP `GET /sounds`.
Select a filename and play it through the onboard speaker; the control uses
the existing UDP client when available, with HTTP playback as a fallback.
Prepare compact effects with SoX:

```bash
sox input.wav -r 11025 -c 1 -b 8 -e unsigned-integer alert.wav
soxi alert.wav
```

Unsigned 8-bit mono 11025 Hz PCM uses about 10.8 KiB/second; it sacrifices
fidelity to save flash space and transfer time. The complete file must be
at most 300 KiB. List/upload/delete are direct HTTP operations, not sensor
stream frames. See [the sound tutorial](../../ai-udp-client.md#sound-convert-store-and-play)
for curl commands, Python HTTP/UDP examples, and safe stop/delete sequencing.

In application code, call the existing `client.queue_play_sound("alert.wav")`.
This queues a UDP PLAY command, not a guarantee of audible playback.
`SoundHttpClient.list_sounds()` returns JSON bytes; `play_sound(filename)`
and `stop_sound()` provide HTTP control. That wrapper has no upload/delete
methods; use the tutorial's HTTP requests for those operations.

For a gamepad mapping in `sensorscreen.conf`:

```ini
[gamepad]
button_a = gamepad_callbacks.play(filename="alert.wav",buttonvalue=$value)
```

