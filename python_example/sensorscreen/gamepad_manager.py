"""Gamepad lifecycle and input mapping for SensorsScreen."""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

try:
    import pygame # type: ignore  # noqa: I001
except ImportError:
    pygame :type|None = None

try:
    sdl_controller = importlib.import_module("pygame._sdl2.controller")
except ImportError:
    sdl_controller = None

import protocol as proto
from gamepad_callbacks import mix_track_speeds, set_track_drive


class ServoValueSink(Protocol):
    def set_external_value(self, channel: int, value: int) -> None: ...
    def servo_types(self) -> tuple[int, ...]: ...

logger = logging.getLogger("sensorscreen")

JOYSTICK_DEADZONE = 0.12
JOYSTICK_TRIGGER_DEADZONE = 0.08
JOYSTICK_TRIGGER_PRECISION = 3
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

JOYSTICK_AXIS_DEFAULTS = {
    "left_stick_x": JOYSTICK_LEFT_X_AXIS,
    "left_stick_y": JOYSTICK_LEFT_Y_AXIS,
    "right_stick_x": JOYSTICK_RIGHT_X_AXIS,
    "right_stick_y": JOYSTICK_RIGHT_Y_AXIS,
    "left_trigger": JOYSTICK_LEFT_TRIGGER_AXIS,
    "right_trigger": JOYSTICK_RIGHT_TRIGGER_AXIS,
}
SDL_AXIS_KEYS = {
    "left_stick_x": "leftx",
    "left_stick_y": "lefty",
    "right_stick_x": "rightx",
    "right_stick_y": "righty",
    "left_trigger": "lefttrigger",
    "right_trigger": "righttrigger",
}

