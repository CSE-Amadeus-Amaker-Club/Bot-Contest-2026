"""OpenCV rendering of the 4 sensor panels into a single dashboard image."""

from __future__ import annotations

import math
import time

import cv2
import numpy as np

import protocol as proto
from screen_controls import SCREEN_BAND_H
from sound_controls import SOUND_BAND_H
from servo_controls import SERVO_BAND_H
from state import SensorSnapshot

# ─── Layout: 2x2 grid, each panel comfortably larger than the on-device 240x320 screen ──
PANEL_W = 480
PANEL_H = 420
PANEL_H_BOTTOM = PANEL_H // 2  # IMU/Geomag row is half as tall as the HuskyLens/Lidar row
GRID_GAP = 8
WINDOW_W = PANEL_W * 2 + GRID_GAP * 3
TOP_BAR_H = 32
SOUND_BAND_TOP = TOP_BAR_H
SCREEN_BAND_TOP = SOUND_BAND_TOP + SOUND_BAND_H
SENSOR_GRID_TOP = SCREEN_BAND_TOP + SCREEN_BAND_H
STATUS_BAR_H = 28
SENSOR_GRID_H = PANEL_H + PANEL_H_BOTTOM + GRID_GAP * 3
SERVO_BAND_TOP = SENSOR_GRID_TOP + SENSOR_GRID_H + GRID_GAP
STATUS_BAR_TOP = SERVO_BAND_TOP + SERVO_BAND_H + GRID_GAP
WINDOW_H = STATUS_BAR_TOP + STATUS_BAR_H

BG_COLOR = (30, 30, 30)
TITLE_COLOR = (220, 220, 220)
STALE_COLOR = (90, 90, 90)
FONT = cv2.FONT_HERSHEY_SIMPLEX

# Lidar distance gradient: 300mm (red) -> 1900mm (white); 0/under-range -> dark gray
LIDAR_MIN_DIST = 300
LIDAR_MAX_DIST = 1900
LIDAR_DARK = (40, 40, 40)  # BGR

# Lidar intensity gradient: 0 (dark blue) -> 255 (cyan)
LIDAR_INTENSITY_MAX = 255

BUMP_FLASH_S = 1.5
BUMP_COLOR = (0, 90, 255)  # BGR orange-red
BUMP_TEXT_COLOR = (255, 255, 255)


def _new_panel(height: int = PANEL_H) -> np.ndarray:
    panel = np.zeros((height, PANEL_W, 3), dtype=np.uint8)
    panel[:] = BG_COLOR
    return panel


def _title(panel: np.ndarray, text: str, fresh: bool) -> None:
    color = TITLE_COLOR if fresh else STALE_COLOR
    cv2.putText(panel, text, (10, 24), FONT, 0.6, color, 1, cv2.LINE_AA)


def _distance_color(mm: int) -> tuple[int, int, int]:
    """Return a BGR color for a distance in mm, matching the firmware red->white gradient."""
    if mm == 0 or mm < LIDAR_MIN_DIST:
        return LIDAR_DARK
    if mm > LIDAR_MAX_DIST:
        return (255, 255, 255)
    t = (mm - LIDAR_MIN_DIST) / (LIDAR_MAX_DIST - LIDAR_MIN_DIST)
    # red (0,0,255) -> white (255,255,255) in BGR
    g_b = int(255 * t)
    return (g_b, g_b, 255)


def _intensity_color(value: int) -> tuple[int, int, int]:
    """BGR color for intensity 0-255, matching firmware dark-blue -> cyan gradient."""
    t = max(0.0, min(1.0, value / LIDAR_INTENSITY_MAX))
    # dark blue (0x08,0x41 ~ (66,8,4) approx) -> cyan (255,255,0) in BGR; keep it simple/linear
    b = int(90 + 165 * t)
    g = int(255 * t)
    return (b, g, 0)


def render_lidar_panel(snapshot: SensorSnapshot) -> np.ndarray:
    panel = _new_panel()
    fresh = snapshot.lidar_distance_fresh or snapshot.lidar_intensity_fresh
    _title(panel, "Lidar (64x8)", fresh)

    heatmap_w = PANEL_W - 20
    heatmap_h = (PANEL_H - 80) // 2
    cell_w = heatmap_w / proto.LIDAR_SCAN_COLS
    cell_h = heatmap_h / proto.LIDAR_SCAN_ROWS

    min_mm = None
    valid_points = 0

    if snapshot.lidar_distance is not None:
        values = snapshot.lidar_distance.values
        y0 = 40
        for row in range(proto.LIDAR_SCAN_ROWS):
            for col in range(proto.LIDAR_SCAN_COLS):
                idx = row * proto.LIDAR_SCAN_COLS + col
                mm = values[idx] if idx < len(values) else 0
                if mm > 0:
                    valid_points += 1
                    min_mm = mm if min_mm is None else min(min_mm, mm)
                x1, y1 = int(10 + col * cell_w), int(y0 + row * cell_h)
                x2, y2 = int(10 + (col + 1) * cell_w), int(y0 + (row + 1) * cell_h)
                cv2.rectangle(panel, (x1, y1), (x2, y2), _distance_color(mm), -1)

    if snapshot.lidar_intensity is not None:
        values = snapshot.lidar_intensity.values
        y0 = 40 + heatmap_h + 8
        for row in range(proto.LIDAR_SCAN_ROWS):
            for col in range(proto.LIDAR_SCAN_COLS):
                idx = row * proto.LIDAR_SCAN_COLS + col
                val = values[idx] if idx < len(values) else 0
                x1, y1 = int(10 + col * cell_w), int(y0 + row * cell_h)
                x2, y2 = int(10 + (col + 1) * cell_w), int(y0 + (row + 1) * cell_h)
                cv2.rectangle(panel, (x1, y1), (x2, y2), _intensity_color(val), -1)

    status = f"UDP:{'ON' if fresh else 'OFF'} Min:{f'{min_mm}mm' if min_mm else '---'} Hits:{valid_points}"
    cv2.putText(panel, status, (10, PANEL_H - 12), FONT, 0.5, TITLE_COLOR if fresh else STALE_COLOR, 1, cv2.LINE_AA)
    return panel


