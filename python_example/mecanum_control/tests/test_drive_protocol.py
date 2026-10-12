from dataclasses import replace

import pytest

from mecanum_control.config import Settings, load_settings, save_settings
from mecanum_control.drive import InputSnapshot, mix, motion_arrows
from mecanum_control import protocol


@pytest.mark.parametrize("axes,expected", [
    ((0, 0, 0), (0, 0, 0, 0)),
    ((0, -1, 0), (30, 30, 30, 30)),
    ((0, 1, 0), (-30, -30, -30, -30)),
    ((1, 0, 0), (30, -30, -30, 30)),
    ((0, 0, 1), (30, -30, 30, -30)),
    ((1, -1, 1), (30, -10, 10, 10)),
])
def test_complete_snapshot(axes, expected):
    settings = Settings(inverted=(False,) * 4)
    assert mix(InputSnapshot(*axes), settings) == expected


def test_inversion_and_deadzone():
    assert mix(InputSnapshot(0.1, -0.1, 0.1), Settings()) == (0, 0, 0, 0)
    assert mix(InputSnapshot(0, -1, 0), Settings()) == (30, -30, 30, -30)
    with pytest.raises(ValueError):
        mix(InputSnapshot(float("nan")), Settings())


@pytest.mark.parametrize("wheels,expected", [
    ((1, 1, 1, 1), ("↑", "-")),
    ((-1, -1, -1, -1), ("↓", "-")),
    ((1, -1, -1, 1), ("→", "-")),
    ((-1, 1, 1, -1), ("←", "-")),
    ((2, 0, 0, 2), ("↗", "-")),
    ((0, 2, 2, 0), ("↖", "-")),
    ((0, -2, -2, 0), ("↘", "-")),
    ((-2, 0, 0, -2), ("↙", "-")),
    ((1, -1, 1, -1), ("-", "⟳")),
    ((-1, 1, -1, 1), ("-", "⟲")),
    ((0, 0, 0, 0), ("-", "-")),
])
def test_motion_arrows(wheels, expected):
    assert motion_arrows(wheels, (False,) * 4) == expected


def test_motion_arrows_undo_wheel_inversion_and_show_combined_motion():
    assert motion_arrows((30, -30, 30, -30), (False, True, False, True)) == ("↑", "-")
    assert motion_arrows((4, 0, 2, -2), (False, True, False, True)) == ("↗", "⟳")


def test_motion_arrows_reject_invalid_wheel_count():
    with pytest.raises(ValueError):
        motion_arrows((0, 0, 0), (False,) * 4)


def test_settings(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(path, Settings())
    assert load_settings(path) == Settings()
    assert "token" not in path.read_text()
    with pytest.raises(ValueError):
        replace(Settings(), channels=(0, 0, 2, 3))


def test_protocol():
    assert protocol.servo_speed(3, -100) == b"\x23\x08\x9c"
    assert protocol.servo_type(15) == b"\x22\x0f\x02"
    assert protocol.decode_reply(b"\x23\x00" + bytes(8)) == (0x23, 0, b"")
    assert protocol.decode_reply(b"\x44abcd" + bytes(8)) == (0x44, None, b"abcd")
    for frame in (b"\x23\x00", b"\x23\x00\x01" + bytes(8), b"\x43\x00" + bytes(8)):
        with pytest.raises(ValueError):
            protocol.decode_reply(frame)
    with pytest.raises(ValueError):
        protocol.register("bad")
    assert protocol.sound_play("jarvis-connected.wav") == b"\xb1jarvis-connected.wav"
    assert protocol.decode_reply(b"\xb1\x03" + bytes(8)) == (0xB1, 3, b"")
    for name in ("x.mp3", "../x.wav", "a/b.wav", "é.wav", "a" * 45 + ".wav", "a\n.wav"):
        with pytest.raises(ValueError):
            protocol.sound_play(name)