SERVO_1_CHANNEL = 0
SERVO_2_CHANNEL = 1
SERVO_4_CHANNEL = 3
SERVO_5_CHANNEL = 4
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
    inputs: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    raw_axes: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))


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
        self._axis_indices = dict(JOYSTICK_AXIS_DEFAULTS)
        self._previous: dict[str, int] = {}
        self._previous_inputs: dict[str, Any] = {}
        self._mapping_errors: set[str] = set()
        self._inputs: Mapping[str, Any] = MappingProxyType({})
        self._raw_axes: Mapping[str, float] = MappingProxyType({})
        self._has_logged_rumble_error = False
        self._rumble_supported = True

        self._compiled_actions = self._compile_actions(self._gamepad_actions)
        self._legacy_mode = len(self._compiled_actions) == 0

    @builtins.property
    def joystick(self):
        return self._joystick

    @joystick.setter
    def joystick(self, value) -> None:
        self._reset_inputs()
        self._joystick = value

    def initialize(self) -> None:
        if pygame is None:
            logger.warning("pygame is unavailable; gamepad controls are disabled")
            return
        pygame.init()
        if pygame.joystick.get_count() > 0:
            self.joystick = self._open_joystick(0)
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
                self.joystick = self._open_joystick(event.device_index)
            elif (
                event.type == pygame.JOYDEVICEREMOVED
                and self._joystick is not None
                and event.instance_id == self._joystick.get_instance_id()
            ):
                logger.info("Controller disconnected")
                self.set_safe_positions(client, servo_controls)
                self.joystick = None
            elif event.type == pygame.JOYHATMOTION and self._joystick is not None and not self._legacy_mode:
                self._handle_hat(event.value, client, servo_controls)
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

    def _handle_hat(self, hat_value, client, servo_controls: ServoValueSink) -> None:
        """Fire pad_* actions on the press edge of each D-pad direction."""
        x, y = hat_value
        current = {"pad_up": y > 0, "pad_down": y < 0, "pad_left": x < 0, "pad_right": x > 0}
        for key, pressed in current.items():
            was_pressed = self._previous_inputs.get(key, False)
            self._previous_inputs[key] = pressed
            if pressed and not was_pressed:
                self._run_action(key, True, client, servo_controls)

    def apply_controls(self, client, servo_controls: ServoValueSink) -> None:
        self._refresh_servo_types(servo_controls)
        if self._joystick is None:
            if self._previous or self._previous_inputs:
                self.set_safe_positions(client, servo_controls)
                self._reset_inputs()
            return

        axes = tuple(self._joystick.get_axis(axis) for axis in range(self._joystick.get_numaxes()))
        stick_axes = {
            key: self._axis_indices[key]
            for key in ("left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y")
        }
        self._raw_axes = MappingProxyType({
            key: axes[axis] if axis < len(axes) else 0.0 for key, axis in stick_axes.items()
        })
        values: dict[str, Any] = {
            key: self._speed_from_axis(value) for key, value in self._raw_axes.items()
        }
        for key in ("left_trigger", "right_trigger"):
            axis = self._axis_indices[key]
            values[key] = self._trigger_ratio(axes[axis]) if axis < len(axes) else 0.0
        values.update({
            "left_bumper": self._read_button(self._joystick, JOYSTICK_LEFT_BUMPER_BUTTON),
            "right_bumper": self._read_button(self._joystick, JOYSTICK_RIGHT_BUMPER_BUTTON),
        })
        self._inputs = MappingProxyType(values)
        if self._legacy_mode:
            self._apply_legacy_controls(client, servo_controls)
            return

        for key in POLLED_INPUT_KEYS:
            if key not in self._compiled_actions:
                continue
            current = values[key]
            observed = (
                self._raw_axes[key]
                if self._compiled_actions[key].callback is set_track_drive and key in self._raw_axes
                else current
            )
            if self._previous_inputs.get(key) == observed:
                continue
            self._previous_inputs[key] = observed
            self._run_action(key, current, client, servo_controls)

    def _apply_legacy_controls(self, client, servo_controls: ServoValueSink) -> None:
        if not (
            self._servo_types[SERVO_1_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_2_CHANNEL] == proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_4_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
            and self._servo_types[SERVO_5_CHANNEL] != proto.SERVO_TYPE_CONTINUOUS
        ):
            self._log_mapping_error("Joystick requires continuous S1/S2 and positional S4/S5")
            return
        context = self._action_context(client, servo_controls)
        self.apply_track_drive(SERVO_1_CHANNEL, SERVO_2_CHANNEL, context)
        self.apply_paired_angle("left", SERVO_4_CHANNEL, context)
        self.apply_paired_angle("right", SERVO_5_CHANNEL, context)

    def _action_context(self, client, servo_controls: ServoValueSink) -> GamepadActionContext:
        return GamepadActionContext(client, servo_controls, self, self._inputs, self._raw_axes)

    def _reset_inputs(self) -> None:
        self._previous.clear()
        self._previous_inputs.clear()

    def _refresh_servo_types(self, servo_controls: ServoValueSink) -> None:
        accessor = getattr(servo_controls, "servo_types", None)
        current = tuple(accessor()) if accessor is not None else self._servo_types
        if current != self._servo_types:
            self._servo_types = current
            self._reset_inputs()
            self._mapping_errors.clear()

    def _log_mapping_error(self, message: str) -> None:
        if message not in self._mapping_errors:
            logger.error(message)
            self._mapping_errors.add(message)

    def _send_paired_value(self, channel: int, value: int, continuous: bool, context: GamepadActionContext) -> None:
        key = f"{'speed' if continuous else 'angle'}-{channel}"
        if self._previous.get(key) != value:
            if continuous:
                context.client.queue_set_servo_speed(channel, value)
            else:
                context.client.queue_set_servo_angle(channel, value)
            self._previous[key] = value
        context.servo_controls.set_external_value(channel, value)

    def apply_track_drive(self, leftchannel: int, rightchannel: int, context: GamepadActionContext) -> None:
        """Apply one coherent track calculation, suppressing duplicate outputs within a poll."""
        if leftchannel == rightchannel or any(
            self._servo_types[channel] != proto.SERVO_TYPE_CONTINUOUS for channel in (leftchannel, rightchannel)
        ):
            self._log_mapping_error("Track mapping requires two distinct continuous servo channels")
            return
        speeds = mix_track_speeds(
            context.raw_axes.get("left_stick_x", 0.0),
            context.raw_axes.get("left_stick_y", 0.0), JOYSTICK_DEADZONE,
        )
        for channel, speed in zip((leftchannel, rightchannel), speeds):
            self._send_paired_value(channel, speed, True, context)

    def apply_paired_angle(self, side: str, channel: int, context: GamepadActionContext) -> None:
        """Resolve the same-side bumper and trigger using the shared mechanical limits."""
        if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
            self._log_mapping_error(f"S{channel + 1} requires an angular servo for {side} controls")
            return
        try:
            minimum, maximum = self._resolve_angle_limits(channel)
        except ValueError as exc:
            self._log_mapping_error(str(exc))
            return
        ratio = max(float(context.inputs.get(f"{side}_trigger", 0.0)),
                    1.0 if context.inputs.get(f"{side}_bumper", False) else 0.0)
        self._send_paired_value(channel, round(minimum + (maximum - minimum) * ratio), False, context)

    def _run_action(self, input_key: str, value: Any, client: Any, servo_controls: ServoValueSink) -> None:
        action = self._compiled_actions.get(input_key)
        if action is None:
            return
        # For button mappings without $value, run once on press and ignore release.
        if input_key.startswith("button_") and not action.value_argument_names and value is False:
            return
        call_kwargs = dict(action.kwargs)
        for name in action.value_argument_names:
            call_kwargs[name] = value
        if action.pass_context:
            call_kwargs["context"] = self._action_context(client, servo_controls)
        if action.pass_client:
            call_kwargs["client"] = client
        if action.pass_servo_controls:
            call_kwargs["servo_controls"] = servo_controls
        try:
            action.callback(**call_kwargs)
        except Exception:
            logger.exception("Gamepad action '%s' failed", input_key)

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
        self._refresh_servo_types(servo_controls)
        for channel in range(proto.SERVO_COUNT):
            if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
                client.queue_set_servo_speed(channel, 0, force=True)
                servo_controls.set_external_value(channel, 0)
            else:
                try:
                    target, _ = self._resolve_angle_limits(channel)
                except ValueError as exc:
                    self._log_mapping_error(str(exc))
                    continue
                client.queue_set_servo_angle(channel, target, force=True)
                servo_controls.set_external_value(channel, target)
        self._reset_inputs()

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
        if not 0 <= configured[0] <= configured[1] <= default_max:
            raise ValueError(f"S{channel + 1} angle limits are incompatible with its current servo type")
        return configured

    def _open_joystick(self, device_index: int):
        if pygame is None:
            return None
        try:
            joystick = pygame.joystick.Joystick(device_index)
            joystick.init()
            self._axis_indices = dict(JOYSTICK_AXIS_DEFAULTS)
            self._load_axis_mapping(device_index, joystick.get_numaxes())
            logger.info("Controller connected: %s", joystick.get_name())
            logger.info("Controller axis mapping: %s", self._axis_indices)
            return joystick
        except Exception as exc:
            logger.warning("Unable to open controller %d: %s", device_index, exc)
            return None

    def _load_axis_mapping(self, device_index: int, axis_count: int) -> None:
        """Use SDL's device-specific axis bindings while retaining fallback indices."""
        if sdl_controller is None or pygame is None:
            return
        try:
            sdl_controller.init()
            if not sdl_controller.is_controller(device_index):
                return
            controller = sdl_controller.Controller(device_index)
            try:
                mapping = controller.get_mapping()
            finally:
                controller.quit()
            for key, sdl_key in SDL_AXIS_KEYS.items():
                binding = mapping.get(sdl_key, "")
                if binding.startswith("a") and binding[1:].isdigit():
                    axis = int(binding[1:])
                    if axis < axis_count:
                        self._axis_indices[key] = axis
                else:
                    logger.warning("Unsupported SDL axis binding for %s: %s; using fallback", key, binding)
        except (pygame.error, RuntimeError, ValueError) as exc:
            logger.warning("Unable to read SDL controller mapping; using fallback axes: %s", exc)

    @staticmethod
    def _read_button(joystick, button: int) -> bool:
        return button < joystick.get_numbuttons() and bool(joystick.get_button(button))

    @staticmethod
    def _trigger_position(joystick, axis: int) -> float:
        if axis >= joystick.get_numaxes():
            return 0.0
        return GamepadManager._trigger_ratio(joystick.get_axis(axis))

    @staticmethod
    def _trigger_ratio(value: float) -> float:
        position = min(1.0, max(0.0, (value + 1.0) / 2.0))
        if position <= JOYSTICK_TRIGGER_DEADZONE:
            return 0.0
        normalized = (position - JOYSTICK_TRIGGER_DEADZONE) / (1.0 - JOYSTICK_TRIGGER_DEADZONE)
        return round(normalized, JOYSTICK_TRIGGER_PRECISION)

    @staticmethod
    def _stick_speed(joystick, axis: int) -> int:
        if axis >= joystick.get_numaxes():
            return 0
        return GamepadManager._speed_from_axis(joystick.get_axis(axis))

    @staticmethod
    def _speed_from_axis(value: float) -> int:
        speed = -round(value * 100)
        return 0 if abs(speed) < round(JOYSTICK_DEADZONE * 100) else speed
