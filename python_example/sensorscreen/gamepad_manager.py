"""Gamepad lifecycle and input mapping for SensorsScreen."""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import logging
from dataclasses import dataclass
from typing import Any, Protocol

try:
    import pygame # type: ignore  # noqa: I001
except ImportError:
    pygame :type|None = None

import protocol as proto


class ServoValueSink(Protocol):
    def set_external_value(self, channel: int, value: int) -> None: ...

logger = logging.getLogger("sensorscreen")

JOYSTICK_DEADZONE = 0.12
JOYSTICK_TRIGGER_DEADZONE = 0.08
JOYSTICK_LEFT_X_AXIS = 0
JOYSTICK_LEFT_Y_AXIS = 1
JOYSTICK_RIGHT_X_AXIS = 2
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
LED_MASK_ALL = 0x1F
LED_BRIGHTNESS = 255

FACE_BUTTON_COLORS = {
    JOYSTICK_X_BUTTON: (0, 0, 255),
    JOYSTICK_Y_BUTTON: (255, 255, 0),
    JOYSTICK_A_BUTTON: (0, 255, 0),
    JOYSTICK_B_BUTTON: (255, 0, 0),
}

BUTTON_KEY_BY_INDEX = {
    JOYSTICK_A_BUTTON: "button_a",
    JOYSTICK_B_BUTTON: "button_b",
    JOYSTICK_X_BUTTON: "button_x",
    JOYSTICK_Y_BUTTON: "button_y",
    JOYSTICK_LEFT_BUMPER_BUTTON: "button_lb",
    JOYSTICK_RIGHT_BUMPER_BUTTON: "button_rb",
    JOYSTICK_GUIDE_BUTTON: "button_guide",
}

POLLED_INPUT_KEYS = (
    "left_stick_x",
    "left_stick_y",
    "right_stick_x",
    "right_stick_y",
    "left_trigger",
    "right_trigger",
    "left_bumper",
    "right_bumper",
)

_VALUE_SENTINEL = object()


@dataclass(frozen=True)
class _CompiledAction:
    callback: Any
    kwargs: dict[str, Any]
    value_argument_names: tuple[str, ...]
    pass_context: bool
    pass_client: bool
    pass_servo_controls: bool


@dataclass(frozen=True)
class GamepadActionContext:
    client: Any
    servo_controls: ServoValueSink
    manager: GamepadManager