def render_imu_panel(snapshot: SensorSnapshot) -> np.ndarray:
    panel = _new_panel(PANEL_H_BOTTOM)
    _title(panel, "IMU (accel)", snapshot.imu_fresh)
    if snapshot.imu is None:
        cv2.putText(panel, "NO DATA", (10, 60), FONT, 0.7, STALE_COLOR, 1, cv2.LINE_AA)
        return panel

    imu = snapshot.imu
    magnitude = math.sqrt(imu.accel_x_mg ** 2 + imu.accel_y_mg ** 2 + imu.accel_z_mg ** 2)
    color = TITLE_COLOR if snapshot.imu_fresh else STALE_COLOR
    lines = [
        f"X: {imu.accel_x_mg:6d} mg",
        f"Y: {imu.accel_y_mg:6d} mg",
        f"Z: {imu.accel_z_mg:6d} mg",
        f"|a|: {magnitude:7.1f} mg",
    ]
    for i, line in enumerate(lines):
        cv2.putText(panel, line, (10, 46 + i * 18), FONT, 0.45, color, 1, cv2.LINE_AA)

    # 2D vector indicator for X/Y tilt, placed to the right of the readout text.
    cx, cy, r = int(PANEL_W * 0.74), PANEL_H_BOTTOM // 2 + 6, 42
    cv2.circle(panel, (cx, cy), r, color, 1, cv2.LINE_AA)
    scale = r / 1000.0  # 1000mg maps to the circle radius
    dx = int(max(-r, min(r, imu.accel_x_mg * scale)))
    dy = int(max(-r, min(r, -imu.accel_y_mg * scale)))
    cv2.arrowedLine(panel, (cx, cy), (cx + dx, cy + dy), (0, 200, 255), 2, cv2.LINE_AA, tipLength=0.2)

    if snapshot.imu_bump is not None:
        elapsed = time.monotonic() - snapshot.imu_bump_ts
        if elapsed < BUMP_FLASH_S:
            alpha = 1.0 - elapsed / BUMP_FLASH_S
            banner = panel[0:36, 0:PANEL_W].copy()
            overlay = np.full_like(banner, BUMP_COLOR, dtype=np.uint8)
            cv2.addWeighted(overlay, alpha, banner, 1 - alpha, 0, dst=banner)
            panel[0:36, 0:PANEL_W] = banner
            bump = snapshot.imu_bump
            shock_mg = math.sqrt(
                bump.accel_x_mg ** 2 + bump.accel_y_mg ** 2 + bump.accel_z_mg ** 2
            )
            label = f"SHOCK {proto.bump_dir_label(bump.bump_dir)}  {shock_mg / 1000.0:.2f}g"
            cv2.putText(panel, label, (10, 24), FONT, 0.6, BUMP_TEXT_COLOR, 1, cv2.LINE_AA)
    return panel


def render_geomag_panel(snapshot: SensorSnapshot) -> np.ndarray:
    panel = _new_panel(PANEL_H_BOTTOM)
    _title(panel, "Geomag (compass)", snapshot.geomag_fresh)
    if snapshot.geomag is None:
        cv2.putText(panel, "NO DATA", (10, 60), FONT, 0.7, STALE_COLOR, 1, cv2.LINE_AA)
        return panel

    geomag = snapshot.geomag
    color = TITLE_COLOR if snapshot.geomag_fresh else STALE_COLOR
    lines = [
        f"Heading: {geomag.heading_deg:3d} deg",
        f"X: {geomag.field_x_ut:5d} uT",
        f"Y: {geomag.field_y_ut:5d} uT",
        f"Z: {geomag.field_z_ut:5d} uT",
    ]
    for i, line in enumerate(lines):
        cv2.putText(panel, line, (10, 46 + i * 18), FONT, 0.45, color, 1, cv2.LINE_AA)

    cx, cy, r = int(PANEL_W * 0.74), PANEL_H_BOTTOM // 2 + 6, 42
    cv2.circle(panel, (cx, cy), r, color, 1, cv2.LINE_AA)
    angle_rad = math.radians(geomag.heading_deg - 90)  # 0deg = up
    needle = (cx + int(r * math.cos(angle_rad)), cy + int(r * math.sin(angle_rad)))
    cv2.arrowedLine(panel, (cx, cy), needle, (0, 165, 255), 2, cv2.LINE_AA, tipLength=0.2)
    cv2.putText(panel, "N", (cx - 6, cy - r - 8), FONT, 0.5, color, 1, cv2.LINE_AA)
    return panel


