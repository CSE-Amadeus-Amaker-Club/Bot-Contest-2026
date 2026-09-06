"""Wire protocol constants and pack/unpack helpers for the K10 Bot UDP protocol.

Mirrors the firmware constants in include/BotCommunication/BotMessageHandler.h
and include/services/{Lidar,Geomag,Imu,Huskylens}Service.h. All multi-byte
integers are little-endian, EXCEPT the IMU stream-enable hz field which the
firmware encodes big-endian (see ImuService.cpp) — that quirk is preserved here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

DEFAULT_PORT = 24642

# BotProto response codes (byte[1] of most replies)
RESP_OK = 0x00
RESP_INVALID_PARAMS = 0x01
RESP_INVALID_VALUES = 0x02
RESP_OPERATION_FAILED = 0x03
RESP_NOT_STARTED = 0x04
RESP_UNKNOWN_SERVICE = 0x05
RESP_UNKNOWN_CMD = 0x06
RESP_NOT_MASTER = 0x07

RESP_NAMES = {
    RESP_OK: "resp_ok",
    RESP_INVALID_PARAMS: "resp_invalid_params",
    RESP_INVALID_VALUES: "resp_invalid_values",
    RESP_OPERATION_FAILED: "resp_operation_failed",
    RESP_NOT_STARTED: "resp_not_started",
    RESP_UNKNOWN_SERVICE: "resp_unknown_service",
    RESP_UNKNOWN_CMD: "resp_unknown_cmd",
    RESP_NOT_MASTER: "resp_not_master",
}

# AmakerBotService (0x04)
SERVICE_AMAKER = 0x04
CMD_MASTER_REGISTER = 0x01
CMD_MASTER_UNREGISTER = 0x02
CMD_HEARTBEAT = 0x03
CMD_PING = 0x04

# AmakerBotUIService (0x06)
SERVICE_UI = 0x06
UI_CMD_NEXT_SCREEN = 0x01
UI_CMD_PREV_SCREEN = 0x02
UI_CMD_SET_SCREEN = 0x03
UI_SCREEN_SPLASH = 0
UI_SCREEN_APP_INFO = 1
UI_SCREEN_SENSORS = 2
UI_SCREEN_APP_LOG = 3
UI_SCREEN_SERVICE_LOG = 4
UI_SCREEN_DEBUG_LOG = 5
UI_SCREEN_ESP_LOG = 6
UI_SCREEN_COUNT = 7

# HuskylensService (0x07)
SERVICE_HUSKYLENS = 0x07
HUSKYLENS_CMD_SET_LIGHT = 0x01
HUSKYLENS_CMD_SET_ILLUMINATION = HUSKYLENS_CMD_SET_LIGHT
HUSKYLENS_CMD_SET_STREAM = 0x02
HUSKYLENS_CMD_GET_STREAM = 0x03
HUSKYLENS_CMD_SET_ALGORITHM = 0x04
HUSKYLENS_CMD_GET_ALGORITHM = 0x05
HUSKYLENS_CMD_SET_RGB_LIGHT = 0x06
HUSKYLENS_CMD_SET_DISPLAY = 0x07
HUSKYLENS_CMD_GET_CONTROLS = 0x08
HUSKYLENS_ALGORITHM_FACE_RECOGNITION = 0
HUSKYLENS_ALGORITHM_OBJECT_TRACKING = 1
HUSKYLENS_ALGORITHM_OBJECT_RECOGNITION = 2
HUSKYLENS_ALGORITHM_LINE_TRACKING = 3
HUSKYLENS_ALGORITHM_COLOR_RECOGNITION = 4
HUSKYLENS_ALGORITHM_TAG_RECOGNITION = 5
HUSKYLENS_ALGORITHM_MAX = HUSKYLENS_ALGORITHM_TAG_RECOGNITION
HUSKYLENS_STREAM_FRAME_CMD = 0x0F
HUSKYLENS_LENS_WIDTH = 320
HUSKYLENS_LENS_HEIGHT = 240
HUSKYLENS_MAX_BLOCKS = 8
HUSKYLENS_MAX_ARROWS = 8

# GeomagService (0x09)
SERVICE_GEOMAG = 0x09
GEOMAG_CMD_SET_STREAM = 0x03
GEOMAG_CMD_GET_STREAM = 0x04
GEOMAG_STREAM_FRAME_CMD = 0x0F

# LidarService (0x08)
SERVICE_LIDAR = 0x08
LIDAR_CMD_SET_STREAM = 0x03
LIDAR_CMD_SET_STREAM_INTENSITY = 0x09
LIDAR_STREAM_FRAME_CMD = 0x0F
LIDAR_STREAM_INTENSITY_FRAME_CMD = 0x0E
LIDAR_SCAN_ROWS = 8
LIDAR_SCAN_COLS = 64
LIDAR_SCAN_POINTS = LIDAR_SCAN_ROWS * LIDAR_SCAN_COLS

# ImuService (0x0A)
SERVICE_IMU = 0x0A
IMU_CMD_SET_STREAM = 0x02
IMU_CMD_SET_BUMP_CONFIG = 0x07
IMU_CMD_GET_BUMP_CONFIG = 0x08
IMU_STREAM_FRAME_CMD = 0x0F
IMU_BUMP_EVENT_CMD = 0x10

# Matches firmware IMU shock direction byte: 0..5 == X-/X+/Y-/Y+/Z-/Z+
IMU_BUMP_DIR_LABELS = {
    0: "X-",
    1: "X+",
    2: "Y-",
    3: "Y+",
    4: "Z-",
    5: "Z+",
}


def bump_dir_label(code: int) -> str:
    return IMU_BUMP_DIR_LABELS.get(code, f"?{code}")

# MotorServoService (0x02)
SERVICE_MOTOR_SERVO = 0x02
MOTOR_SERVO_CMD_SET_SERVO_TYPE = 0x02
MOTOR_SERVO_CMD_SET_SERVOS_SPEED = 0x03
MOTOR_SERVO_CMD_SET_SERVOS_ANGLE = 0x04
MOTOR_SERVO_CMD_STOP_ALL_MOTORS = 0x08
SERVO_COUNT = 6
SERVO_MASK_ALL = (1 << SERVO_COUNT) - 1
SERVO_TYPE_180 = 0
SERVO_TYPE_270 = 1
SERVO_TYPE_CONTINUOUS = 2
SERVO_SPEED_MIN = -100
SERVO_SPEED_MAX = 100
SERVO_180_ANGLE_MAX = 180
SERVO_270_ANGLE_MAX = 270

# LEDService (0x05)
SERVICE_LED = 0x05
LED_CMD_SET_COLOR = 0x01
LED_MASK_ALL = 0x1F


def make_action(service_id: int, cmd_id: int) -> int:
    """Build the single action byte from a service id and command id."""
    return ((service_id & 0x0F) << 4) | (cmd_id & 0x0F)


def action_service(action: int) -> int:
    return (action >> 4) & 0x0F


def action_cmd(action: int) -> int:
    return action & 0x0F


# ─── Request builders ──────────────────────────────────────────────────────

def build_master_register(token: str) -> bytes:
    return bytes([make_action(SERVICE_AMAKER, CMD_MASTER_REGISTER)]) + token.encode("ascii")


def build_master_unregister() -> bytes:
    return bytes([make_action(SERVICE_AMAKER, CMD_MASTER_UNREGISTER)])


def build_heartbeat() -> bytes:
    return bytes([make_action(SERVICE_AMAKER, CMD_HEARTBEAT)])


def build_ui_set_screen(screen: int) -> bytes:
    """Build [0x63][screen] to select a K10 UI screen by its firmware index."""
    if not 0 <= screen < UI_SCREEN_COUNT:
        raise ValueError(f"screen must be in 0..{UI_SCREEN_COUNT - 1}")
    return bytes([make_action(SERVICE_UI, UI_CMD_SET_SCREEN), screen])


def build_lidar_set_stream(enabled: bool, hz: int) -> bytes:
    return bytes([make_action(SERVICE_LIDAR, LIDAR_CMD_SET_STREAM), 1 if enabled else 0, hz, 0])


def build_lidar_set_stream_intensity(enabled: bool, hz: int) -> bytes:
    return bytes([make_action(SERVICE_LIDAR, LIDAR_CMD_SET_STREAM_INTENSITY), 1 if enabled else 0, hz, 0])


def build_geomag_set_stream(enabled: bool, hz: int) -> bytes:
    return bytes([make_action(SERVICE_GEOMAG, GEOMAG_CMD_SET_STREAM), 1 if enabled else 0, hz])


def build_imu_set_stream(enabled: bool, hz: int) -> bytes:
    # Firmware reads hz as big-endian u16 here, unlike every other service.
    return bytes([make_action(SERVICE_IMU, IMU_CMD_SET_STREAM), 1 if enabled else 0]) + struct.pack(">H", hz)


def build_imu_set_bump_config(threshold_mg: int, debounce_ms: int) -> bytes:
    # Firmware reads both fields as big-endian u16 here (see ImuService.cpp cmd_set_bump_config).
    return bytes([make_action(SERVICE_IMU, IMU_CMD_SET_BUMP_CONFIG)]) + struct.pack(">HH", threshold_mg, debounce_ms)


def build_huskylens_set_stream(enabled: bool, hz: int) -> bytes:
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_SET_STREAM), 1 if enabled else 0, hz])


def build_huskylens_set_illumination(enabled: bool) -> bytes:
    """Build the HuskyLens illumination setter; this does not power off its LCD."""
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_SET_ILLUMINATION), 1 if enabled else 0])


def build_huskylens_set_algorithm(algorithm: int) -> bytes:
    if not 0 <= algorithm <= HUSKYLENS_ALGORITHM_MAX:
        raise ValueError(f"invalid HuskyLens algorithm: {algorithm}")
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_SET_ALGORITHM), algorithm])


def build_huskylens_get_algorithm() -> bytes:
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_GET_ALGORITHM)])


def build_huskylens_set_rgb_light(enabled: bool) -> bytes:
    """Build the HuskyLens RGB/status-light setter; V1 firmware may report unsupported."""
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_SET_RGB_LIGHT), 1 if enabled else 0])


def build_huskylens_set_display(enabled: bool) -> bytes:
    """Build the HuskyLens LCD/display setter; V1 firmware may report unsupported."""
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_SET_DISPLAY), 1 if enabled else 0])


def build_huskylens_get_controls() -> bytes:
    return bytes([make_action(SERVICE_HUSKYLENS, HUSKYLENS_CMD_GET_CONTROLS)])


def _validate_servo_mask(servo_mask: int) -> None:
    if not 0 < servo_mask <= SERVO_MASK_ALL:
        raise ValueError(f"servo_mask must select channels 0-{SERVO_COUNT - 1}")


def build_set_servo_type(servo_mask: int, servo_type: int) -> bytes:
    """Build [0x22][servo_mask][type] for 180, 270, or continuous servos."""
    _validate_servo_mask(servo_mask)
    if servo_type not in (SERVO_TYPE_180, SERVO_TYPE_270, SERVO_TYPE_CONTINUOUS):
        raise ValueError("servo_type must be 0 (180), 1 (270), or 2 (continuous)")
    return bytes([make_action(SERVICE_MOTOR_SERVO, MOTOR_SERVO_CMD_SET_SERVO_TYPE), servo_mask, servo_type])


def build_set_servos_speed(servo_mask: int, speed: int) -> bytes:
    """Build [0x23][servo_mask][speed:i8] for continuous servos."""
    _validate_servo_mask(servo_mask)
    if not SERVO_SPEED_MIN <= speed <= SERVO_SPEED_MAX:
        raise ValueError(f"speed must be in {SERVO_SPEED_MIN}..{SERVO_SPEED_MAX}")
    return bytes([make_action(SERVICE_MOTOR_SERVO, MOTOR_SERVO_CMD_SET_SERVOS_SPEED), servo_mask]) + struct.pack("b", speed)


def build_set_servos_angle(servo_mask: int, angle: int) -> bytes:
    """Build [0x24][servo_mask][angle:i16BE] for positional servos."""
    _validate_servo_mask(servo_mask)
    if not 0 <= angle <= SERVO_270_ANGLE_MAX:
        raise ValueError(f"angle must be in 0..{SERVO_270_ANGLE_MAX}")
    return bytes([make_action(SERVICE_MOTOR_SERVO, MOTOR_SERVO_CMD_SET_SERVOS_ANGLE), servo_mask]) + struct.pack(">h", angle)


def build_stop_all_motors() -> bytes:
    """Build [0x28], which stops DC motors and continuous servo channels."""
    return bytes([make_action(SERVICE_MOTOR_SERVO, MOTOR_SERVO_CMD_STOP_ALL_MOTORS)])


def build_set_led_color(led_mask: int, red: int, green: int, blue: int, brightness: int) -> bytes:
    """Build [0x51][led_mask][red][green][blue][brightness] for selected LEDs."""
    if not 0 < led_mask <= LED_MASK_ALL:
        raise ValueError("led_mask must select LEDs 0-4")
    if not all(0 <= value <= 255 for value in (red, green, blue, brightness)):
        raise ValueError("red, green, blue, and brightness must be in 0..255")
    return bytes([make_action(SERVICE_LED, LED_CMD_SET_COLOR), led_mask, red, green, blue, brightness])


# ─── Streamed frame parsing ────────────────────────────────────────────────

@dataclass
class LidarFrame:
    frame_id: int
    timestamp_ms: int
    values: list[int] = field(default_factory=list)  # row-major, len == point_count


def parse_lidar_frame(frame: bytes) -> LidarFrame | None:
    """[action][status][frame_id:u16LE][timestamp:u32LE][point_count:u16LE][...u16LE values]"""
    if len(frame) < 10:
        return None
    frame_id, timestamp_ms, point_count = struct.unpack_from("<HIH", frame, 2)
    expected_len = 10 + point_count * 2
    if len(frame) < expected_len:
        return None
    values = list(struct.unpack_from(f"<{point_count}H", frame, 10))
    return LidarFrame(frame_id=frame_id, timestamp_ms=timestamp_ms, values=values)


@dataclass
class GeomagFrame:
    frame_id: int
    heading_deg: int
    field_x_ut: int
    field_y_ut: int
    field_z_ut: int


def parse_geomag_frame(frame: bytes) -> GeomagFrame | None:
    """[action][status][frame_id:u16LE][heading:u16LE][x,y,z:int16LE]"""
    if len(frame) < 12:
        return None
    frame_id, heading, x, y, z = struct.unpack_from("<HHhhh", frame, 2)
    return GeomagFrame(frame_id=frame_id, heading_deg=heading, field_x_ut=x, field_y_ut=y, field_z_ut=z)


@dataclass
class ImuFrame:
    sample_id: int
    accel_x_mg: int
    accel_y_mg: int
    accel_z_mg: int


def parse_imu_frame(frame: bytes) -> ImuFrame | None:
    """[action][status][sample_id:u32LE][x,y,z:int16LE]"""
    if len(frame) < 12:
        return None
    sample_id, x, y, z = struct.unpack_from("<Ihhh", frame, 2)
    return ImuFrame(sample_id=sample_id, accel_x_mg=x, accel_y_mg=y, accel_z_mg=z)


@dataclass
class ImuBumpEvent:
    sample_id: int
    bump_dir: int
    accel_x_mg: int
    accel_y_mg: int
    accel_z_mg: int


def parse_imu_bump_event(frame: bytes) -> ImuBumpEvent | None:
    """[action][status][sample_id:u32LE][bump_dir:u8][x,y,z:int16LE]"""
    if len(frame) < 13:
        return None
    sample_id, bump_dir, x, y, z = struct.unpack_from("<IBhhh", frame, 2)
    return ImuBumpEvent(sample_id=sample_id, bump_dir=bump_dir, accel_x_mg=x, accel_y_mg=y, accel_z_mg=z)


@dataclass
class ImuBumpConfig:
    threshold_mg: int
    debounce_ms: int


def parse_imu_bump_config(frame: bytes) -> ImuBumpConfig | None:
    """[action][status][threshold_mg:u16LE][debounce_ms:u16LE] (get_bump_config reply)"""
    if len(frame) < 6:
        return None
    threshold_mg, debounce_ms = struct.unpack_from("<HH", frame, 2)
    return ImuBumpConfig(threshold_mg=threshold_mg, debounce_ms=debounce_ms)


@dataclass
class HuskylensBlock:
    x_center: int
    y_center: int
    width: int
    height: int
    id: int
    confidence: int


@dataclass
class HuskylensArrow:
    x_origin: int
    y_origin: int
    x_target: int
    y_target: int
    id: int
    confidence: int


@dataclass
class HuskylensFrame:
    connected: bool
    frame_number: int
    width: int
    height: int
    blocks: list[HuskylensBlock] = field(default_factory=list)
    arrows: list[HuskylensArrow] = field(default_factory=list)


def parse_huskylens_frame(frame: bytes) -> HuskylensFrame | None:
    """[action][status][frame:u16LE][w:u16LE][h:u16LE][block_count][arrow_count]
    then block_count * [x,y,w,h:u16LE][id,conf:u8] then arrow_count * [x0,y0,x1,y1:u16LE][id,conf:u8]
    """
    if len(frame) < 10:
        return None
    frame_number, width, height, block_count, arrow_count = struct.unpack_from("<HHHBB", frame, 2)
    offset = 10
    blocks: list[HuskylensBlock] = []
    for _ in range(block_count):
        if offset + 10 > len(frame):
            return None
        x, y, w, h, bid, conf = struct.unpack_from("<HHHHBB", frame, offset)
        blocks.append(HuskylensBlock(x, y, w, h, bid, conf))
        offset += 10
    arrows: list[HuskylensArrow] = []
    for _ in range(arrow_count):
        if offset + 10 > len(frame):
            return None
        x0, y0, x1, y1, aid, conf = struct.unpack_from("<HHHHBB", frame, offset)
        arrows.append(HuskylensArrow(x0, y0, x1, y1, aid, conf))
        offset += 10
    return HuskylensFrame(
        connected=frame[1] == 0x00,
        frame_number=frame_number,
        width=width,
        height=height,
        blocks=blocks,
        arrows=arrows,
    )
