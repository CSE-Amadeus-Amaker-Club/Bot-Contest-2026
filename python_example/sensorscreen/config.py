"""Configuration loading for the sensorscreen app: ini file + CLI overrides."""

from __future__ import annotations

import argparse
import configparser
from dataclasses import dataclass
from pathlib import Path

from protocol import (
    DEFAULT_PORT,
    SERVO_COUNT,
    SERVO_TYPE_180,
    SERVO_TYPE_270,
    SERVO_TYPE_CONTINUOUS,
)

DEFAULT_CONF_NAME = "sensorscreen.conf"
SERVO_TYPE_NAMES = {
    "angle180": SERVO_TYPE_180,
    "angle270": SERVO_TYPE_270,
    "continuous": SERVO_TYPE_CONTINUOUS,
}


@dataclass
class BotConfig:
    ip: str
    port: int = DEFAULT_PORT
    token: str = "00000"
    timeout: float = 2.0
    lidar_hz: int = 10
    geomag_hz: int = 10
    imu_hz: int = 10
    huskylens_hz: int = 10
    imu_bump_threshold_mg: int = 50
    imu_bump_debounce_ms: int = 200
    capture_path: Path | None = None
    servo_types: tuple[int, ...] = (SERVO_TYPE_180,) * SERVO_COUNT
    servo_angle_limits: tuple[tuple[int, int] | None, ...] = (None,) * SERVO_COUNT


def _load_ini(path: Path) -> tuple[dict, dict]:
    parser = configparser.ConfigParser()
    parser.read(path)
    bot_section = parser["bot"] if parser.has_section("bot") else parser[parser.default_section]
    servo_section = parser["servos"] if parser.has_section("servos") else {}
    return dict(bot_section), dict(servo_section)


def load_config(argv: list[str] | None = None) -> BotConfig:
    parser = argparse.ArgumentParser(description="K10 Bot SensorsScreen UDP replica")
    parser.add_argument("--config", type=Path, default=Path(__file__).parent / DEFAULT_CONF_NAME,
                         help="Path to ini config file (default: sensorscreen.conf next to this script)")
    parser.add_argument("--ip", help="Bot IP address")
    parser.add_argument("--port", type=int, help="Bot UDP port")
    parser.add_argument("--token", help="5-character master token shown on the device screen")
    parser.add_argument("--timeout", type=float, help="Socket timeout in seconds")
    parser.add_argument("--lidar-hz", type=int, help="Lidar stream rate (Hz)")
    parser.add_argument("--geomag-hz", type=int, help="Geomag stream rate (Hz)")
    parser.add_argument("--imu-hz", type=int, help="IMU stream rate (Hz)")
    parser.add_argument("--huskylens-hz", type=int, help="HuskyLens stream rate (Hz)")
    parser.add_argument("--imu-bump-threshold-mg", type=int, help="IMU bump threshold (mg)")
    parser.add_argument("--imu-bump-debounce-ms", type=int, help="IMU bump debounce time (ms)")
    parser.add_argument("--capture", type=Path, help="Append raw LIDAR frames to this JSONL file")
    args = parser.parse_args(argv)

    ini_values: dict = {}
    servo_values: dict = {}
    if args.config.exists():
        ini_values, servo_values = _load_ini(args.config)

    def pick(cli_value, ini_key: str, default, cast: type = str):
        if cli_value is not None:
            return cli_value
        if ini_key in ini_values:
            return cast(ini_values[ini_key])
        return default

    ip = pick(args.ip, "bot_ip", None)
    if not ip:
        parser.error("Bot IP is required: pass --ip or set bot_ip in the config file")

    servo_types: list[int] = []
    servo_angle_limits: list[tuple[int, int] | None] = []
    for channel in range(SERVO_COUNT):
        name = servo_values.get(f"s{channel + 1}_type", "angle180").strip().lower()
        if name not in SERVO_TYPE_NAMES:
            choices = ", ".join(SERVO_TYPE_NAMES)
            parser.error(f"servos.s{channel + 1}_type must be one of: {choices}")
        servo_type = SERVO_TYPE_NAMES[name]
        servo_types.append(servo_type)

        min_key = f"s{channel + 1}_min_angle"
        max_key = f"s{channel + 1}_max_angle"
        has_min = min_key in servo_values
        has_max = max_key in servo_values
        if servo_type == SERVO_TYPE_CONTINUOUS:
            if has_min or has_max:
                parser.error(f"servos.s{channel + 1}_min_angle and servos.s{channel + 1}_max_angle are invalid for continuous servos")
            servo_angle_limits.append(None)
            continue

        max_limit = 270 if servo_type == SERVO_TYPE_270 else 180
        try:
            min_angle = int(servo_values[min_key]) if has_min else 0
            max_angle = int(servo_values[max_key]) if has_max else max_limit
        except ValueError:
            parser.error(f"servos.s{channel + 1}_min_angle and servos.s{channel + 1}_max_angle must be integers")
        if min_angle < 0 or min_angle > max_limit:
            parser.error(f"servos.s{channel + 1}_min_angle must be in range 0..{max_limit}")
        if max_angle < 0 or max_angle > max_limit:
            parser.error(f"servos.s{channel + 1}_max_angle must be in range 0..{max_limit}")
        if min_angle > max_angle:
            parser.error(f"servos.s{channel + 1}_min_angle must be <= servos.s{channel + 1}_max_angle")
        servo_angle_limits.append((min_angle, max_angle))

    return BotConfig(
        ip=ip,
        port=pick(args.port, "bot_port", DEFAULT_PORT, int),
        token=pick(args.token, "bot_token", "00000"),
        timeout=pick(args.timeout, "bot_timeout", 2.0, float),
        lidar_hz=pick(args.lidar_hz, "lidar_hz", 10, int),
        geomag_hz=pick(args.geomag_hz, "geomag_hz", 10, int),
        imu_hz=pick(args.imu_hz, "imu_hz", 10, int),
        huskylens_hz=pick(args.huskylens_hz, "huskylens_hz", 10, int),
        imu_bump_threshold_mg=pick(args.imu_bump_threshold_mg, "imu_bump_threshold_mg", 50, int),
        imu_bump_debounce_ms=pick(args.imu_bump_debounce_ms, "imu_bump_debounce_ms", 200, int),
        capture_path=args.capture,
        servo_types=tuple(servo_types),
        servo_angle_limits=tuple(servo_angle_limits),
    )
