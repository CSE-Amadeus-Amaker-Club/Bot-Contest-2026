# SensorsScreen Python Client — Agent Guidelines

## Scope
This subtree contains the host-side SensorsScreen client at
`python_example/sensorscreen/`. There is no separate `example-clients/python/`
tree, bundled simulator, or setup script in this repository.

Sound clients: follow [the sound tutorial](../ai-udp-client.md#sound-convert-store-and-play)
for SoX 8-bit mono 11025 Hz PCM conversion, HTTP list/upload/delete, and
Python playback. Sound-only control needs no master; preserve motion safety.


## Client Overview
- **Entry point:** `sensorscreen/main.py`.
- **Configuration:** `sensorscreen/sensorscreen.conf` (start from the example file).
- **Protocol/client:** `sensorscreen/protocol.py` and `sensorscreen/udp_client.py`.
- **Tests:** `sensorscreen/tests/` — run with pytest from the SensorsScreen directory.

## Architecture
```
main.py → SensorsScreen UI → SensorUDPClient → K10 Bot
```
- `udp_client.py` owns UDP communication, registration, and the receive dispatcher.
- Sensor, servo, sound, screen, and gamepad behavior lives in focused modules.

## Coding Conventions
- Python 3.11+; follow existing type-annotation style.
- Keep network and master-registration behavior in `udp_client.py`.
- Preserve the single receive dispatcher and safe shutdown behavior.
- Naming: `snake_case` for variables/functions, `PascalCase` for classes.

## Build & Run
```bash
cd python_example/sensorscreen
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp sensorscreen.conf.example sensorscreen.conf
python main.py
```

## Testing
```bash
cd python_example/sensorscreen
source venv/bin/activate
python -m pytest -q tests/
```

## Hard Guardrails
- Keep protocol builders aligned with the active firmware and protocol reference.
- Keep `sensorscreen.conf.example` aligned with supported configuration keys.

## Key References
- SensorsScreen README: [sensorscreen/README.md](sensorscreen/README.md)
- Root project guidelines: [../AGENTS.md](../AGENTS.md)
- Bot protocol details: [../binary-protocol.md](../binary-protocol.md)
- UDP transport details: [../communication.md](../communication.md)
