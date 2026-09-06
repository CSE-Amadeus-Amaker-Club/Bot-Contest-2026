import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sound_controls import DROP_DOWN_BOUNDS, OPTION_H, OPTION_TOP, PLAY_BOUNDS, SoundControls, parse_sound_list


def test_parse_sound_list_sorts_and_discards_invalid_entries():
    payload = '{"sounds": ["warn.wav", "Ready.wav", "warn.wav", 3, ""]}'
    assert parse_sound_list(payload) == ["Ready.wav", "warn.wav"]


def test_dropdown_selects_sound():
    controls = SoundControls("192.0.2.1", 0.1)
    controls.sounds = ["one.wav", "two.wav"]
    controls.selected_sound = "one.wav"
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, 20, 20)
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, 20, OPTION_TOP + OPTION_H + 5)
    assert controls.selected_sound == "two.wav"
    assert controls.expanded is False


def test_play_button_starts_only_for_selected_sound(monkeypatch):
    controls = SoundControls("192.0.2.1", 0.1)
    controls.selected_sound = "ready tone.wav"
    played = []

    def fake_play():
        played.append(controls.selected_sound)

    monkeypatch.setattr(controls, "_play_selected", fake_play)
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, (PLAY_BOUNDS[0] + PLAY_BOUNDS[2]) // 2, 20)
    assert played == ["ready tone.wav"]


def test_dropdown_bounds_are_clickable():
    controls = SoundControls("192.0.2.1", 0.1)
    x = (DROP_DOWN_BOUNDS[0] + DROP_DOWN_BOUNDS[2]) // 2
    y = (DROP_DOWN_BOUNDS[1] + DROP_DOWN_BOUNDS[3]) // 2
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, x, y)
    assert controls.expanded is True