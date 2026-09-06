import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto


def test_make_action():
    assert proto.make_action(0x04, 0x01) == 0x41
    assert proto.make_action(0x08, 0x0F) == 0x8F
    assert proto.make_action(0x07, 0x0F) == 0x7F


def test_response_codes_are_named_consistently():
    assert proto.RESP_NAMES[proto.RESP_OPERATION_FAILED] == "resp_operation_failed"
    assert proto.RESP_NAMES[proto.RESP_NOT_STARTED] == "resp_not_started"
    assert set(proto.RESP_NAMES) == set(range(0x08))


def test_build_master_register():
    assert proto.build_master_register("abc12") == bytes([0x41]) + b"abc12"


def test_build_ui_set_screen():
    for screen in range(proto.UI_SCREEN_COUNT):
        assert proto.build_ui_set_screen(screen) == bytes([0x63, screen])


def test_build_ui_set_screen_rejects_invalid_indexes():
    for screen in (-1, proto.UI_SCREEN_COUNT):
        try:
            proto.build_ui_set_screen(screen)
        except ValueError:
            continue
        raise AssertionError(f"build_ui_set_screen accepted {screen}")


def test_build_imu_set_stream_is_big_endian_hz():
    frame = proto.build_imu_set_stream(True, 0x0102)
    assert frame == bytes([0xA2, 0x01, 0x01, 0x02])


def test_build_lidar_set_stream():
    assert proto.build_lidar_set_stream(True, 10) == bytes([0x83, 0x01, 10, 0x00])


def test_build_huskylens_set_illumination():
    assert proto.build_huskylens_set_illumination(True) == bytes([0x71, 0x01])
    assert proto.build_huskylens_set_illumination(False) == bytes([0x71, 0x00])


def test_build_huskylens_algorithm_commands():
    assert proto.build_huskylens_set_algorithm(proto.HUSKYLENS_ALGORITHM_LINE_TRACKING) == bytes([0x74, 0x03])
    assert proto.build_huskylens_get_algorithm() == bytes([0x75])


def test_build_huskylens_control_commands():
    assert proto.build_huskylens_set_rgb_light(True) == bytes([0x76, 0x01])
    assert proto.build_huskylens_set_rgb_light(False) == bytes([0x76, 0x00])
    assert proto.build_huskylens_set_display(True) == bytes([0x77, 0x01])
    assert proto.build_huskylens_set_display(False) == bytes([0x77, 0x00])
    assert proto.build_huskylens_get_controls() == bytes([0x78])


def test_build_huskylens_set_algorithm_rejects_invalid_values():
    for algorithm in (-1, proto.HUSKYLENS_ALGORITHM_MAX + 1):
        try:
            proto.build_huskylens_set_algorithm(algorithm)
        except ValueError:
            continue
        raise AssertionError(f"build_huskylens_set_algorithm accepted {algorithm}")


def test_build_set_servo_type():
    assert proto.build_set_servo_type(0x04, proto.SERVO_TYPE_270) == bytes([0x22, 0x04, 0x01])


def test_build_set_continuous_servo_speed():
    assert proto.build_set_servos_speed(0x20, -75) == bytes([0x23, 0x20, 0xB5])


def test_build_set_positional_servo_angle_is_big_endian():
    assert proto.build_set_servos_angle(0x01, 270) == bytes([0x24, 0x01, 0x01, 0x0E])


def test_build_servo_commands_reject_invalid_values():
    for builder, args in (
        (proto.build_set_servo_type, (0x40, proto.SERVO_TYPE_180)),
        (proto.build_set_servos_speed, (0x01, 101)),
        (proto.build_set_servos_angle, (0x01, 271)),
    ):
        try:
            builder(*args)
        except ValueError:
            continue
        raise AssertionError(f"{builder.__name__} accepted invalid values")


def test_build_stop_all_motors():
    assert proto.build_stop_all_motors() == bytes([0x28])


def test_build_set_all_leds_color():
    assert proto.build_set_led_color(0x1F, 0, 255, 0, 255) == bytes([0x51, 0x1F, 0, 255, 0, 255])


def test_parse_lidar_frame_roundtrip():
    values = list(range(proto.LIDAR_SCAN_POINTS))
    payload = bytes([0x8F, 0x00]) + struct.pack("<HIH", 42, 12345, len(values)) + struct.pack(f"<{len(values)}H", *values)
    parsed = proto.parse_lidar_frame(payload)
    assert parsed is not None
    assert parsed.frame_id == 42
    assert parsed.timestamp_ms == 12345
    assert parsed.values == values


def test_parse_lidar_frame_rejects_truncated_payload():
    frame = bytes([0x8F, proto.RESP_OPERATION_FAILED]) + struct.pack("<HIH", 42, 12345, 2) + b"\x01\x00"
    assert proto.parse_lidar_frame(frame) is None


def test_parse_geomag_frame_roundtrip():
    payload = bytes([0x9F, 0x00]) + struct.pack("<HHhhh", 7, 180, -10, 20, -30)
    parsed = proto.parse_geomag_frame(payload)
    assert parsed is not None
    assert parsed.heading_deg == 180
    assert (parsed.field_x_ut, parsed.field_y_ut, parsed.field_z_ut) == (-10, 20, -30)


def test_parse_geomag_frame_rejects_truncated_header():
    assert proto.parse_geomag_frame(bytes([0x9F, proto.RESP_OPERATION_FAILED]) + b"\x00" * 9) is None


def test_parse_imu_frame_roundtrip():
    payload = bytes([0xAF, 0x00]) + struct.pack("<Ihhh", 99, 10, -20, 990)
    parsed = proto.parse_imu_frame(payload)
    assert parsed is not None
    assert parsed.sample_id == 99
    assert (parsed.accel_x_mg, parsed.accel_y_mg, parsed.accel_z_mg) == (10, -20, 990)


def test_parse_imu_frame_rejects_truncated_payload():
    assert proto.parse_imu_frame(bytes([0xAF, proto.RESP_OPERATION_FAILED]) + b"\x00" * 9) is None


def test_parse_imu_bump_event_roundtrip():
    payload = bytes([0xA0, 0x00]) + struct.pack("<IBhhh", 42, 2, 10, -20, 990)
    parsed = proto.parse_imu_bump_event(payload)
    assert parsed is not None
    assert parsed.sample_id == 42
    assert parsed.bump_dir == 2
    assert (parsed.accel_x_mg, parsed.accel_y_mg, parsed.accel_z_mg) == (10, -20, 990)


def test_bump_dir_label():
    assert proto.bump_dir_label(0) == "X-"
    assert proto.bump_dir_label(1) == "X+"
    assert proto.bump_dir_label(2) == "Y-"
    assert proto.bump_dir_label(3) == "Y+"
    assert proto.bump_dir_label(4) == "Z-"
    assert proto.bump_dir_label(5) == "Z+"
    assert proto.bump_dir_label(9) == "?9"


def test_parse_huskylens_frame_roundtrip():
    header = bytes([0x7F, 0x00]) + struct.pack("<HHHBB", 3, 320, 240, 1, 1)
    block = struct.pack("<HHHHBB", 100, 120, 40, 40, 5, 90)
    arrow = struct.pack("<HHHHBB", 10, 20, 200, 210, 6, 80)
    parsed = proto.parse_huskylens_frame(header + block + arrow)
    assert parsed is not None
    assert parsed.connected is True
    assert len(parsed.blocks) == 1
    assert parsed.blocks[0].id == 5
    assert len(parsed.arrows) == 1
    assert parsed.arrows[0].id == 6
