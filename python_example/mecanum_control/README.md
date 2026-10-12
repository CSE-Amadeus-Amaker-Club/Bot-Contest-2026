# K10 Mecanum Bot

Standalone uv desktop application for the sensorless K10 mecanum bot.
The Python package remains `mecanum_control`; the executable is `mecanum-bot`.
No SensorsScreen installation or repository-wide Python environment is required.

## Setup and Run

Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
Run these commands from the **k10-bot-gh-pages repository root**, on Linux
or Windows PowerShell:

```bash
uv sync --project python_example/mecanum_control --locked
uv run --project python_example/mecanum_control --locked mecanum-bot
```

uv uses the project's Python 3.13 pin, `uv.lock`, and its own `.venv` under
`python_example/mecanum_control/`. Application code supports Python 3.11+.
uv downloads the pinned interpreter if it is not installed. Existing sibling
applications and the repository-root environment are not modified.

Alternative module launch and configuration overrides:

```bash
uv run --project python_example/mecanum_control --locked python -m mecanum_control --ip 192.168.4.1
uv run --project python_example/mecanum_control --locked mecanum-bot --config /path/to/settings.json
```

Use the settings button to edit IP/hostname, UDP port (24642), HTTP port (80),
wheel connectors, reversal switches, deadzone, and rotation sensitivity.
Enter the five-character uppercase hex master token shown on the K10 screen
in the masked field, then Connect. The token is memory-only and is not saved
or logged. Nonsecret settings are saved under `~/.config/k10-mecanum-bot/`
on Linux or `%APPDATA%\k10-mecanum-bot\` on Windows.
See [config.example.json](config.example.json) for the settings format.

Registration and each startup servo-type/zero-speed command wait up to one
second for their WiFi ACKs; live motion commands retain their 100 ms deadline.
Heartbeat continues throughout servo setup. The app starts its camera stream
only after setup succeeds, avoiding extra camera traffic during configuration.
A missing registration ACK is not proof of a
wrong token: a received rejection produces a different error. Timeouts show
the resolved IP/port and counts of received, wrong-sender, malformed, and
unrelated packets without logging token or packet contents. With zero replies,
check that the settings match the bot's displayed IP and UDP port, that both
devices are on the same reachable network, and that the firewall permits UDP
replies. With rejected packets, check the sender and firmware protocol version.
After registration, a setup timeout is labeled "Registered; servo setup failed".
Close any browser camera stream while diagnosing UDP setup latency. The camera
is not started if setup fails, and closes if the control session ends;
this is not evidence that the HTTP camera itself is broken.

For a timeout immediately after Resume, uncheck Camera before connecting, or run:

```bash
uv run --project python_example/mecanum_control --locked mecanum-bot --no-camera
```

Close external browser camera streams for this comparison. The Camera switch
is locked during a connection; reconnect to change it. Disabling video does not
change registration, wheel control, heartbeat, or stop-on-timeout behavior.
Firmware currently sends queued UDP replies from Core 1 at priority 4, while
the Core 1 AsyncTCP callback encodes camera JPEGs at priority 10. This can delay
ACK transmission; on-device timing has not yet confirmed it as the timeout cause.
Motor/servo dispatch now skips synchronous packet logging even in verbose builds,
removing one shared logger-lock dependency before the ACK is queued. This firmware
change requires a firmware upload, not a filesystem-only upload.

Linux requires a graphical session, Qt platform libraries and SDL gamepad
access. Windows is targeted but has not been verified on a Windows machine.

When launched from Snap-packaged VS Code on Linux, startup restores the host
GTK variables backed up by VS Code and defaults to Qt's generic platform
theme. This avoids a native GLib abort about the missing GNOME `antialiasing`
schema key. Explicit `QT_QPA_PLATFORMTHEME` settings are preserved; other
platforms and terminals without Snap markers are unchanged.

## Controls

The wheel layout assumes X-arranged mecanum rollers viewed from above:

| Wheel | Connector | Protocol channel | Default reversal |
|---|---|---|---|
| Front left | S1 | 0 | No |
| Front right | S2 | 1 | Yes |
| Rear left | S3 | 2 | No |
| Rear right | S4 | 3 | Yes |

Reversal is a configurable mounting assumption, not verified hardware.
Verify directions and neutral with wheels unloaded before ground testing.
The client configures the selected channels as continuous servos; no sensor
streams, calibration, or sensor hardware are required.

| Xbox input | Action |
|---|---|
| Right stick XY | Robot-relative forward/backward and sideways translation |
| Left stick X | Rotation; stick right means clockwise |
| Left stick Y | Unused |
| A / B / X / Y | All LEDs green / red / blue / yellow; off on release |
| Left bumper / left trigger | Play `Rocket-hahaaa-take-that.wav` / `Rocket-are-you-kidding.wav` |
| Right bumper / right trigger | Play `Rocket-don-t-panic.wav` / `Rocket-okay-panic.wav` |

After each successful registration and servo setup the bot plays
`jarvis-connected.wav`; before unregistering a registered session it plays
`jarvis-disconnected.wav`. Sounds play once per press (triggers above 50%),
require SDL Xbox mapping, and must already be stored on the bot. PLAY is
never retried; a lost or rejected sound ACK is only logged. During playback
the firmware pauses LiDAR, HuskyLens, UI refresh, and shock polling.

Translation and rotation are mixed from one snapshot. Wheel speeds are
normalized together and limited by the speed slider, initially 30%.
SDL Xbox mapping is preferred; raw joystick indices are configurable.
The status area shows translation with ↑/↗/→/↘/↓/↙/←/↖ and rotation with
⟲/⟳. A `?` means a changed four-wheel command batch is not fully ACK-confirmed;
`-` means paused or no command on that axis. ACKs confirm queuing, not physical
movement.

Center the sticks and press Resume after connecting or pausing. There is
**no hold-to-drive bumper** and **video loss does not stop driving**.
STOP, window focus loss, controller removal, and stale input pause motion.
A single missed motion ACK is logged and not replayed; the next pass sends
speeds mixed from fresh input, or pauses if input is stale. Three consecutive
missed motion ACKs, a heartbeat fault, a socket error, or a command rejection
after setup zero the wheels, send `0x28`, unregister, and reconnect
automatically with 0.5-5 s backoff. A reconnected session stays paused until
the sticks are centered and Resume is pressed. Initial connection failures and
a token rejected during reconnect (for example after a bot reboot) end the
session so settings or the token can be corrected. LED ACK timeouts are logged only.
Disconnect, interruption, and window close perform best-effort cleanup.

## Protocol and Safety

The application uses the documented binary UDP protocol and the existing
HTTP `/cam/stream` MJPEG endpoint. There are no invented authentication headers
or camera settings routes. Read [the mandatory checklist](../../ai-mandatory-checklist.md),
[the client pattern](../../ai-udp-client.md), and
[the protocol reference](../../binary-protocol.md).

Used actions are registration `0x41`, independent heartbeat `0x43` every 25 ms,
continuous type `0x22`, signed servo speed `0x23`, LEDs `0x51`, sound PLAY `0xB1`, stop `0x28`,
and unregister `0x42`. One UDP receiver validates sender, action, status and
reply length after removing the eight-byte diagnostics trailer.

Four distinct wheel speeds are sent as separate commands: the protocol has
no atomic four-wheel update or per-command transaction ID. ACKs confirm
deferred queuing, not physical movement. Commands are serialized; old demands
are not queued or replayed after a timeout. UDP duplication/reordering and
delayed acknowledgments remain protocol limitations.

Install and verify the sibling firmware safety patch before driving loaded
wheels. Updated firmware stops DC motors and configured continuous servos
on `0x28` or watchdog timeout and discards earlier deferred motion. Positional
holding is preserved. **Older firmware stops DC motors only**, so continuous
wheels may keep spinning after connection loss or a client crash. The app
cannot remotely certify the installed failsafe. Watchdog timeout does not
release master ownership.

Cleanup still zeros each selected continuous servo individually, sends `0x28`,
then unregisters while keeping heartbeat active. Network cleanup cannot
guarantee physical safety; keep a physical power cutoff accessible.

## Identify Wheel Servos

Disconnect the driving app, lift all wheels clear of the ground, and keep a
physical power cutoff accessible. From the repository root, run:

```bash
uv run --project python_example/mecanum_control --locked python -m mecanum_control.identify_servos --host 192.168.1.178
```

The script reads the saved configuration, asks for the master token in a hidden
prompt, configures only the selected wheel channels as continuous servos, and
zeros them before testing. It visits the configured connectors in numerical
order (S1 through S4 with the default settings). Press Enter to start each servo,
then press Enter again to stop it. Only that servo receives positive speed; a
zero-speed command must be acknowledged before continuing. There is no automatic
time limit. Saved wheel reversals are ignored so
you can record each connector's actual wheel and positive-speed direction.
For forward/backward direction, observe whether the wheel would propel the
bot toward its front or rear, not clockwise/counterclockwise viewed from outside.

After each stop, enter three initials: front/rear (`f`/`r`), left/right (`l`/`r`),
forward/backward (`f`/`b`). For example, `flb` means front-left backward, and `rrf`
means rear-right forward. Invalid codes are requested again without restarting
motion. The script prints the observations on exit; it does not modify settings.
Full-speed testing requires an explicit `--speed 100`; the default remains 10%.
The old `--duration` option is no longer used. Ctrl+C, EOF, or any
command failure aborts testing, zeros every configured wheel best-effort, sends
stop, and unregisters. Heartbeat runs independently even while waiting at prompts.
If the session fails while waiting for Enter, its worker performs cleanup without
waiting for terminal input; press Enter to let the terminal report the failure.
An ACK confirms queuing, not physical stopping; use the cutoff if needed.

## Offline Tests

From the repository root on Linux:

```bash
uv sync --project python_example/mecanum_control --locked
source python_example/mecanum_control/.venv/bin/activate
QT_QPA_PLATFORM=offscreen SDL_VIDEODRIVER=dummy uv run --project python_example/mecanum_control --locked pytest python_example/mecanum_control/tests -q
```

Windows PowerShell:

```powershell
uv sync --project python_example/mecanum_control --locked
.\python_example\mecanum_control\.venv\Scripts\Activate.ps1
$env:QT_QPA_PLATFORM='offscreen'
$env:SDL_VIDEODRIVER='dummy'
uv run --project python_example/mecanum_control --locked pytest python_example/mecanum_control/tests -q
```

The dev dependency group is included by default. Tests use mocks and loopback,
never a live bot: mixer normalization, simultaneous movement/rotation, button
edges, controller removal, settings, registration/reply validation, timeouts,
cleanup, MJPEG streaming, camera stalls, and desktop video resizing.
Physical wheel direction, neutral, Windows operation, and WiFi-loss stopping
still require explicitly authorized hardware validation.