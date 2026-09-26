"""Persist and restore user-facing UI state across sensorscreen sessions."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

import protocol as proto


@dataclass(frozen=True)
class UiState:
    """Subset of UI state that is safe and useful to restore on startup."""

    selected_screen: int | None = None
    huskylens_algorithm_index: int = proto.HUSKYLENS_ALGORITHM_TAG_RECOGNITION
    huskylens_illumination_enabled: bool = False
    huskylens_rgb_light_enabled: bool = False
    huskylens_display_enabled: bool = True
    servo_types: tuple[int, ...] | None = None


class UiStateStore:
    """Loads and saves persistent UI state in an ini-style file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> UiState:
        if not self.path.exists():
            return UiState()

        parser = configparser.ConfigParser()
        parser.read(self.path)

        section = parser["ui"] if parser.has_section("ui") else parser[parser.default_section]

        selected_screen = self._get_int(section, "selected_screen")
        if selected_screen is not None and not 0 <= selected_screen < proto.UI_SCREEN_COUNT:
            selected_screen = None

        algorithm_index = self._get_int(
            section,
            "huskylens_algorithm_index",
            default=proto.HUSKYLENS_ALGORITHM_TAG_RECOGNITION,
        )
        algorithm_index = max(0, min(proto.HUSKYLENS_ALGORITHM_MAX, algorithm_index))

        servo_types = self._get_servo_types(section)

        return UiState(
            selected_screen=selected_screen,
            huskylens_algorithm_index=algorithm_index,
            huskylens_illumination_enabled=self._get_bool(section, "huskylens_illumination_enabled", default=False),
            huskylens_rgb_light_enabled=self._get_bool(section, "huskylens_rgb_light_enabled", default=False),
            huskylens_display_enabled=self._get_bool(section, "huskylens_display_enabled", default=True),
            servo_types=servo_types,
        )

    def save(self, state: UiState) -> None:
        parser = configparser.ConfigParser()
        parser["ui"] = {
            "huskylens_algorithm_index": str(max(0, min(proto.HUSKYLENS_ALGORITHM_MAX, state.huskylens_algorithm_index))),
            "huskylens_illumination_enabled": "1" if state.huskylens_illumination_enabled else "0",
            "huskylens_rgb_light_enabled": "1" if state.huskylens_rgb_light_enabled else "0",
            "huskylens_display_enabled": "1" if state.huskylens_display_enabled else "0",
        }

        if state.selected_screen is not None and 0 <= state.selected_screen < proto.UI_SCREEN_COUNT:
            parser["ui"]["selected_screen"] = str(state.selected_screen)

        if state.servo_types is not None and len(state.servo_types) == proto.SERVO_COUNT:
            for index, servo_type in enumerate(state.servo_types):
                if servo_type in (proto.SERVO_TYPE_180, proto.SERVO_TYPE_270, proto.SERVO_TYPE_CONTINUOUS):
                    parser["ui"][f"s{index + 1}_type"] = str(servo_type)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            parser.write(handle)

    @staticmethod
    def _get_int(section: configparser.SectionProxy, key: str, default: int | None = None) -> int | None:
        raw = section.get(key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    def _get_bool(section: configparser.SectionProxy, key: str, default: bool) -> bool:
        raw = section.get(key)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_servo_types(section: configparser.SectionProxy) -> tuple[int, ...] | None:
        servo_types: list[int] = []
        for channel in range(proto.SERVO_COUNT):
            raw = section.get(f"s{channel + 1}_type")
            if raw is None:
                return None
            try:
                value = int(raw)
            except ValueError:
                return None
            if value not in (proto.SERVO_TYPE_180, proto.SERVO_TYPE_270, proto.SERVO_TYPE_CONTINUOUS):
                return None
            servo_types.append(value)
        return tuple(servo_types)