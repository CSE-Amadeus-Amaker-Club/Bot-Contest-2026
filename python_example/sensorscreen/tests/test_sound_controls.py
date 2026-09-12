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


def test_mousewheel_scrolls_dropdown():
    controls = SoundControls("192.0.2.1", 0.1)
    controls.sounds = [f"sound_{i}.wav" for i in range(10)]
    controls.expanded = True
    assert controls.scroll_offset == 0

    # Scroll down (negative flags or 0 flags in OpenCV)
    controls.handle_mouse(cv2.EVENT_MOUSEWHEEL, 20, 20, flags=-1)
    assert controls.scroll_offset == 1

    controls.handle_mouse(cv2.EVENT_MOUSEWHEEL, 20, 20, flags=-1)
    assert controls.scroll_offset == 2

    # Scroll up (positive flags in OpenCV)
    controls.handle_mouse(cv2.EVENT_MOUSEWHEEL, 20, 20, flags=1)
    assert controls.scroll_offset == 1

    # Scroll up beyond bounds
    controls.handle_mouse(cv2.EVENT_MOUSEWHEEL, 20, 20, flags=1)
    controls.handle_mouse(cv2.EVENT_MOUSEWHEEL, 20, 20, flags=1)
    assert controls.scroll_offset == 0


def test_dropdown_selects_scrolled_sound():
    controls = SoundControls("192.0.2.1", 0.1)
    controls.sounds = [f"sound_{i}.wav" for i in range(10)]
    controls.expanded = True
    controls.scroll_offset = 3

    # Click row 1 (the 2nd visible item in the expanded dropdown)
    row_y = OPTION_TOP + OPTION_H + 5
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, 20, row_y)
    # With offset 3 + row 1 = index 4 ("sound_4.wav")
    assert controls.selected_sound == "sound_4.wav"
    assert controls.expanded is False


def test_scrollbar_click_and_drag():
    controls = SoundControls("192.0.2.1", 0.1)
    controls.sounds = [f"sound_{i}.wav" for i in range(10)]
    controls.expanded = True
    assert controls.scroll_offset == 0

    track_bounds = controls._scrollbar_track_bounds(5)
    tx_center = (track_bounds[0] + track_bounds[2]) // 2

    # Click near bottom of scrollbar track
    controls.handle_mouse(cv2.EVENT_LBUTTONDOWN, tx_center, track_bounds[3] - 2)
    assert controls.dragging_scrollbar is True
    assert controls.scroll_offset > 0

    # Drag up
    controls.handle_mouse(cv2.EVENT_MOUSEMOVE, tx_center, track_bounds[1] + 2)
    assert controls.scroll_offset == 0

    # Release mouse
    controls.handle_mouse(cv2.EVENT_LBUTTONUP, tx_center, track_bounds[1] + 2)
    assert controls.dragging_scrollbar is False


def test_render_with_and_without_scrollbar():
    controls = SoundControls("192.0.2.1", 0.1)
    controls.sounds = ["sound_0.wav", "sound_1.wav"]
    controls.expanded = True
    band_few = controls.render()
    assert band_few.shape == (170, 480, 3)

    controls.sounds = [f"sound_{i}.wav" for i in range(10)]
    band_many = controls.render()
    assert band_many.shape == (170, 480, 3)