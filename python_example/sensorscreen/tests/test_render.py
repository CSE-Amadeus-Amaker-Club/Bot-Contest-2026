import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from render import BG_COLOR, PANEL_H, PANEL_W, render_lidar_panel
from state import SensorSnapshot


def _snapshot_with_lidar(distance_values, intensity_values):
    distance = proto.LidarFrame(frame_id=1, timestamp_ms=1, values=distance_values)
    intensity = proto.LidarFrame(frame_id=1, timestamp_ms=1, values=intensity_values)
    return SensorSnapshot(
        lidar_distance=distance,
        lidar_distance_fresh=True,
        lidar_intensity=intensity,
        lidar_intensity_fresh=True,
        geomag=None,
        geomag_fresh=False,
        imu=None,
        imu_fresh=False,
        imu_bump=None,
        imu_bump_ts=0.0,
        huskylens=None,
        huskylens_fresh=False,
    )


def _find_bounds(mask):
    ys, xs = mask.nonzero()
    return xs.min(), xs.max(), ys.min(), ys.max()


def test_lidar_cells_are_square_and_centered():
    dist_values = [0] * proto.LIDAR_SCAN_POINTS
    dist_values[0] = 800
    dist_values[1] = 1000
    dist_values[proto.LIDAR_SCAN_COLS] = 1200

    int_values = [0] * proto.LIDAR_SCAN_POINTS
    int_values[0] = 32
    int_values[1] = 128
    int_values[proto.LIDAR_SCAN_COLS] = 255

    panel = render_lidar_panel(_snapshot_with_lidar(dist_values, int_values))

    assert panel.shape == (PANEL_H, PANEL_W, 3)

    bg = tuple(BG_COLOR)
    non_bg = (panel[:, :, 0] != bg[0]) | (panel[:, :, 1] != bg[1]) | (panel[:, :, 2] != bg[2])

    heatmap_w = PANEL_W - 20
    heatmap_h = (PANEL_H - 80) // 2
    cell_size = heatmap_w / proto.LIDAR_SCAN_COLS
    grid_h = proto.LIDAR_SCAN_ROWS * cell_size
    expected_margin = (heatmap_h - grid_h) / 2

    distance_region = non_bg[40:40 + heatmap_h, 10:10 + heatmap_w]
    intensity_region = non_bg[40 + heatmap_h + 8:40 + heatmap_h + 8 + heatmap_h, 10:10 + heatmap_w]

    dist_x_min_r, dist_x_max_r, dist_y_min_r, dist_y_max_r = _find_bounds(distance_region)
    int_x_min_r, int_x_max_r, int_y_min_r, int_y_max_r = _find_bounds(intensity_region)

    dist_x_min = dist_x_min_r + 10
    dist_x_max = dist_x_max_r + 10
    dist_y_min = dist_y_min_r + 40
    dist_y_max = dist_y_max_r + 40

    int_x_min = int_x_min_r + 10
    int_x_max = int_x_max_r + 10
    int_y_min = int_y_min_r + 40 + heatmap_h + 8
    int_y_max = int_y_max_r + 40 + heatmap_h + 8

    dist_top_margin = dist_y_min - 40
    dist_bottom_margin = (40 + heatmap_h) - dist_y_max
    int_top_margin = int_y_min - (40 + heatmap_h + 8)
    int_bottom_margin = (40 + heatmap_h + 8 + heatmap_h) - int_y_max

    for margin in (dist_top_margin, dist_bottom_margin, int_top_margin, int_bottom_margin):
        assert abs(margin - expected_margin) <= 1.5

    dist_cell_w = (dist_x_max - dist_x_min + 1) / proto.LIDAR_SCAN_COLS
    dist_cell_h = (dist_y_max - dist_y_min + 1) / proto.LIDAR_SCAN_ROWS
    int_cell_w = (int_x_max - int_x_min + 1) / proto.LIDAR_SCAN_COLS
    int_cell_h = (int_y_max - int_y_min + 1) / proto.LIDAR_SCAN_ROWS

    for w, h in ((dist_cell_w, dist_cell_h), (int_cell_w, int_cell_h)):
        assert abs(w - h) <= 0.25
