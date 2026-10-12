"""Validated, nonsecret desktop settings."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "192.168.4.1"
    udp_port: int = 24642
    http_port: int = 80
    channels: tuple[int, ...] = (0, 1, 2, 3)
    inverted: tuple[bool, ...] = (False, True, False, True)
    speed_limit: int = 30
    deadzone: float = 0.12
    rotation_gain: float = 1.0
    axes: tuple[int, ...] = (2, 3, 0)
    buttons: tuple[int, ...] = (0, 1, 2, 3)

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip() or any(char.isspace() for char in self.host):
            raise ValueError("Enter a bot IP address or hostname without spaces")
        for port in (self.udp_port, self.http_port):
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("Ports must be integers in 1..65535")
        if len(self.channels) != 4 or len(set(self.channels)) != 4 or any(type(channel) is not int or not 0 <= channel < 6 for channel in self.channels):
            raise ValueError("Choose four distinct servo channels S1..S6")
        if len(self.inverted) != 4 or any(type(value) is not bool for value in self.inverted):
            raise ValueError("Four wheel direction switches are required")
        if type(self.speed_limit) is not int or not 0 <= self.speed_limit <= 100:
            raise ValueError("Speed limit must be 0..100 percent")
        if not math.isfinite(self.deadzone) or not 0 <= self.deadzone < 1:
            raise ValueError("Deadzone must be in 0..<1")
        if not math.isfinite(self.rotation_gain) or not 0 <= self.rotation_gain <= 2:
            raise ValueError("Rotation sensitivity must be 0..2")
        for mapping, length in ((self.axes, 3), (self.buttons, 4)):
            if len(mapping) != length or len(set(mapping)) != length or any(type(value) is not int or not 0 <= value < 32 for value in mapping):
                raise ValueError("Controller indices must be distinct integers in 0..31")


def default_path() -> Path:
    root = Path(os.environ.get("APPDATA", str(Path.home() / ".config")))
    return root / "k10-mecanum-bot" / "settings.json"


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("channels", "inverted", "axes", "buttons"):
        if key in data:
            data[key] = tuple(data[key])
    return Settings(**data)


def save_settings(path: Path, settings: Settings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)