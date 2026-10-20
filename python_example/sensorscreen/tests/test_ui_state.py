import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from ui_state import UiState, UiStateStore


def test_ui_state_round_trip(tmp_path: Path):
    state_path = tmp_path / "ui.state"
    store = UiStateStore(state_path)

    original = UiState(
        selected_screen=proto.UI_SCREEN_SENSORS,
        huskylens_algorithm_index=proto.HUSKYLENS_ALGORITHM_OBJECT_RECOGNITION,
        huskylens_illumination_enabled=True,
        huskylens_rgb_light_enabled=False,
        huskylens_display_enabled=True,
        servo_types=(
            proto.SERVO_TYPE_180,
            proto.SERVO_TYPE_270,
            proto.SERVO_TYPE_CONTINUOUS,
            proto.SERVO_TYPE_180,
            proto.SERVO_TYPE_270,
            proto.SERVO_TYPE_CONTINUOUS,
        ),
    )

    store.save(original)
    loaded = store.load()

    assert loaded == original


def test_ui_state_invalid_values_fall_back(tmp_path: Path):
    state_path = tmp_path / "ui.state"
    state_path.write_text(
        """
[ui]
selected_screen = 999
huskylens_algorithm_index = 999
huskylens_illumination_enabled = yes
huskylens_rgb_light_enabled = no
huskylens_display_enabled = maybe
s1_type = 0
s2_type = 1
s3_type = bad
s4_type = 0
s5_type = 1
s6_type = 2
""".strip()
    )

    loaded = UiStateStore(state_path).load()

    assert loaded.selected_screen is None
    assert loaded.huskylens_algorithm_index == proto.HUSKYLENS_ALGORITHM_MAX
    assert loaded.huskylens_illumination_enabled is True
    assert loaded.huskylens_rgb_light_enabled is False
    assert loaded.huskylens_display_enabled is False
    assert loaded.servo_types is None