def render_huskylens_panel(snapshot: SensorSnapshot, huskylens_controls) -> np.ndarray:
    panel = _new_panel()
    _title(panel, "HuskyLens", snapshot.huskylens_fresh)
    huskylens_controls.render(panel)
    if snapshot.huskylens is None:
        cv2.putText(panel, "NO DATA", (10, 60), FONT, 0.7, STALE_COLOR, 1, cv2.LINE_AA)
        return panel

    hl = snapshot.huskylens
    lens_x0, lens_y0 = 10, 40
    lens_w, lens_h = PANEL_W - 20, PANEL_H - 60
    scale_x = lens_w / proto.HUSKYLENS_LENS_WIDTH
    scale_y = lens_h / proto.HUSKYLENS_LENS_HEIGHT
    cv2.rectangle(panel, (lens_x0, lens_y0), (lens_x0 + lens_w, lens_y0 + lens_h), (80, 80, 80), 1)

    for block in hl.blocks:
        x = int(lens_x0 + (block.x_center - block.width / 2) * scale_x)
        y = int(lens_y0 + (block.y_center - block.height / 2) * scale_y)
        w = int(block.width * scale_x)
        h = int(block.height * scale_y)
        cv2.rectangle(panel, (x, y), (x + w, y + h), (0, 255, 255), 2)
        cv2.putText(panel, f"#{block.id}", (x, max(lens_y0, y - 6)), FONT, 0.5, (0, 255, 255), 1, cv2.LINE_AA)

    for arrow in hl.arrows:
        p0 = (int(lens_x0 + arrow.x_origin * scale_x), int(lens_y0 + arrow.y_origin * scale_y))
        p1 = (int(lens_x0 + arrow.x_target * scale_x), int(lens_y0 + arrow.y_target * scale_y))
        cv2.arrowedLine(panel, p0, p1, (255, 255, 0), 2, cv2.LINE_AA, tipLength=0.2)

    if not hl.connected:
        cv2.putText(panel, "DISCONNECTED", (lens_x0 + 10, lens_y0 + 30), FONT, 0.6, (0, 0, 255), 1, cv2.LINE_AA)
    return panel


def compose_dashboard(snapshot: SensorSnapshot, servo_controls, huskylens_controls, screen_controls, sound_controls, packet_stats) -> np.ndarray:
    window = np.zeros((WINDOW_H, WINDOW_W, 3), dtype=np.uint8)
    window[:] = (15, 15, 15)

    cv2.putText(window, "aMaker UDP Bot", (12, TOP_BAR_H - 10), FONT, 0.7, TITLE_COLOR, 1, cv2.LINE_AA)

    panels = [
        render_huskylens_panel(snapshot, huskylens_controls),
        render_lidar_panel(snapshot),
        render_imu_panel(snapshot),
        render_geomag_panel(snapshot),
    ]
    positions = [
        (GRID_GAP, SENSOR_GRID_TOP + GRID_GAP),
        (GRID_GAP * 2 + PANEL_W, SENSOR_GRID_TOP + GRID_GAP),
        (GRID_GAP, SENSOR_GRID_TOP + GRID_GAP * 2 + PANEL_H),
        (GRID_GAP * 2 + PANEL_W, SENSOR_GRID_TOP + GRID_GAP * 2 + PANEL_H),
    ]
    for panel, (x, y) in zip(panels, positions):
        h = panel.shape[0]
        window[y:y + h, x:x + PANEL_W] = panel
    window[SOUND_BAND_TOP:SOUND_BAND_TOP + SOUND_BAND_H, 0:480] = sound_controls.render()
    window[SCREEN_BAND_TOP:SCREEN_BAND_TOP + SCREEN_BAND_H, :] = screen_controls.render()
    window[SERVO_BAND_TOP:SERVO_BAND_TOP + SERVO_BAND_H, :] = servo_controls.render()

    status_text = (
        f"UDP IN: {packet_stats.recv_total:,} ({packet_stats.recv_rate:.1f}/s, {_format_bps(packet_stats.recv_byte_rate)})"
        f"   OUT: {packet_stats.sent_total:,} ({packet_stats.sent_rate:.1f}/s, {_format_bps(packet_stats.sent_byte_rate)})"
    )
    cv2.putText(window, status_text, (12, STATUS_BAR_TOP + STATUS_BAR_H - 9), FONT, 0.55, TITLE_COLOR, 1, cv2.LINE_AA)
    return window


def _format_bps(byte_rate: float) -> str:
    """Human-readable bytes/sec, switching to KB/s above 1024 B/s."""
    if byte_rate >= 1024:
        return f"{byte_rate / 1024:.1f} KB/s"
    return f"{byte_rate:.0f} B/s"
