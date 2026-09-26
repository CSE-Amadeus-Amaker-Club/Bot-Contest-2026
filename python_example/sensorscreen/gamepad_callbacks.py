"""Built-in callback helpers for config-driven gamepad mappings."""

from __future__ import annotations

import protocol as proto


def set_speed(*, servonumber: int, speedvalue: int, context) -> None:
    """Set a continuous-servo speed from a mapped gamepad value."""
    speed = max(proto.SERVO_SPEED_MIN, min(proto.SERVO_SPEED_MAX, int(speedvalue)))
    context.client.queue_set_servo_speed(servonumber, speed)
    context.servo_controls.set_external_value(servonumber, speed)


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
    angle = round(lo + (hi - lo) * ratio)
    context.client.queue_set_servo_angle(servonumber, angle)
    context.servo_controls.set_external_value(servonumber, angle)


def set_led(*, red: int, green: int, blue: int, brightness: int = 255, buttonvalue: bool, context) -> None:
    """Set all LEDs while a mapped button is pressed, then turn off on release."""
    if buttonvalue:
        context.client.queue_set_led_color(proto.LED_MASK_ALL, red, green, blue, brightness)
    else:
        context.client.queue_set_led_color(proto.LED_MASK_ALL, 0, 0, 0, brightness)


def play(filename: str, context) -> None:
    """Play a sound file when a mapped button is pressed."""
    if not filename:
        return

    context.client.queue_play_sound(filename)
 
    
    