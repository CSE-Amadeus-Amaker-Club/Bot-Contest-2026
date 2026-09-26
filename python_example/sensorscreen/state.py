"""Thread-safe latest-frame store shared between the UDP receiver thread and the render loop."""

from __future__ import annotations

from collections import deque
import threading
import time

from protocol import GeomagFrame, HuskylensFrame, ImuBumpEvent, ImuFrame, LidarFrame

STALE_AFTER_S = 2.0
RATE_WINDOW_S = 2.5


class SensorState:
    """Holds the most recent frame per sensor plus its arrival time, guarded by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.lidar_distance: LidarFrame | None = None
        self.lidar_distance_ts: float = 0.0
        self._lidar_distance_arrivals: deque[float] = deque()
        self.lidar_intensity: LidarFrame | None = None
        self.lidar_intensity_ts: float = 0.0
        self._lidar_intensity_arrivals: deque[float] = deque()
        self.geomag: GeomagFrame | None = None
        self.geomag_ts: float = 0.0
        self._geomag_arrivals: deque[float] = deque()
        self.imu: ImuFrame | None = None
        self.imu_ts: float = 0.0
        self._imu_arrivals: deque[float] = deque()
        self.imu_bump: ImuBumpEvent | None = None
        self.imu_bump_ts: float = 0.0
        self.huskylens: HuskylensFrame | None = None
        self.huskylens_ts: float = 0.0
        self._huskylens_arrivals: deque[float] = deque()

    def _mark_arrival(self, arrivals: deque[float]) -> float:
        now = time.monotonic()
        arrivals.append(now)
        cutoff = now - RATE_WINDOW_S
        while arrivals and arrivals[0] < cutoff:
            arrivals.popleft()
        return now

    @staticmethod
    def _rate_hz(arrivals: deque[float]) -> float:
        if len(arrivals) < 2:
            return 0.0
        span = arrivals[-1] - arrivals[0]
        if span <= 0.0:
            return 0.0
        return (len(arrivals) - 1) / span

    def set_lidar_distance(self, f: LidarFrame) -> None:
        with self._lock:
            self.lidar_distance = f
            self.lidar_distance_ts = self._mark_arrival(self._lidar_distance_arrivals)

    def set_lidar_intensity(self, f: LidarFrame) -> None:
        with self._lock:
            self.lidar_intensity = f
            self.lidar_intensity_ts = self._mark_arrival(self._lidar_intensity_arrivals)

    def set_geomag(self, f: GeomagFrame) -> None:
        with self._lock:
            self.geomag = f
            self.geomag_ts = self._mark_arrival(self._geomag_arrivals)

    def set_imu(self, f: ImuFrame) -> None:
        with self._lock:
            self.imu = f
            self.imu_ts = self._mark_arrival(self._imu_arrivals)

    def set_imu_bump(self, f: ImuBumpEvent) -> None:
        with self._lock:
            self.imu_bump = f
            self.imu_bump_ts = time.monotonic()

    def set_huskylens(self, f: HuskylensFrame) -> None:
        with self._lock:
            self.huskylens = f
            self.huskylens_ts = self._mark_arrival(self._huskylens_arrivals)

    def snapshot(self) -> "SensorSnapshot":
        now = time.monotonic()
        with self._lock:
            return SensorSnapshot(
                lidar_distance=self.lidar_distance,
                lidar_distance_fresh=self.lidar_distance is not None and (now - self.lidar_distance_ts) < STALE_AFTER_S,
                lidar_distance_hz=self._rate_hz(self._lidar_distance_arrivals),
                lidar_intensity=self.lidar_intensity,
                lidar_intensity_fresh=self.lidar_intensity is not None and (now - self.lidar_intensity_ts) < STALE_AFTER_S,
                lidar_intensity_hz=self._rate_hz(self._lidar_intensity_arrivals),
                geomag=self.geomag,
                geomag_fresh=self.geomag is not None and (now - self.geomag_ts) < STALE_AFTER_S,
                geomag_hz=self._rate_hz(self._geomag_arrivals),
                imu=self.imu,
                imu_fresh=self.imu is not None and (now - self.imu_ts) < STALE_AFTER_S,
                imu_hz=self._rate_hz(self._imu_arrivals),
                imu_bump=self.imu_bump,
                imu_bump_ts=self.imu_bump_ts,
                huskylens=self.huskylens,
                huskylens_fresh=self.huskylens is not None and (now - self.huskylens_ts) < STALE_AFTER_S,
                huskylens_hz=self._rate_hz(self._huskylens_arrivals),
            )


class SensorSnapshot:
    """Immutable copy of SensorState for a single render tick."""

    def __init__(self, *, lidar_distance, lidar_distance_fresh, lidar_intensity, lidar_intensity_fresh,
                 geomag, geomag_fresh, imu, imu_fresh, imu_bump, imu_bump_ts, huskylens, huskylens_fresh,
                 lidar_distance_hz, lidar_intensity_hz, geomag_hz, imu_hz, huskylens_hz) -> None:
        self.lidar_distance = lidar_distance
        self.lidar_distance_fresh = lidar_distance_fresh
        self.lidar_distance_hz = lidar_distance_hz
        self.lidar_intensity = lidar_intensity
        self.lidar_intensity_fresh = lidar_intensity_fresh
        self.lidar_intensity_hz = lidar_intensity_hz
        self.geomag = geomag
        self.geomag_fresh = geomag_fresh
        self.geomag_hz = geomag_hz
        self.imu = imu
        self.imu_fresh = imu_fresh
        self.imu_hz = imu_hz
        self.imu_bump = imu_bump
        self.imu_bump_ts = imu_bump_ts
        self.huskylens = huskylens
        self.huskylens_fresh = huskylens_fresh
        self.huskylens_hz = huskylens_hz
