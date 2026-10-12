"""Robot-relative X-mecanum mixing from one complete stick snapshot."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Settings

TRANSLATION_ARROWS = ("↑", "↗", "→", "↘", "↓", "↙", "←", "↖")
ROTATION_ARROWS = {1: "⟳", -1: "⟲"}


@dataclass(frozen=True)
class InputSnapshot:
    right_x: float = 0.0
    right_y: float = 0.0
    left_x: float = 0.0
    timestamp: float = 0.0
    connected: bool = False
    focused: bool = False


def normalize(value: float, deadzone: float) -> float:
    if not math.isfinite(value):
        raise ValueError("Controller axis is not finite")
    value = max(-1.0, min(1.0, value))
    if abs(value) <= deadzone:
        return 0.0
    return math.copysign((abs(value) - deadzone) / (1 - deadzone), value)


def mix(snapshot: InputSnapshot, settings: Settings) -> tuple[int, ...]:
    strafe = normalize(snapshot.right_x, settings.deadzone)
    forward = -normalize(snapshot.right_y, settings.deadzone)
    yaw = normalize(snapshot.left_x, settings.deadzone) * settings.rotation_gain
    values = (forward + strafe + yaw, forward - strafe - yaw,
              forward - strafe + yaw, forward + strafe - yaw)
    scale = max(1.0, *(abs(value) for value in values))
    return tuple(round(value / scale * settings.speed_limit * (-1 if inverted else 1))
                 for value, inverted in zip(values, settings.inverted))


def motion_arrows(wheels: tuple[int, ...], inverted: tuple[bool, ...]) -> tuple[str, str]:
    """Return robot-relative translation and rotation arrows for wheel commands."""
    if len(wheels) != 4 or len(inverted) != 4:
        raise ValueError("Four wheel speeds and inversion flags are required")
    front_left, front_right, rear_left, rear_right = (
        speed * (-1 if reverse else 1) for speed, reverse in zip(wheels, inverted)
    )
    forward = (front_left + front_right + rear_left + rear_right) / 4
    strafe = (front_left - front_right - rear_left + rear_right) / 4
    yaw = (front_left - front_right + rear_left - rear_right) / 4
    if forward == 0 and strafe == 0:
        translation = "-"
    else:
        sector = math.floor((math.atan2(strafe, forward) + math.pi / 8) / (math.pi / 4)) % 8
        translation = TRANSLATION_ARROWS[sector]
    rotation = ROTATION_ARROWS[1 if yaw > 0 else -1] if yaw else "-"
    return translation, rotation


def centered(snapshot: InputSnapshot, settings: Settings) -> bool:
    return all(abs(value) <= settings.deadzone for value in
               (snapshot.right_x, snapshot.right_y, snapshot.left_x))