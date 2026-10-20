"""Built-in callback helpers for config-driven gamepad mappings."""

from __future__ import annotations

import random

import protocol as proto


def mix_track_speeds(raw_x: float, raw_y: float, deadzone: float = 0.12) -> tuple[int, int]:
    """Mix left-stick forward/turn inputs with a rescaled deadzone and ratio-preserving saturation."""
    def normalize(value: float) -> float:
        value = max(-1.0, min(1.0, value))
        if abs(value) <= deadzone:
            return 0.0
        magnitude = (abs(value) - deadzone) / (1.0 - deadzone)
        return magnitude if value > 0 else -magnitude

    forward = 100 * normalize(raw_y)
    turn = -100 * normalize(raw_x)
    left = forward + turn
    right = forward - turn
    scale = max(1.0, abs(left) / 100, abs(right) / 100)
    return round(left / scale), round(right / scale)


def set_track_drive(*, leftchannel: int, rightchannel: int, context) -> None:
    """Drive two continuous track servos from the complete left-stick snapshot."""
    context.manager.apply_track_drive(
        _validate_servo_channel(leftchannel), _validate_servo_channel(rightchannel), context,
    )


def set_paired_angle(*, side: str, servonumber: int, context) -> None:
    """Set a positional servo from its trigger, with the same-side bumper taking priority."""
    if side not in {"left", "right"}:
        raise ValueError("side must be left or right")
    context.manager.apply_paired_angle(side, _validate_servo_channel(servonumber), context)


def _validate_servo_channel(servonumber: int) -> int:
    channel = int(servonumber)
    if not 0 <= channel < proto.SERVO_COUNT:
        raise ValueError(f"servonumber must be in 0..{proto.SERVO_COUNT - 1}")
    return channel


def _validate_byte(name: str, value: int) -> int:
    converted = int(value)
    if not 0 <= converted <= 255:
        raise ValueError(f"{name} must be in 0..255")
    return converted


def set_speed(*, servonumber: int, speedvalue: int, context) -> None:
    """Set a continuous-servo speed from a mapped gamepad value."""
    channel = _validate_servo_channel(servonumber)
    speed = max(proto.SERVO_SPEED_MIN, min(proto.SERVO_SPEED_MAX, int(speedvalue)))
    context.client.queue_set_servo_speed(channel, speed)
    context.servo_controls.set_external_value(channel, speed)


def set_angle(
    *,
    servonumber: int,
    minvalue: int,
    maxvalue: int,
    triggervalue: float | None = None,
    bumpervalue: bool | float | None = None,
    buttonvalue: bool | None = None,
    context,
) -> None:
    """Set a positional-servo angle using normalized trigger or boolean button values."""
    channel = _validate_servo_channel(servonumber)
    if triggervalue is not None:
        ratio = float(triggervalue)
    elif bumpervalue is not None:
        ratio = 1.0 if bool(bumpervalue) else 0.0
    elif buttonvalue is not None:
        ratio = 1.0 if bool(buttonvalue) else 0.0
    else:
        raise ValueError("set_angle requires triggervalue, bumpervalue, or buttonvalue")

    ratio = min(1.0, max(0.0, ratio))
    lo = int(minvalue)
    hi = int(maxvalue)
    if lo > hi:
        raise ValueError("minvalue must be <= maxvalue")
    if lo < 0 or hi > proto.SERVO_270_ANGLE_MAX:
        raise ValueError(f"angle range must be within 0..{proto.SERVO_270_ANGLE_MAX}")
    angle = round(lo + (hi - lo) * ratio)
    context.client.queue_set_servo_angle(channel, angle)
    context.servo_controls.set_external_value(channel, angle)


def set_led(*, red: int, green: int, blue: int, brightness: int = 255, buttonvalue: bool, context) -> None:
    """Set all LEDs while a mapped button is pressed, then turn off on release."""
    red_value = _validate_byte("red", red)
    green_value = _validate_byte("green", green)
    blue_value = _validate_byte("blue", blue)
    brightness_value = _validate_byte("brightness", brightness)
    if buttonvalue:
        context.client.queue_set_led_color(proto.LED_MASK_ALL, red_value, green_value, blue_value, brightness_value)
    else:
        context.client.queue_set_led_color(proto.LED_MASK_ALL, 0, 0, 0, brightness_value)


def play(*, filename: str, buttonvalue: bool | None = None, context) -> None:
    """Play a sound file when a mapped button is pressed."""
    if buttonvalue is False:
        return
    if not filename:
        return

    context.client.queue_play_sound(filename)


def play_random(*, filenames: str, buttonvalue: bool | None = None, context) -> None:
    """Play one randomly chosen sound from a comma-separated list on press."""
    if buttonvalue is False:
        return
    choices = [name.strip() for name in filenames.split(",") if name.strip()]
    if choices:
        context.client.queue_play_sound(random.choice(choices))
 
    
    