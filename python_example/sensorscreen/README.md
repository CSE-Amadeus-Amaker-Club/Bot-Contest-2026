# K10 Bot — SensorsScreen (Python/OpenCV UDP replica)

Reproduces the device's on-board SensorsScreen (HuskyLens, Lidar, IMU, Geomag) on the host,
using the same UDP protocol as the firmware — no serial/USB connection needed.

## Setup

```bash
cd example-clients/python/sensorscreen
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp sensorscreen.conf.example sensorscreen.conf
```

Edit `sensorscreen.conf` with the bot's IP and the 5-character master token shown on its screen.

## Run

```bash
python main.py
# or override the config file:
python main.py --ip 192.168.4.1 --token abc12
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
| `LED` | `0x71` | Toggles the HuskyLens illumination LED. |
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
the mouse button is released. `STOP` sets a continuous channel to zero. `STOP ALL` sends
the firmware emergency-stop command, which stops continuous servos and DC motors.

## Tests

```bash
pip install pytest
pytest tests/
```
