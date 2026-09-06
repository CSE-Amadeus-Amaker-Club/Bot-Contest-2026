"""K10 Bot SensorsScreen replica — registers as UDP master and renders live sensor panels."""

from __future__ import annotations

import logging
import sys

import cv2

try:
    import pygame
except ImportError:
    pygame = None

from capture import LidarCapture
from config import load_config
from huskylens_controls import HuskylensLightControl
from render import GRID_GAP, SCREEN_BAND_TOP, SENSOR_GRID_TOP, SERVO_BAND_TOP, SOUND_BAND_TOP, WINDOW_H, WINDOW_W, compose_dashboard
from screen_controls import ScreenControls
from sound_controls import SoundControls
from servo_controls import ServoControls
from state import SensorState
from udp_client import MasterRegistrationError, SensorUDPClient
import protocol as proto

logger = logging.getLogger("sensorscreen")

WINDOW_NAME = "aMaker Bot - SensorsScreen"
TARGET_FPS = 30
JOYSTICK_DEADZONE = 0.12
JOYSTICK_LEFT_Y_AXIS = 1
JOYSTICK_RIGHT_Y_AXIS = 3
JOYSTICK_LEFT_TRIGGER_AXIS = 4
JOYSTICK_RIGHT_TRIGGER_AXIS = 5
JOYSTICK_A_BUTTON = 0
JOYSTICK_B_BUTTON = 1
JOYSTICK_X_BUTTON = 2
JOYSTICK_Y_BUTTON = 3
JOYSTICK_LEFT_BUMPER_BUTTON = 4
JOYSTICK_RIGHT_BUMPER_BUTTON = 5
JOYSTICK_GUIDE_BUTTON = 8
SERVO_1_CHANNEL = 0
SERVO_2_CHANNEL = 1
SERVO_3_CHANNEL = 2
SERVO_4_CHANNEL = 3
SERVO_ANGLE_MIN = 0
LED_MASK_ALL = 0x1F
LED_BRIGHTNESS = 255
RUMBLE_DURATION_MS = 250
FACE_BUTTON_COLORS = {
    JOYSTICK_X_BUTTON: (0, 0, 255),
    JOYSTICK_Y_BUTTON: (255, 255, 0),
    JOYSTICK_A_BUTTON: (0, 255, 0),
    JOYSTICK_B_BUTTON: (255, 0, 0),
}


