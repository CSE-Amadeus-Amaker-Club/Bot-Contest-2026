"""Xbox SDL controller polling with configurable raw joystick fallback."""

from __future__ import annotations

import os
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
from pygame._sdl2 import controller

from .config import Settings
from .drive import InputSnapshot
from .protocol import FACE_COLORS

SHOULDER_SOUNDS = (
    (pygame.CONTROLLER_BUTTON_LEFTSHOULDER, "Rocket-hahaaa-take-that.wav"),
    (pygame.CONTROLLER_BUTTON_RIGHTSHOULDER, "Rocket-don-t-panic.wav"),
)
TRIGGER_SOUNDS = (
    (pygame.CONTROLLER_AXIS_TRIGGERLEFT, "Rocket-are-you-kidding.wav"),
    (pygame.CONTROLLER_AXIS_TRIGGERRIGHT, "Rocket-okay-panic.wav"),
)
TRIGGER_PRESS = 0.5
TRIGGER_RELEASE = 0.25


class Gamepad:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        pygame.display.init()
        pygame.joystick.init()
        controller.init()
        self.device = None
        self.semantic = False
        self.name = "No controller"
        self._buttons = (False,) * 4
        self._sound_inputs = (False,) * (len(SHOULDER_SOUNDS) + len(TRIGGER_SOUNDS))
        self._sounds: list[str] = []

    def _release(self) -> None:
        if self.device is not None:
            self.device.quit()
        self.device = None
        self.name = "No controller"
        self._buttons = (False,) * 4
        self._sound_inputs = (False,) * len(self._sound_inputs)

    def take_sounds(self) -> list[str]:
        """Return sound filenames triggered by press edges since the last call."""
        sounds, self._sounds = self._sounds, []
        return sounds

    def _poll_sound_inputs(self) -> None:
        pressed = [bool(self.device.get_button(button)) for button, _name in SHOULDER_SOUNDS]
        for index, (axis, _name) in enumerate(TRIGGER_SOUNDS):
            value = self.device.get_axis(axis) / 32767
            was_pressed = self._sound_inputs[len(SHOULDER_SOUNDS) + index]
            pressed.append(value > (TRIGGER_RELEASE if was_pressed else TRIGGER_PRESS))
        names = [name for _input, name in SHOULDER_SOUNDS + TRIGGER_SOUNDS]
        for previous, current, name in zip(self._sound_inputs, pressed, names):
            if current and not previous:
                self._sounds.append(name)
        self._sound_inputs = tuple(pressed)

    def poll(self, focused: bool) -> tuple[InputSnapshot, list[tuple[int, int, int]]]:
        try:
            events = pygame.event.get()
            if self.device is not None:
                instance_id = self.device.as_joystick().get_instance_id() if self.semantic else self.device.get_instance_id()
                if any(event.type == pygame.JOYDEVICEREMOVED and event.instance_id == instance_id for event in events):
                    self._release()
            if self.device is None and pygame.joystick.get_count():
                self.semantic = controller.is_controller(0)
                self.device = controller.Controller(0) if self.semantic else pygame.joystick.Joystick(0)
                if not self.semantic:
                    self.device.init()
                self.name = self.device.name if self.semantic else self.device.get_name()
            if self.device is None:
                return InputSnapshot(timestamp=time.monotonic(), focused=focused), []
            if self.semantic:
                raw_axes = (self.device.get_axis(pygame.CONTROLLER_AXIS_RIGHTX),
                            self.device.get_axis(pygame.CONTROLLER_AXIS_RIGHTY),
                            self.device.get_axis(pygame.CONTROLLER_AXIS_LEFTX))
                axes = tuple(max(-1.0, value / 32767) for value in raw_axes)
                buttons = tuple(bool(self.device.get_button(index)) for index in
                                (pygame.CONTROLLER_BUTTON_A, pygame.CONTROLLER_BUTTON_B,
                                 pygame.CONTROLLER_BUTTON_X, pygame.CONTROLLER_BUTTON_Y))
                self._poll_sound_inputs()
            else:
                if max(self.settings.axes) >= self.device.get_numaxes() or max(self.settings.buttons) >= self.device.get_numbuttons():
                    raise pygame.error("Raw controller mapping exceeds available inputs")
                axes = tuple(self.device.get_axis(index) for index in self.settings.axes)
                buttons = tuple(bool(self.device.get_button(index)) for index in self.settings.buttons)
            colors = []
            for index, (previous, current) in enumerate(zip(self._buttons, buttons)):
                if previous != current:
                    colors.append(FACE_COLORS[index] if current else (0, 0, 0))
            self._buttons = buttons
            return InputSnapshot(*axes, time.monotonic(), True, focused), colors
        except pygame.error as error:
            self._release()
            self.name = f"Controller error: {error}"
            return InputSnapshot(timestamp=time.monotonic(), focused=focused), []

    def close(self) -> None:
        self._release()
        controller.quit()
        pygame.joystick.quit()
        pygame.display.quit()