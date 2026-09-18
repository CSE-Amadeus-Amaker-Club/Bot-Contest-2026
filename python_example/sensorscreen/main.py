"""K10 Bot SensorsScreen replica — registers as UDP master and renders live sensor panels."""

from __future__ import annotations

import importlib.util
import logging
import sys
from os import environ

import cv2

environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
from capture import LidarCapture
from config import load_config
from gamepad_manager import GamepadManager
from huskylens_controls import HuskylensLightControl
from render import (
    GRID_GAP,
    SCREEN_BAND_TOP,
    SENSOR_GRID_TOP,
    SENSOR_ONLY_WINDOW_H,
    SERVO_BAND_TOP,
    SOUND_BAND_TOP,
    WINDOW_H,
    WINDOW_W,
    compose_dashboard,
    compose_sensor_display,
)
from screen_controls import ScreenControls
from servo_controls import ServoControls
from sound_controls import SoundControls
from state import SensorState
from udp_client import MasterRegistrationError, SensorUDPClient
from ui_state import UiState, UiStateStore

logger = logging.getLogger("sensorscreen")

WINDOW_NAME = "aMaker Sensor View"
TARGET_FPS = 30
RUMBLE_DURATION_MS = 250

class BotController():
    class _DisplaySize:
        """Tracks window size for OpenCV mouse coordinate scaling."""

        def __init__(self, width: int, height: int) -> None:
            self.width = width
            self.height = height

    def _load_tk_bindings(self,):
        if importlib.util.find_spec("tkinter") is None or importlib.util.find_spec("_tkinter") is None:
            return None, None
        import tkinter as tk_module

        from ui_tkinter import TkControlWindow

        return tk_module, TkControlWindow

    def _scaled_mouse_callback(self,
        servo_controls: ServoControls,
        huskylens_controls: HuskylensLightControl,
        screen_controls: ScreenControls,
        sound_controls: SoundControls,
        display_size: _DisplaySize,
    ):
        def _callback(self,event: int, x: int, y: int, flags: int, param: object | None = None) -> None:
            scaled_x = round(x * WINDOW_W / display_size.width)
            scaled_y = round(y * WINDOW_H / display_size.height)
            screen_controls.handle_mouse(event, scaled_x, scaled_y)
            sound_controls.handle_mouse(event, scaled_x, scaled_y - SOUND_BAND_TOP, flags)
            servo_controls.handle_mouse(event, scaled_x, scaled_y, flags, param)
            huskylens_controls.handle_mouse(event, scaled_x - GRID_GAP, scaled_y - SENSOR_GRID_TOP - GRID_GAP)

        return _callback


    def _window_is_visible(self,) -> bool:
        try:
            return cv2.getWindowProperty(WINDOW_NAME, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            return False


    def _run_native_loop(self,client: SensorUDPClient, state: SensorState, config, ui_state: UiState,
                        startup_servo_types: tuple[int, ...], tk_module, tk_window_cls) -> UiState:
        if tk_module is None or tk_window_cls is None:
            raise RuntimeError("native loop requested without tkinter support")

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL | cv2.WINDOW_FREERATIO)
        cv2.resizeWindow(WINDOW_NAME, WINDOW_W, SENSOR_ONLY_WINDOW_H)

        root = tk_module.Tk()
        controls = tk_window_cls(
            root,
            client,
            bot_ip=config.ip,
            timeout=config.timeout,
            servo_types=startup_servo_types,
            servo_angle_limits=config.servo_angle_limits,
            initial_state=ui_state,
        )

        if ui_state.selected_screen is not None:
            client.queue_set_screen(ui_state.selected_screen)
        client.queue_set_huskylens_algorithm(ui_state.huskylens_algorithm_index)
        client.queue_set_huskylens_illumination(ui_state.huskylens_illumination_enabled)
        client.queue_set_huskylens_rgb_light(ui_state.huskylens_rgb_light_enabled)
        client.queue_set_huskylens_display(ui_state.huskylens_display_enabled)
        controls.refresh_sounds()

        gamepad = GamepadManager(startup_servo_types, config.servo_angle_limits, config.gamepad_actions)
        sound = SoundControls(config.ip, config.timeout)
        last_bump_ts = 0.0
        gamepad.initialize()
        try:
            while controls.running:
                try:
                    root.update_idletasks()
                    root.update()
                except tk_module.TclError:
                    break

                gamepad.handle_events(client, controls)
                gamepad.apply_controls(client, controls)

                snapshot = state.snapshot()
                if snapshot.imu_bump_ts > last_bump_ts:
                    last_bump_ts = snapshot.imu_bump_ts
                    gamepad.try_rumble(1.0, 1.0, RUMBLE_DURATION_MS)
                frame = compose_sensor_display(snapshot, client.stats())

                _, _, win_w, win_h = cv2.getWindowImageRect(WINDOW_NAME)
                if win_w > 0 and win_h > 0 and (win_w, win_h) != (WINDOW_W, SENSOR_ONLY_WINDOW_H):
                    frame = cv2.resize(frame, (win_w, win_h), interpolation=cv2.INTER_LINEAR)
                cv2.imshow(WINDOW_NAME, frame)

                key = cv2.waitKey(int(1000 / TARGET_FPS)) & 0xFF
                if key in (ord("q"), 27):
                    break
                if not self._window_is_visible():
                    break
        finally:
            gamepad.shutdown()
            controls.close()
        return controls.get_persisted_state()


    def _run_legacy_loop(self,client: SensorUDPClient, state: SensorState, config, ui_state: UiState,
                        startup_servo_types: tuple[int, ...]) -> UiState:
        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL | cv2.WINDOW_FREERATIO)
        cv2.resizeWindow(WINDOW_NAME, WINDOW_W, WINDOW_H)

        servo_controls = ServoControls(client, WINDOW_W, SERVO_BAND_TOP, startup_servo_types)
        huskylens_controls = HuskylensLightControl(
            client,
            enabled=ui_state.huskylens_illumination_enabled,
            rgb_light_enabled=ui_state.huskylens_rgb_light_enabled,
            display_enabled=ui_state.huskylens_display_enabled,
            algorithm_index=ui_state.huskylens_algorithm_index,
        )
        screen_controls = ScreenControls(client, WINDOW_W, SCREEN_BAND_TOP, selected_screen=ui_state.selected_screen)
        sound_controls = SoundControls(config.ip, config.timeout)
        sound_controls.start()

        if ui_state.selected_screen is not None:
            client.queue_set_screen(ui_state.selected_screen)
        client.queue_set_huskylens_algorithm(huskylens_controls.algorithm_index)
        client.queue_set_huskylens_illumination(huskylens_controls.enabled)
        client.queue_set_huskylens_rgb_light(huskylens_controls.rgb_light_enabled)
        client.queue_set_huskylens_display(huskylens_controls.display_enabled)

        display_size = self._DisplaySize(WINDOW_W, WINDOW_H)
        cv2.setMouseCallback(
            WINDOW_NAME,
            self._scaled_mouse_callback(servo_controls, huskylens_controls, screen_controls, sound_controls, display_size),
        )

        gamepad = GamepadManager(startup_servo_types, config.servo_angle_limits, config.gamepad_actions)
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
                if key in (ord("q"), 27):
                    break
                if not self._window_is_visible():
                    break
        finally:
            gamepad.shutdown()
            sound_controls.stop()
        huskylens_settings = huskylens_controls.settings()
        return type(ui_state)(
            selected_screen=screen_controls.selected_screen,
            huskylens_algorithm_index=int(huskylens_settings["algorithm_index"]),
            huskylens_illumination_enabled=bool(huskylens_settings["enabled"]),
            huskylens_rgb_light_enabled=bool(huskylens_settings["rgb_light_enabled"]),
            huskylens_display_enabled=bool(huskylens_settings["display_enabled"]),
            servo_types=servo_controls.servo_types(),
        )


    def main(self) -> int:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        config = load_config()
        ui_state_store = UiStateStore(config.ui_state_path)
        ui_state = ui_state_store.load()
        lidar_capture = LidarCapture(config.capture_path) if config.capture_path else None

        startup_servo_types = ui_state.servo_types if ui_state.servo_types is not None else config.servo_types

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
        client.initialize_servos(startup_servo_types)

        persisted_state: UiState = ui_state
        tk_module, tk_window_cls = self._load_tk_bindings()
        try:
            if tk_module is not None and tk_window_cls is not None:
                logger.info("UI mode: NATIVE (Tk controls + OpenCV sensor window)")
                persisted_state = self._run_native_loop(
                    client,
                    state,
                    config,
                    ui_state,
                    startup_servo_types,
                    tk_module,
                    tk_window_cls,
                )
            else:
                logger.warning(
                    "UI mode: LEGACY (OpenCV-only controls) because tkinter/_tkinter is unavailable in this Python build."
                )
                persisted_state = self._run_legacy_loop(client, state, config, ui_state, startup_servo_types)
        except KeyboardInterrupt:
            pass
        finally:
            ui_state_store.save(persisted_state)
            client.disable_streams()
            client.queue_stop_all_motors()
            client.unregister()
            client.stop()
            if lidar_capture is not None:
                lidar_capture.close()
            cv2.destroyAllWindows()

        return 0


if __name__ == "__main__":
    controller = BotController()
    

    sys.exit(controller.main())
