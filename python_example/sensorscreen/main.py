"""K10 Bot SensorsScreen replica — registers as UDP master and renders live sensor panels."""

from __future__ import annotations

import logging
import sys

import cv2

from capture import LidarCapture
from config import load_config
from gamepad_manager import GamepadManager
from huskylens_controls import HuskylensLightControl
from render import (
    GRID_GAP,
    SCREEN_BAND_TOP,
    SENSOR_GRID_TOP,
    SERVO_BAND_TOP,
    SOUND_BAND_TOP,
    WINDOW_H,
    WINDOW_W,
    compose_dashboard,
)
from screen_controls import ScreenControls
from sound_controls import SoundControls
from servo_controls import ServoControls
from state import SensorState
from udp_client import MasterRegistrationError, SensorUDPClient

logger = logging.getLogger("sensorscreen")

WINDOW_NAME = "aMaker Bot demo controller"
TARGET_FPS = 30
RUMBLE_DURATION_MS = 250


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
        sound_controls.handle_mouse(event, scaled_x, scaled_y - SOUND_BAND_TOP, flags)
        servo_controls.handle_mouse(event, scaled_x, scaled_y, flags, param)
        huskylens_controls.handle_mouse(event, scaled_x - GRID_GAP, scaled_y - SENSOR_GRID_TOP - GRID_GAP)

    return _callback


def _window_is_visible() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) >= 1
    except cv2.error:
        return False


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
    gamepad = GamepadManager(config.servo_types, config.servo_angle_limits)
    last_bump_ts = 0.0
    gamepad.initialize()
    try:
        while True:
            gamepad.handle_events(client, servo_controls)
            gamepad.apply_controls(client, servo_controls)

            snapshot = state.snapshot()
            if snapshot.imu_bump_ts > last_bump_ts:
                last_bump_ts = snapshot.imu_bump_ts
                gamepad.try_rumble(1.0, 1.0, RUMBLE_DURATION_MS)
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
        gamepad.shutdown()
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
