# Example Clients — Agent Guidelines

## Scope
This subtree contains host-side client implementations for the K10 Bot.


## Python Client Overview
- **Entry point:** `python/main.py` — launches the Textual TUI (`K10BotApp`).
- **User customisation:** `python/customize.py` — the only file end-users should edit (hardware, actions, keyboard, joystick mappings).
- **Framework (do not modify):** `python/udp_client/` — UDP networking, controller loop, input handling, TUI widgets.
- **Bot simulator:** `python/bot_simulator/` — local fake bot for offline testing.
- **Tests:** `python/tests/` — run with `tox` or `pytest`.

## Architecture
```
main.py  →  K10BotApp (TUI)  →  Controller (40 ms loop)
                                      │
                                  BotConfig  ←  customize.py
                                      │
                                 UDP packets  →  Bot
```
- `udp_client/control/` owns the controller loop and stick helpers.
- `udp_client/network/` owns UDP send/receive.
- `udp_client/input/` owns gamepad/keyboard input and calibration.
- `udp_client/state/` owns shared app state.
- `udp_client/ui/` owns Textual widgets.

## Coding Conventions
- Python 3.11+; follow existing type-annotation style.
- Keep `udp_client/` framework code free of user-specific logic.
- All bot customisation belongs in `customize.py`; document new helpers there.
- Use `config.py` for infrastructure settings (ports, timing, network), not `customize.py`.
- Naming: `snake_case` for variables/functions, `PascalCase` for classes.

## Build & Run
```bash
cd example-clients/python
bash setup.sh          # first time: creates venv + pip install -e .
source venv/bin/activate
python main.py         # or: k10-bot
```

## Testing
```bash
cd example-clients/python
source venv/bin/activate
tox                    # runs pytest + linting
pytest tests/          # tests only
```

## Hard Guardrails
- Do not edit `udp_client/` when the task only concerns customisation or UI.
- Do not break the `customize.py` public API (`BOT_CONFIG`, `KEYBOARD_ACTIONS`, `JOYSTICK_CONFIG`) — external user guides depend on it.
- Keep `bot_simulator/` in sync if the UDP packet format changes.

## Key References
- Python client README: [python/README.md](python/README.md)
- User guide: [python/USER_GUIDE.md](python/USER_GUIDE.md)
- Root project guidelines: [../AGENTS.md](../AGENTS.md)
- Bot protocol details: [../../docs/user guides/AmakerBotService_protocol.md](../../docs/user%20guides/AmakerBotService_protocol.md)
- UDP message handling: [../../docs/contributor guides/UDPServiceHandlers.md](../../docs/contributor%20guides/UDPServiceHandlers.md)
