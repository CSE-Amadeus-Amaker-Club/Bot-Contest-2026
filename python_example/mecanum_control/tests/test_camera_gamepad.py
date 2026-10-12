import pytest

from mecanum_control.camera import MAX_FRAME, MultipartFrames, stream_boundary


def multipart(frame=b"\xff\xd8test\xff\xd9"):
    return b"\r\n--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame


def test_fragmented_multipart():
    parser = MultipartFrames(stream_boundary('multipart/x-mixed-replace; boundary="frame"'))
    frames = []
    payload = multipart() * 3
    for byte in payload:
        frames.extend(parser.feed(bytes([byte])))
    assert frames == [b"\xff\xd8test\xff\xd9"] * 3
    assert len(parser.buffer) == 0


def test_bad_frames_and_bounds():
    with pytest.raises(ValueError):
        stream_boundary("image/jpeg")
    with pytest.raises(ValueError):
        MultipartFrames(b"frame").feed(multipart(b"not-jpeg"))
    with pytest.raises(ValueError):
        MultipartFrames(b"frame").feed(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(MAX_FRAME + 1).encode() + b"\r\n\r\n")


def test_latest_frame_only():
    from mecanum_control.camera import CameraStream
    stream = CameraStream("http://127.0.0.1/cam/stream")
    stream._frame = (b"latest", 1)
    assert stream.take_frame() == (b"latest", 1)
    assert stream.take_frame() is None


def test_xbox_axes_button_edges_and_remove(monkeypatch):
    from types import SimpleNamespace
    import pygame
    from mecanum_control import gamepad
    from mecanum_control.config import Settings

    class Controller:
        name = "Mock Xbox"
        pressed = set()
        triggers = {}
        def as_joystick(self):
            return self
        def get_instance_id(self):
            return 42
        def get_axis(self, axis):
            return {pygame.CONTROLLER_AXIS_RIGHTX: 32767,
                    pygame.CONTROLLER_AXIS_RIGHTY: -32768,
                    pygame.CONTROLLER_AXIS_LEFTX: 16384}.get(axis, self.triggers.get(axis, 0))
        def get_button(self, button):
            return button in self.pressed
        def quit(self):
            pass

    device = Controller()
    events = []
    count = [1]
    monkeypatch.setattr(pygame.event, "get", lambda: events)
    monkeypatch.setattr(pygame.joystick, "get_count", lambda: count[0])
    monkeypatch.setattr(gamepad.controller, "is_controller", lambda _index: True)
    monkeypatch.setattr(gamepad.controller, "Controller", lambda _index: device)
    pad = gamepad.Gamepad(Settings())
    try:
        snapshot, colors = pad.poll(True)
        assert snapshot.right_x == 1 and snapshot.right_y == -1
        assert 0.49 < snapshot.left_x < 0.51
        assert snapshot.connected and not colors
        for button, color in zip((pygame.CONTROLLER_BUTTON_A, pygame.CONTROLLER_BUTTON_B,
                                  pygame.CONTROLLER_BUTTON_X, pygame.CONTROLLER_BUTTON_Y),
                                 ((0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0))):
            device.pressed = {button}
            assert pad.poll(True)[1] == [color]
            assert pad.poll(True)[1] == []
            device.pressed = set()
            assert pad.poll(True)[1] == [(0, 0, 0)]
        assert pad.take_sounds() == []
        for button, sound in ((pygame.CONTROLLER_BUTTON_LEFTSHOULDER, "Rocket-hahaaa-take-that.wav"),
                              (pygame.CONTROLLER_BUTTON_RIGHTSHOULDER, "Rocket-don-t-panic.wav")):
            device.pressed = {button}
            pad.poll(True)
            pad.poll(True)
            assert pad.take_sounds() == [sound]
            device.pressed = set()
            pad.poll(True)
            assert pad.take_sounds() == []
        for axis, sound in ((pygame.CONTROLLER_AXIS_TRIGGERLEFT, "Rocket-are-you-kidding.wav"),
                            (pygame.CONTROLLER_AXIS_TRIGGERRIGHT, "Rocket-okay-panic.wav")):
            for value in (10000, 20000, 12000, 20000):
                device.triggers = {axis: value}
                pad.poll(True)
            assert pad.take_sounds() == [sound]
            for value in (5000, 20000):
                device.triggers = {axis: value}
                pad.poll(True)
            assert pad.take_sounds() == [sound]
            device.triggers = {}
            pad.poll(True)
        events.append(SimpleNamespace(type=pygame.JOYDEVICEREMOVED, instance_id=42))
        count[0] = 0
        assert not pad.poll(True)[0].connected
    finally:
        pad.close()