class _DisplaySize:
    """Tracks the window's current displayed pixel size for mouse coordinate rescaling."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


def _scaled_mouse_callback(servo_controls: ServoControls, huskylens_controls: HuskylensLightControl,
                           screen_controls: ScreenControls, sound_controls: SoundControls, display_size: _DisplaySize):
    def _callback(event: int, x: int, y: int, flags: int, param: object | None = None) -> None:
        scaled_x = round(x * WINDOW_W / display_size.width)
        scaled_y = round(y * WINDOW_H / display_size.height)
        screen_controls.handle_mouse(event, scaled_x, scaled_y)
        sound_controls.handle_mouse(event, scaled_x, scaled_y - SOUND_BAND_TOP)
        servo_controls.handle_mouse(event, scaled_x, scaled_y, flags, param)
        huskylens_controls.handle_mouse(event, scaled_x - GRID_GAP, scaled_y - SENSOR_GRID_TOP - GRID_GAP)

    return _callback


def _open_joystick(device_index: int):
    if pygame is None:
        return None
    try:
        joystick = pygame.joystick.Joystick(device_index)
        joystick.init()
        logger.info("Controller connected: %s", joystick.get_name())
        return joystick
    except pygame.error as exc:
        logger.warning("Unable to open controller %d: %s", device_index, exc)
        return None


def _window_is_visible() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


def _read_button(joystick, button: int) -> bool:
    return button < joystick.get_numbuttons() and bool(joystick.get_button(button))


def _trigger_position(joystick, axis: int) -> float:
    if axis >= joystick.get_numaxes():
        return 0.0
    return min(1.0, max(0.0, (joystick.get_axis(axis) + 1.0) / 2.0))


def _stick_speed(joystick, axis: int) -> int:
    if axis >= joystick.get_numaxes():
        return 0
    speed = -round(joystick.get_axis(axis) * 100)
    return 0 if abs(speed) < round(JOYSTICK_DEADZONE * 100) else speed


def _set_gamepad_safe_positions(client: SensorUDPClient, servo_controls: ServoControls,
                                servo_types: tuple[int, ...]) -> None:
    for channel in (SERVO_1_CHANNEL, SERVO_2_CHANNEL, SERVO_3_CHANNEL, SERVO_4_CHANNEL):
        if servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
            client.queue_set_servo_speed(channel, 0, force=True)
        else:
            client.queue_set_servo_angle(channel, SERVO_ANGLE_MIN, force=True)
        servo_controls.set_external_value(channel, 0)


def _apply_gamepad_controls(client: SensorUDPClient, joystick, servo_types: tuple[int, ...],
                            previous: dict[str, int], servo_controls: ServoControls) -> None:
    if (servo_types[SERVO_1_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
            or servo_types[SERVO_2_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
            or servo_types[SERVO_3_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS
            or servo_types[SERVO_4_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS):
        if not previous.get("joystick_mapping_error"):
            logger.error("Joystick mapping requires continuous servos on channels 0/1 and positional servos on 2/3")
            previous["joystick_mapping_error"] = 1
        return
    previous.pop("joystick_mapping_error", None)
    servo_3_max = 270 if servo_types[SERVO_3_CHANNEL] == 1 else 180
    servo_4_max = 270 if servo_types[SERVO_4_CHANNEL] == 1 else 180
    servo_3_position = max(
        1.0 if _read_button(joystick, JOYSTICK_LEFT_BUMPER_BUTTON) else 0.0,
        _trigger_position(joystick, JOYSTICK_LEFT_TRIGGER_AXIS),
    )
    servo_4_position = max(
        1.0 if _read_button(joystick, JOYSTICK_RIGHT_BUMPER_BUTTON) else 0.0,
        _trigger_position(joystick, JOYSTICK_RIGHT_TRIGGER_AXIS),
    )
    values = {
        "servo_1_speed": _stick_speed(joystick, JOYSTICK_LEFT_Y_AXIS),
        "servo_2_speed": _stick_speed(joystick, JOYSTICK_RIGHT_Y_AXIS),
        "servo_3_angle": round(SERVO_ANGLE_MIN + (servo_3_max - SERVO_ANGLE_MIN) * servo_3_position),
        "servo_4_angle": round(SERVO_ANGLE_MIN + (servo_4_max - SERVO_ANGLE_MIN) * servo_4_position),
    }
    if previous.get("servo_1_speed") != values["servo_1_speed"]:
        client.queue_set_servo_speed(SERVO_1_CHANNEL, values["servo_1_speed"])
    if previous.get("servo_2_speed") != values["servo_2_speed"]:
        client.queue_set_servo_speed(SERVO_2_CHANNEL, values["servo_2_speed"])
    if previous.get("servo_3_angle") != values["servo_3_angle"]:
        client.queue_set_servo_angle(SERVO_3_CHANNEL, values["servo_3_angle"])
    if previous.get("servo_4_angle") != values["servo_4_angle"]:
        client.queue_set_servo_angle(SERVO_4_CHANNEL, values["servo_4_angle"])
    servo_controls.set_external_value(SERVO_1_CHANNEL, values["servo_1_speed"])
    servo_controls.set_external_value(SERVO_2_CHANNEL, values["servo_2_speed"])
    servo_controls.set_external_value(SERVO_3_CHANNEL, values["servo_3_angle"])
    servo_controls.set_external_value(SERVO_4_CHANNEL, values["servo_4_angle"])
    previous.update(values)


def _handle_joystick_events(client: SensorUDPClient, joystick, servo_controls: ServoControls,
                            servo_types: tuple[int, ...]):
    if pygame is None:
        return joystick
    for event in pygame.event.get():
        if event.type == pygame.JOYDEVICEADDED and joystick is None:
            joystick = _open_joystick(event.device_index)
        elif event.type == pygame.JOYDEVICEREMOVED and joystick is not None and event.instance_id == joystick.get_instance_id():
            logger.info("Controller disconnected")
            _set_gamepad_safe_positions(client, servo_controls, servo_types)
            joystick = None
        elif event.type == pygame.JOYBUTTONDOWN and joystick is not None:
            if event.button in FACE_BUTTON_COLORS:
                client.queue_set_led_color(LED_MASK_ALL, *FACE_BUTTON_COLORS[event.button], LED_BRIGHTNESS)
            elif event.button == JOYSTICK_GUIDE_BUTTON:
                client.queue_set_led_color(LED_MASK_ALL, 0, 0, 0, LED_BRIGHTNESS)
        elif event.type == pygame.JOYBUTTONUP and joystick is not None and event.button in FACE_BUTTON_COLORS:
            client.queue_set_led_color(LED_MASK_ALL, 0, 0, 0, LED_BRIGHTNESS)
    return joystick


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config()
    lidar_capture = LidarCapture(config.capture_path) if config.capture_path else None

    state = SensorState()
    client = SensorUDPClient(config.ip, config.port, config.token, config.timeout, state, lidar_capture)

    try:
        client.register_master()
    except MasterRegistrationError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Registered as master on %s:%d", config.ip, config.port)
    client.configure_imu_bump(config.imu_bump_threshold_mg, config.imu_bump_debounce_ms)
    client.enable_streams(config.lidar_hz, config.geomag_hz, config.imu_hz, config.huskylens_hz)
    client.start()
    client.initialize_servos(config.servo_types)

    # FREERATIO: stretch content to the actual window rect on both axes (no aspect-locked letterboxing)
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL | cv2.WINDOW_FREERATIO)
    cv2.resizeWindow(WINDOW_NAME, WINDOW_W, WINDOW_H)
    servo_controls = ServoControls(client, WINDOW_W, SERVO_BAND_TOP, config.servo_types)
    huskylens_controls = HuskylensLightControl(client)
    screen_controls = ScreenControls(client, WINDOW_W, SCREEN_BAND_TOP)
    sound_controls = SoundControls(config.ip, config.timeout)
    sound_controls.start()
    display_size = _DisplaySize(WINDOW_W, WINDOW_H)
    cv2.setMouseCallback(WINDOW_NAME, _scaled_mouse_callback(servo_controls, huskylens_controls, screen_controls, sound_controls, display_size))
    joystick = None
    gamepad_controls: dict[str, int] = {}
    last_bump_ts = 0.0
    rumble_supported = True
    if pygame is None:
        logger.warning("pygame is unavailable; gamepad controls are disabled")
    else:
        pygame.init()
        if pygame.joystick.get_count() > 0:
            joystick = _open_joystick(0)
        else:
            logger.info("No controller connected; waiting for one to be attached")
    try:
        while True:
            joystick = _handle_joystick_events(client, joystick, servo_controls, config.servo_types)
            if joystick is not None:
                _apply_gamepad_controls(client, joystick, config.servo_types, gamepad_controls, servo_controls)
            elif gamepad_controls:
                _set_gamepad_safe_positions(client, servo_controls, config.servo_types)
                gamepad_controls.clear()

            snapshot = state.snapshot()
            if snapshot.imu_bump_ts > last_bump_ts:
                last_bump_ts = snapshot.imu_bump_ts
                if joystick is not None and rumble_supported:
                    try:
                        rumble_supported = joystick.rumble(1.0, 1.0, RUMBLE_DURATION_MS)
                        if not rumble_supported:
                            logger.warning("Controller does not support rumble")
                    except pygame.error as exc:
                        rumble_supported = False
                        logger.warning("Controller rumble unavailable: %s", exc)
            frame = compose_dashboard(snapshot, servo_controls, huskylens_controls, screen_controls, sound_controls, client.stats())

            _, _, win_w, win_h = cv2.getWindowImageRect(WINDOW_NAME)
            if win_w > 0 and win_h > 0:
                display_size.width, display_size.height = win_w, win_h
                if (win_w, win_h) != (WINDOW_W, WINDOW_H):
                    frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_LINEAR)
            cv2.imshow(WINDOW_NAME, frame)

            key = cv2.waitKey(int(1000 / TARGET_FPS)) & 0xFF
            if key in (ord("q"), 27):  # q or ESC
                break
            if not _window_is_visible():
                break
    except KeyboardInterrupt:
        pass
    finally:
        if joystick is not None and rumble_supported:
            try:
                joystick.stop_rumble()
            except pygame.error:
                pass
        if pygame is not None:
            pygame.joystick.quit()
            pygame.quit()
        client.disable_streams()
        client.unregister()
        client.stop()
        sound_controls.stop()
        if lidar_capture is not None:
            lidar_capture.close()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    sys.exit(main())
