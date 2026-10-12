"""Only verified K10 binary commands; no sensor subscriptions."""

from __future__ import annotations

import struct

REGISTER = 0x41
UNREGISTER = 0x42
HEARTBEAT = 0x43
PING = 0x44
SET_TYPE = 0x22
SET_SPEED = 0x23
STOP = 0x28
LED = 0x51
SOUND_PLAY = 0xB1
FACE_COLORS = ((0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0))
SOUND_NAME_MAX = 48


def ping(request_id: int) -> bytes:
    if type(request_id) is not int or not 0 <= request_id <= 0xFFFFFFFF:
        raise ValueError("PING ID must be an unsigned 32-bit integer")
    return bytes([PING]) + struct.pack(">I", request_id)


def register(token: str) -> bytes:
    encoded = token.encode("ascii")
    if len(encoded) != 5 or any(char not in "0123456789ABCDEF" for char in token):
        raise ValueError("Enter the five-character uppercase hex token from the bot screen")
    return bytes([REGISTER]) + encoded


def servo_type(mask: int) -> bytes:
    if type(mask) is not int or not 1 <= mask <= 0x3F:
        raise ValueError("Invalid servo mask")
    return bytes([SET_TYPE, mask, 2])


def servo_speed(channel: int, speed: int) -> bytes:
    if type(channel) is not int or not 0 <= channel < 6:
        raise ValueError("Invalid servo channel")
    if type(speed) is not int or not -100 <= speed <= 100:
        raise ValueError("Invalid servo speed")
    return bytes([SET_SPEED, 1 << channel]) + struct.pack("b", speed)


def led_color(color: tuple[int, int, int]) -> bytes:
    if len(color) != 3 or any(type(value) is not int or not 0 <= value <= 255 for value in color):
        raise ValueError("Invalid RGB color")
    return bytes([LED, 0x1F, *color, 255])


def sound_play(name: str) -> bytes:
    if (not isinstance(name, str) or not name.isascii() or not name.endswith(".wav")
            or len(name) > SOUND_NAME_MAX or "/" in name or "\\" in name or ".." in name
            or not name.isprintable()):
        raise ValueError("Sound must be a stored ASCII .wav filename of at most 48 bytes")
    return bytes([SOUND_PLAY]) + name.encode("ascii")


def decode_reply(frame: bytes) -> tuple[int, int | None, bytes]:
    if len(frame) < 9:
        raise ValueError("Missing UDP diagnostics trailer")
    body = frame[:-8]
    action = body[0]
    if action == PING:
        if len(body) != 5:
            raise ValueError("Malformed PING reply")
        return action, None, body[1:]
    if len(body) < 2:
        raise ValueError("Missing response status")
    if action in (REGISTER, UNREGISTER, SET_TYPE, SET_SPEED, STOP, LED, SOUND_PLAY) and len(body) != 2:
        raise ValueError("Malformed acknowledgment")
    if action == HEARTBEAT:
        raise ValueError("Heartbeat must not have a reply")
    return action, body[1], body[2:]