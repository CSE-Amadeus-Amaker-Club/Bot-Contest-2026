# SensorsScreen Guidelines

Follow the parent `example-clients/python/AGENTS.md` and the repository root
`AGENTS.md`. This directory contains a host-side Python replica of the K10
SensorsScreen.

## Architecture
- Keep `protocol.py` aligned with the firmware UDP message format and protocol
  documentation.
- Keep network and master-registration behavior in `udp_client.py`; UI modules
  should communicate through the existing client and state abstractions.
- Keep sensor, servo, sound, and HuskyLens controls isolated in their existing
  modules rather than adding device-specific logic to `main.py`.
- Preserve safe shutdown behavior: unregister as master and stop active outputs
  when the window closes or the client exits.

## Configuration and Compatibility
- Do not commit credentials or machine-specific bot addresses from
  `sensorscreen.conf`.
- Keep `sensorscreen.conf.example` updated when configuration keys change.
- Support Python 3.11+ and retain graceful behavior when optional pygame input
  is unavailable.
- Avoid changing UDP timing, packet sizes, or command values without updating
  the corresponding firmware and protocol tests.

## Validation
- From this directory, activate the local virtual environment and run
  `pytest tests/`.
- Prefer focused protocol/control tests for logic changes; use a live K10 only
  for behavior that depends on hardware or the network.