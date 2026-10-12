"""Identify continuous wheel servos one at a time with the wheels lifted."""

from __future__ import annotations

import argparse
import getpass
import time
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from . import protocol
from .config import default_path, load_settings
from .udp_client import BotSession


class IdentificationSession(BotSession):
    auto_reconnect = False

    def run_until_enter(self, channel: int, speed: int) -> None:
        """Run one configured servo until Enter, with independent heartbeat and cleanup."""
        frame = protocol.servo_speed(channel, speed)
        if channel not in self.settings.channels:
            raise ValueError("Servo is not configured in this session")
        if not 1 <= abs(speed) <= 100:
            raise ValueError("Use speed 1..100 percent")
        if not self.ready or not self.paused or not self.alive():
            raise RuntimeError("Identification requires a ready, paused session")
        try:
            self._request(frame)
            input(f"S{channel + 1} running at {speed:+d}%. Press Enter to stop: ")
            if not self.ready or self._shutdown.is_set() or self._heartbeat_failed.is_set():
                raise RuntimeError("Identification session interrupted")
            self._request(protocol.servo_speed(channel, 0))
        except BaseException:
            self.close()
            raise


def read_observation() -> str:
    """Read front/rear, left/right, forward/backward as three initials."""
    while True:
        code = input("Wheel code (front/rear, left/right, forward/backward; e.g. flb): ").strip().lower()
        if len(code) == 3 and code[0] in "fr" and code[1] in "lr" and code[2] in "fb":
            return code
        print("Use flf, flb, frf, frb, rlf, rlb, rrf, or rrb.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_path())
    parser.add_argument("--host", help="Override the saved bot address")
    parser.add_argument("--port", type=int, help="Override the saved UDP port")
    parser.add_argument("--speed", type=int, default=10, help="Positive pulse speed, 1..100 percent")
    args = parser.parse_args(argv)
    if not 1 <= args.speed <= 100:
        parser.error("Use speed 1..100 percent")
    try:
        settings = load_settings(args.config)
        settings = replace(settings, host=args.host or settings.host,
                           udp_port=args.port if args.port is not None else settings.udp_port)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    session = IdentificationSession(settings)
    observations: list[tuple[int, str]] = []
    try:
        print("Disconnect the driving app. Lift ALL wheels clear and keep a power cutoff accessible.")
        print("Network cleanup cannot guarantee a physical stop. Ctrl+C aborts the sequence.")
        print(f"Bot: {settings.host}:{settings.udp_port}; speed: +{args.speed}% until Enter.")
        print("No automatic time limit. Tests ignore saved wheel reversals. No settings will be changed.")
        input("Press Enter when all wheels are lifted clear and you are ready: ")
        session.start(getpass.getpass("Master token from the bot screen (hidden): ").strip())
        deadline = time.monotonic() + 8
        while not session.ready:
            if not session.alive() or time.monotonic() >= deadline:
                raise RuntimeError(f"Could not initialize identification: {session.status}")
            session._shutdown.wait(0.01)
        for channel in sorted(settings.channels):
            connector = f"S{channel + 1}"
            input(f"Press Enter to run only {connector}, or Ctrl+C to finish: ")
            session.run_until_enter(channel, args.speed)
            print(f"{connector} stopped (zero-speed ACK received).")
            observation = read_observation()
            observations.append((channel, observation))
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nIdentification interrupted; stopping configured wheels.")
        return 130
    except (OSError, ValueError, RuntimeError) as error:
        print(f"Identification aborted: {error}")
        return 1
    finally:
        session.close()
        session.join(5)
        if session.alive() or session.status.startswith("Fault:"):
            print(f"Cleanup not fully confirmed: {session.status}. Use the physical cutoff if needed.")
        for channel, observation in observations:
            print(f"S{channel + 1}: {observation}")


if __name__ == "__main__":
    raise SystemExit(main())