class GamepadManager:
    def __init__(
        self,
        servo_types: tuple[int, ...],
        servo_angle_limits: tuple[tuple[int, int] | None, ...],
        gamepad_actions: dict[str, str] | None = None,
    ) -> None:
        self._servo_types = servo_types
        self._servo_angle_limits = servo_angle_limits
        self._gamepad_actions = gamepad_actions or {}
        self._joystick = None
        self._previous: dict[str, int] = {}
        self._previous_inputs: dict[str, Any] = {}
        self._has_logged_mapping_error = False
        self._has_logged_rumble_error = False
        self._rumble_supported = True

        self._mapping_is_valid = (
            self._servo_types[SERVO_1_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_2_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_3_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_4_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
        )

        self._servo_3_min, self._servo_3_max = self._resolve_angle_limits(SERVO_3_CHANNEL)
        self._servo_4_min, self._servo_4_max = self._resolve_angle_limits(SERVO_4_CHANNEL)
        self._compiled_actions = self._compile_actions(self._gamepad_actions)
        self._legacy_mode = len(self._compiled_actions) == 0

    @builtins.property
    def joystick(self):
        return self._joystick

    @joystick.setter
    def joystick(self, value) -> None:
        self._joystick = value

    def initialize(self) -> None:
        if pygame is None:
            logger.warning("pygame is unavailable; gamepad controls are disabled")
            return
        pygame.init()
        if pygame.joystick.get_count() > 0:
            self._joystick = self._open_joystick(0)
        else:
            logger.info("No controller connected; waiting for one to be attached")

    def shutdown(self) -> None:
        if self._joystick is not None and self._rumble_supported:
            try:
                self._joystick.stop_rumble()
            except Exception:
                pass
        if pygame is not None:
            pygame.joystick.quit()
            pygame.quit()

    def handle_events(self, client, servo_controls: ServoValueSink) -> None:
        if pygame is None:
            return
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEADDED and self._joystick is None:
                self._joystick = self._open_joystick(event.device_index)
            elif (
                event.type == pygame.JOYDEVICEREMOVED
                and self._joystick is not None
                and event.instance_id == self._joystick.get_instance_id()
            ):
                logger.info("Controller disconnected")
                self.set_safe_positions(client, servo_controls)
                self._joystick = None
                self._previous.clear()
            elif event.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP) and self._joystick is not None:
                if self._legacy_mode:
                    if event.type == pygame.JOYBUTTONDOWN:
                        if event.button in FACE_BUTTON_COLORS:
                            client.queue_set_led_color(LED_MASK_ALL, *FACE_BUTTON_COLORS[event.button], LED_BRIGHTNESS)
                        elif event.button == JOYSTICK_GUIDE_BUTTON:
                            client.queue_set_led_color(LED_MASK_ALL, 0, 0, 0, LED_BRIGHTNESS)
                    elif event.button in FACE_BUTTON_COLORS:
                        client.queue_set_led_color(LED_MASK_ALL, 0, 0, 0, LED_BRIGHTNESS)
                else:
                    button_key = BUTTON_KEY_BY_INDEX.get(int(event.button))
                    if button_key is None:
                        continue
                    self._run_action(button_key, event.type == pygame.JOYBUTTONDOWN, client, servo_controls)

    def apply_controls(self, client, servo_controls: ServoValueSink) -> None:
        if self._joystick is None:
            if self._previous:
                self.set_safe_positions(client, servo_controls)
                self._previous.clear()
                self._previous_inputs.clear()
            return

        if self._legacy_mode:
            self._apply_legacy_controls(client, servo_controls)
            raise Exception("No Control applied.")
            # return

        values: dict[str, Any] = {
            "left_stick_x": self._stick_speed(self._joystick, JOYSTICK_LEFT_X_AXIS),
            "left_stick_y": self._stick_speed(self._joystick, JOYSTICK_LEFT_Y_AXIS),
            "right_stick_x": self._stick_speed(self._joystick, JOYSTICK_RIGHT_X_AXIS),
            "right_stick_y": self._stick_speed(self._joystick, JOYSTICK_RIGHT_Y_AXIS),
            "left_trigger": self._trigger_position(self._joystick, JOYSTICK_LEFT_TRIGGER_AXIS),
            "right_trigger": self._trigger_position(self._joystick, JOYSTICK_RIGHT_TRIGGER_AXIS),
            "left_bumper": self._read_button(self._joystick, JOYSTICK_LEFT_BUMPER_BUTTON),
            "right_bumper": self._read_button(self._joystick, JOYSTICK_RIGHT_BUMPER_BUTTON),
        }
        for key in POLLED_INPUT_KEYS:
            if key not in self._compiled_actions:
                continue
            current = values[key]
            if self._previous_inputs.get(key) == current:
                continue
            self._previous_inputs[key] = current
            self._run_action(key, current, client, servo_controls)

    def _apply_legacy_controls(self, client, servo_controls: ServoValueSink) -> None:

    #     if not self._mapping_is_valid:
    #         if not self._has_logged_mapping_error:
    #             logger.error("Joystick mapping requires continuous servos on channels 0/1 and positional servos on 2/3")
    #             self._has_logged_mapping_error = True
    #         return

    #     servo_3_position = max(
    #         1.0 if self._read_button(self._joystick, JOYSTICK_LEFT_BUMPER_BUTTON) else 0.0,
    #         self._trigger_position(self._joystick, JOYSTICK_LEFT_TRIGGER_AXIS),
    #     )
    #     servo_4_position = max(
    #         1.0 if self._read_button(self._joystick, JOYSTICK_RIGHT_BUMPER_BUTTON) else 0.0,
    #         self._trigger_position(self._joystick, JOYSTICK_RIGHT_TRIGGER_AXIS),
    #     )

    #     values = {
    #         "servo_1_speed": self._stick_speed(self._joystick, JOYSTICK_LEFT_Y_AXIS),
    #         "servo_2_speed": self._stick_speed(self._joystick, JOYSTICK_RIGHT_Y_AXIS),
    #         "servo_3_angle": round(self._servo_3_min + (self._servo_3_max - self._servo_3_min) * servo_3_position),
    #         "servo_4_angle": round(self._servo_4_min + (self._servo_4_max - self._servo_4_min) * servo_4_position),
    #     }

    #     if self._previous.get("servo_1_speed") != values["servo_1_speed"]:
    #         client.queue_set_servo_speed(SERVO_1_CHANNEL, values["servo_1_speed"])
    #     if self._previous.get("servo_2_speed") != values["servo_2_speed"]:
    #         client.queue_set_servo_speed(SERVO_2_CHANNEL, values["servo_2_speed"])
    #     if self._previous.get("servo_3_angle") != values["servo_3_angle"]:
    #         client.queue_set_servo_angle(SERVO_3_CHANNEL, values["servo_3_angle"])
    #     if self._previous.get("servo_4_angle") != values["servo_4_angle"]:
    #         client.queue_set_servo_angle(SERVO_4_CHANNEL, values["servo_4_angle"])

    #     servo_controls.set_external_value(SERVO_1_CHANNEL, values["servo_1_speed"])
    #     servo_controls.set_external_value(SERVO_2_CHANNEL, values["servo_2_speed"])
    #     servo_controls.set_external_value(SERVO_3_CHANNEL, values["servo_3_angle"])
    #     servo_controls.set_external_value(SERVO_4_CHANNEL, values["servo_4_angle"])
    #     self._previous.update(values)
        pass

    def _run_action(self, input_key: str, value: Any, client: Any, servo_controls: ServoValueSink) -> None:
        action = self._compiled_actions.get(input_key)
        if action is None:
            return
        call_kwargs = dict(action.kwargs)
        for name in action.value_argument_names:
            call_kwargs[name] = value
        if action.pass_context:
            call_kwargs["context"] = GamepadActionContext(client=client, servo_controls=servo_controls, manager=self)
        if action.pass_client:
            call_kwargs["client"] = client
        if action.pass_servo_controls:
            call_kwargs["servo_controls"] = servo_controls
        action.callback(**call_kwargs)

    def _compile_actions(self, gamepad_actions: dict[str, str]) -> dict[str, _CompiledAction]:
        compiled: dict[str, _CompiledAction] = {}
        for input_key, expression in gamepad_actions.items():
            compiled[input_key] = self._compile_action(input_key, expression)
        return compiled

    def _compile_action(self, input_key: str, expression: str) -> _CompiledAction:
        placeholder = "__GAMEPAD_VALUE__"
        normalized = expression.replace("$value", placeholder)
        try:
            parsed = ast.parse(normalized, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"invalid gamepad action for {input_key}: {expression}") from exc

        if not isinstance(parsed.body, ast.Call):
            raise ValueError(f"gamepad action for {input_key} must be a function call")

        callback = self._resolve_callable(parsed.body.func)
        kwargs: dict[str, Any] = {}
        dynamic_names: list[str] = []
        for keyword in parsed.body.keywords:
            if keyword.arg is None:
                raise ValueError(f"gamepad action for {input_key} cannot use **kwargs unpacking")
            if isinstance(keyword.value, ast.Name) and keyword.value.id == placeholder:
                kwargs[keyword.arg] = _VALUE_SENTINEL
                dynamic_names.append(keyword.arg)
                continue
            if isinstance(keyword.value, ast.Name) and keyword.value.id in {"true", "false"}:
                kwargs[keyword.arg] = keyword.value.id == "true"
                continue
            if not isinstance(keyword.value, ast.Constant):
                raise ValueError(
                    f"gamepad action for {input_key} only supports literal keyword values or $value placeholder"
                )
            kwargs[keyword.arg] = keyword.value.value

        signature = inspect.signature(callback)
        parameters = signature.parameters
        has_var_keyword = any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())

        pass_context = has_var_keyword or "context" in parameters
        pass_client = has_var_keyword or "client" in parameters
        pass_servo_controls = has_var_keyword or "servo_controls" in parameters

        sample_kwargs = {
            key: (0 if value is _VALUE_SENTINEL else value)
            for key, value in kwargs.items()
        }
        if pass_context:
            sample_kwargs["context"] = None
        if pass_client:
            sample_kwargs["client"] = None
        if pass_servo_controls:
            sample_kwargs["servo_controls"] = None
        try:
            signature.bind(**sample_kwargs)
        except TypeError as exc:
            raise ValueError(f"invalid gamepad action for {input_key}: {exc}") from exc

        return _CompiledAction(
            callback=callback,
            kwargs=kwargs,
            value_argument_names=tuple(dynamic_names),
            pass_context=pass_context,
            pass_client=pass_client,
            pass_servo_controls=pass_servo_controls,
        )

    def _resolve_callable(self, function_node: ast.AST):
        path = self._callable_path(function_node)
        if "." not in path:
            raise ValueError(f"callback path must be dotted module.function name: {path}")
        module_name, function_name = path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        callback = getattr(module, function_name, None)
        if callback is None or not callable(callback):
            raise ValueError(f"callback is not callable: {path}")
        return callback

    def _callable_path(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._callable_path(node.value)}.{node.attr}"
        raise ValueError("callback path must be a dotted function reference")

    def set_safe_positions(self, client, servo_controls: ServoValueSink) -> None:
        for channel in (SERVO_1_CHANNEL, SERVO_2_CHANNEL, SERVO_3_CHANNEL, SERVO_4_CHANNEL):
            if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
                client.queue_set_servo_speed(channel, 0, force=True)
            else:
                target = self._servo_3_min if channel == SERVO_3_CHANNEL else self._servo_4_min if channel == SERVO_4_CHANNEL else 0
                client.queue_set_servo_angle(channel, target, force=True)
            servo_controls.set_external_value(channel, 0)

    def try_rumble(self, low: float, high: float, duration_ms: int) -> bool:
        if pygame is None or self._joystick is None or not self._rumble_supported:
            return False
        try:
            self._rumble_supported = self._joystick.rumble(low, high, duration_ms)
            if not self._rumble_supported and not self._has_logged_rumble_error:
                logger.warning("Controller does not support rumble")
                self._has_logged_rumble_error = True
        except Exception as exc:
            self._rumble_supported = False
            if not self._has_logged_rumble_error:
                logger.warning("Controller rumble unavailable: %s", exc)
                self._has_logged_rumble_error = True
        return self._rumble_supported

    def _resolve_angle_limits(self, channel: int) -> tuple[int, int]:
        servo_type = self._servo_types[channel]
        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            return (0, 0)
        default_max = 270 if servo_type == proto.SERVO_TYPE_270 else 180
        configured = self._servo_angle_limits[channel]
        if configured is None:
            return (0, default_max)
        return configured

    def _open_joystick(self, device_index: int):
        try:
            joystick = pygame.joystick.Joystick(device_index)
            joystick.init()
            logger.info("Controller connected: %s", joystick.get_name())
            return joystick
        except Exception as exc:
            logger.warning("Unable to open controller %d: %s", device_index, exc)
            return None

    @staticmethod
    def _read_button(joystick, button: int) -> bool:
        return button < joystick.get_numbuttons() and bool(joystick.get_button(button))

    @staticmethod
    def _trigger_position(joystick, axis: int) -> float:
        if axis >= joystick.get_numaxes():
            return 0.0
        position = min(1.0, max(0.0, (joystick.get_axis(axis) + 1.0) / 2.0))
        if position <= JOYSTICK_TRIGGER_DEADZONE:
            return 0.0
        return (position - JOYSTICK_TRIGGER_DEADZONE) / (1.0 - JOYSTICK_TRIGGER_DEADZONE)

    @staticmethod
    def _stick_speed(joystick, axis: int) -> int:
        if axis >= joystick.get_numaxes():
            return 0
        speed = -round(joystick.get_axis(axis) * 100)
        return 0 if abs(speed) < round(JOYSTICK_DEADZONE * 100) else speed
