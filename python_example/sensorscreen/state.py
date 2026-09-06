"""Thread-safe latest-frame store shared between the UDP receiver thread and the render loop."""

from __future__ import annotations

import threading
import time

from protocol import GeomagFrame, HuskylensFrame, ImuBumpEvent, ImuFrame, LidarFrame

STALE_AFTER_S = 2.0


class SensorState:
    """Holds the most recent frame per sensor plus its arrival time, guarded by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.lidar_distance: LidarFrame | None = None
        self.lidar_distance_ts: float = 0.0
        self.lidar_intensity: LidarFrame | None = None
        self.lidar_intensity_ts: float = 0.0
        self.geomag: GeomagFrame | None = None
        self.geomag_ts: float = 0.0
        self.imu: ImuFrame | None = None
        self.imu_ts: float = 0.0
        self.imu_bump: ImuBumpEvent | None = None
        self.imu_bump_ts: float = 0.0
        self.huskylens: HuskylensFrame | None = None
        self.huskylens_ts: float = 0.0

    def set_lidar_distance(self, f: LidarFrame) -> None:
        with self._lock:
            self.lidar_distance = f
            self.lidar_distance_ts = time.monotonic()

    def set_lidar_intensity(self, f: LidarFrame) -> None:
        with self._lock:
            self.lidar_intensity = f
            self.lidar_intensity_ts = time.monotonic()

    def set_geomag(self, f: GeomagFrame) -> None:
        with self._lock:
            self.geomag = f
            self.geomag_ts = time.monotonic()

    def set_imu(self, f: ImuFrame) -> None:
        with self._lock:
            self.imu = f
            self.imu_ts = time.monotonic()

    def set_imu_bump(self, f: ImuBumpEvent) -> None:
        with self._lock:
            self.imu_bump = f
            self.imu_bump_ts = time.monotonic()

    def set_huskylens(self, f: HuskylensFrame) -> None:
        with self._lock:
            self.huskylens = f
            self.huskylens_ts = time.monotonic()

    def snapshot(self) -> "SensorSnapshot":
        now = time.monotonic()
        with self._lock:
            return SensorSnapshot(
                lidar_distance=self.lidar_distance,
                lidar_distance_fresh=self.lidar_distance is not None and (now - self.lidar_distance_ts) < STALE_AFTER_S,
                lidar_intensity=self.lidar_intensity,
                lidar_intensity_fresh=self.lidar_intensity is not None and (now - self.lidar_intensity_ts) < STALE_AFTER_S,
                geomag=self.geomag,
                geomag_fresh=self.geomag is not None and (now - self.geomag_ts) < STALE_AFTER_S,
                imu=self.imu,
                imu_fresh=self.imu is not None and (now - self.imu_ts) < STALE_AFTER_S,
                imu_bump=self.imu_bump,
                imu_bump_ts=self.imu_bump_ts,
                huskylens=self.huskylens,
                huskylens_fresh=self.huskylens is not None and (now - self.huskylens_ts) < STALE_AFTER_S,
            )


class SensorSnapshot:
    """Immutable copy of SensorState for a single render tick."""

    def __init__(self, *, lidar_distance, lidar_distance_fresh, lidar_intensity, lidar_intensity_fresh,
                 geomag, geomag_fresh, imu, imu_fresh, imu_bump, imu_bump_ts, huskylens, huskylens_fresh) -> None:
        self.lidar_distance = lidar_distance
        self.lidar_distance_fresh = lidar_distance_fresh
        self.lidar_intensity = lidar_intensity
        self.lidar_intensity_fresh = lidar_intensity_fresh
        self.geomag = geomag
        self.geomag_fresh = geomag_fresh
        self.imu = imu
        self.imu_fresh = imu_fresh
        self.imu_bump = imu_bump
        self.imu_bump_ts = imu_bump_ts
        self.huskylens = huskylens
        self.huskylens_fresh = huskylens_fresh
