"""UDP client: master registration, heartbeat, and background frame receiver."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass

import protocol as proto
from capture import LidarCapture
from state import SensorState

logger = logging.getLogger("sensorscreen.udp")

HEARTBEAT_INTERVAL_S = 0.03  # well under the firmware's 50ms watchdog
COMMAND_TIMEOUT_S = 1.0
PACKET_RATE_WINDOW_S = 2.0


class MasterRegistrationError(RuntimeError):
    pass


@dataclass
class PacketStats:
    sent_total: int
    recv_total: int
    sent_rate: float
    recv_rate: float
    sent_byte_rate: float
    recv_byte_rate: float


@dataclass
class PendingCommand:
    data: bytes
    action: int
    status_key: str
    label: str
    coalesce_key: str | None = None
    sent_at: float | None = None


class SensorUDPClient:
    def __init__(self, ip: str, port: int, token: str, timeout: float, state: SensorState,
                 lidar_capture: LidarCapture | None = None) -> None:
        self.target = (ip, port)
        self.token = token
        self.timeout = timeout
        self.state = state
        self.lidar_capture = lidar_capture
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.sock.bind(("", 0))
        self._stop_event = threading.Event()
        self._send_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._command_queue: list[PendingCommand] = []
        self._inflight_command: PendingCommand | None = None
        self._command_status: dict[str, str] = {}
        self._heartbeat_thread: threading.Thread | None = None
        self._receiver_thread: threading.Thread | None = None
        self._stats_lock = threading.Lock()
        self._packets_out_total = 0
        self._packets_in_total = 0
        self._out_samples: deque[tuple[float, int]] = deque()
        self._in_samples: deque[tuple[float, int]] = deque()

    def _send(self, data: bytes, count: bool = True) -> None:
        with self._send_lock:
            self.sock.sendto(data, self.target)
        if count:
            self._record_packet(self._out_samples, len(data), outgoing=True)

    def _request(self, data: bytes) -> bytes | None:
        self._send(data)
        try:
            resp, _ = self.sock.recvfrom(2048)
            self._record_packet(self._in_samples, len(resp), outgoing=False)
            return resp
        except socket.timeout:
            return None

    def _record_packet(self, samples: deque[tuple[float, int]], size: int, outgoing: bool) -> None:
        now = time.monotonic()
        with self._stats_lock:
            samples.append((now, size))
            while samples and now - samples[0][0] > PACKET_RATE_WINDOW_S:
                samples.popleft()
            if outgoing:
                self._packets_out_total += 1
            else:
                self._packets_in_total += 1

    def stats(self) -> PacketStats:
        """Return accumulated packet/byte counts and rates averaged over the trailing window (heartbeats excluded from OUT)."""
        now = time.monotonic()
        with self._stats_lock:
            for samples in (self._out_samples, self._in_samples):
                while samples and now - samples[0][0] > PACKET_RATE_WINDOW_S:
                    samples.popleft()
            return PacketStats(
                sent_total=self._packets_out_total,
                recv_total=self._packets_in_total,
                sent_rate=len(self._out_samples) / PACKET_RATE_WINDOW_S,
                recv_rate=len(self._in_samples) / PACKET_RATE_WINDOW_S,
                sent_byte_rate=sum(size for _, size in self._out_samples) / PACKET_RATE_WINDOW_S,
                recv_byte_rate=sum(size for _, size in self._in_samples) / PACKET_RATE_WINDOW_S,
            )

    def register_master(self) -> None:
        # Firmware reply is the standard 2-byte ack: [action][resp_code].
        resp = self._request(proto.build_master_register(self.token))
        if resp is None or len(resp) < 2:
            raise MasterRegistrationError("No reply from bot during master registration (check ip/port)")
        status = resp[1]
        if status != proto.RESP_OK:
            name = proto.RESP_NAMES.get(status, hex(status))
            raise MasterRegistrationError(f"Master registration failed: {name}")

    def unregister(self) -> None:
        try:
            self._request(proto.build_master_unregister())
        except OSError:
            pass

    def enable_streams(self, lidar_hz: int, geomag_hz: int, imu_hz: int, huskylens_hz: int) -> None:
        for label, data in (
            ("lidar distance", proto.build_lidar_set_stream(True, lidar_hz)),
            ("lidar intensity", proto.build_lidar_set_stream_intensity(True, lidar_hz)),
            ("geomag", proto.build_geomag_set_stream(True, geomag_hz)),
            ("imu", proto.build_imu_set_stream(True, imu_hz)),
            ("huskylens", proto.build_huskylens_set_stream(True, huskylens_hz)),
        ):
            resp = self._request(data)
            if resp is None or len(resp) < 2 or resp[1] != proto.RESP_OK:
                logger.warning("Failed to enable %s streaming: %s", label, resp)

    def disable_streams(self) -> None:
        for data in (
            proto.build_lidar_set_stream(False, 0),
            proto.build_lidar_set_stream_intensity(False, 0),
            proto.build_geomag_set_stream(False, 0),
            proto.build_imu_set_stream(False, 1),
            proto.build_huskylens_set_stream(False, 0),
        ):
            try:
                self._send(data)
            except OSError:
                pass

    def configure_imu_bump(self, threshold_mg: int, debounce_ms: int) -> None:
        resp = self._request(proto.build_imu_set_bump_config(threshold_mg, debounce_ms))
        if resp is None or len(resp) < 2 or resp[1] != proto.RESP_OK:
            logger.warning("Failed to set IMU bump config: %s", resp)
            return
        readback = self._request(bytes([proto.make_action(proto.SERVICE_IMU, proto.IMU_CMD_GET_BUMP_CONFIG)]))
        parsed = proto.parse_imu_bump_config(readback) if readback else None
        if parsed is None:
            logger.warning("IMU bump config set but readback failed: %s", readback)
        else:
            logger.info("IMU bump config active: threshold=%d mg debounce=%d ms", parsed.threshold_mg, parsed.debounce_ms)

    def initialize_servos(self, servo_types: tuple[int, ...]) -> None:
        """Queue the configured type for every servo and stop continuous channels."""
        if len(servo_types) != proto.SERVO_COUNT:
            raise ValueError(f"expected {proto.SERVO_COUNT} servo types")
        for channel, servo_type in enumerate(servo_types):
            self.queue_set_servo_type(channel, servo_type)
            if servo_type == proto.SERVO_TYPE_CONTINUOUS:
                self.queue_set_servo_speed(channel, 0, force=True)

    def queue_set_servo_type(self, channel: int, servo_type: int) -> None:
        """Queue a servo mode update for one zero-based servo channel."""
        self._queue_command(
            proto.build_set_servo_type(self._servo_mask(channel), servo_type),
            f"servo-{channel}",
            f"S{channel + 1} mode",
            coalesce_key=f"mode-{channel}",
        )

    def queue_set_servo_speed(self, channel: int, speed: int, force: bool = False) -> None:
        """Queue a continuous-servo speed update, coalescing drag updates per channel."""
        self._queue_command(
            proto.build_set_servos_speed(self._servo_mask(channel), speed),
            f"servo-{channel}",
            f"S{channel + 1} speed",
            coalesce_key=f"motion-{channel}",
        )

    def queue_set_servo_angle(self, channel: int, angle: int, force: bool = False) -> None:
        """Queue a positional-servo angle update, coalescing drag updates per channel."""
        self._queue_command(
            proto.build_set_servos_angle(self._servo_mask(channel), angle),
            f"servo-{channel}",
            f"S{channel + 1} angle",
            coalesce_key=f"motion-{channel}",
        )

    def queue_set_led_color(self, led_mask: int, red: int, green: int, blue: int, brightness: int) -> None:
        """Queue a color update for one or more LEDs."""
        self._queue_command(
            proto.build_set_led_color(led_mask, red, green, blue, brightness),
            "led-color",
            f"LED 0x{led_mask:02X} color",
            coalesce_key="led-color",
        )

    def queue_set_huskylens_illumination(self, enabled: bool) -> None:
        """Queue a HuskyLens illumination LED state update."""
        self._queue_command(
            proto.build_huskylens_set_illumination(enabled),
            "huskylens-illumination",
            "HuskyLens illumination",
            coalesce_key="huskylens-illumination",
        )

    def queue_set_huskylens_algorithm(self, algorithm: int) -> None:
        """Queue a HuskyLens algorithm switch, retaining only the latest request."""
        self._queue_command(
            proto.build_huskylens_set_algorithm(algorithm),
            "huskylens-algorithm",
            "HuskyLens algorithm",
            coalesce_key="huskylens-algorithm",
        )

    def queue_set_huskylens_rgb_light(self, enabled: bool) -> None:
        """Queue a HuskyLens RGB/status-light request without touching K10 LEDs."""
        self._queue_command(
            proto.build_huskylens_set_rgb_light(enabled),
            "huskylens-rgb-light",
            "HuskyLens RGB light",
            coalesce_key="huskylens-rgb-light",
        )

    def queue_set_huskylens_display(self, enabled: bool) -> None:
        """Queue a HuskyLens LCD/display request without touching the K10 screen."""
        self._queue_command(
            proto.build_huskylens_set_display(enabled),
            "huskylens-display",
            "HuskyLens display",
            coalesce_key="huskylens-display",
        )

    def queue_set_screen(self, screen: int) -> None:
        """Queue selection of a named screen on the physical K10 display."""
        self._queue_command(
            proto.build_ui_set_screen(screen),
            "k10-screen",
            "K10 screen",
            coalesce_key="k10-screen",
        )

    def queue_stop_all_motors(self) -> None:
        """Prioritize the firmware emergency stop over queued movement commands."""
        self._queue_command(
            proto.build_stop_all_motors(),
            "stop-all",
            "STOP ALL",
            priority=True,
            discard_queued=True,
        )

    def command_status(self, status_key: str) -> str:
        """Return the latest acknowledgement state for a control surface item."""
        with self._command_lock:
            return self._command_status.get(status_key, "READY")

    def _servo_mask(self, channel: int) -> int:
        if not 0 <= channel < proto.SERVO_COUNT:
            raise ValueError(f"channel must be in 0..{proto.SERVO_COUNT - 1}")
        return 1 << channel

    def _queue_command(
        self,
        data: bytes,
        status_key: str,
        label: str,
        coalesce_key: str | None = None,
        priority: bool = False,
        discard_queued: bool = False,
    ) -> None:
        command = PendingCommand(data, data[0], status_key, label, coalesce_key)
        with self._command_lock:
            if discard_queued:
                for queued in self._command_queue:
                    self._command_status[queued.status_key] = "CANCELLED"
                self._command_queue.clear()
            elif coalesce_key is not None:
                self._command_queue = [
                    queued for queued in self._command_queue if queued.coalesce_key != coalesce_key
                ]
            self._command_status[status_key] = "QUEUED"
            if priority:
                self._command_queue.insert(0, command)
            else:
                self._command_queue.append(command)
            self._send_next_command_locked()

    def _send_next_command_locked(self) -> None:
        while self._inflight_command is None and self._command_queue:
            command = self._command_queue.pop(0)
            command.sent_at = time.monotonic()
            self._inflight_command = command
            self._command_status[command.status_key] = "SENT"
            try:
                self._send(command.data)
            except OSError:
                self._command_status[command.status_key] = "SEND FAILED"
                self._inflight_command = None

    def _expire_inflight_command(self) -> None:
        with self._command_lock:
            command = self._inflight_command
            if command is None or command.sent_at is None:
                return
            if time.monotonic() - command.sent_at < COMMAND_TIMEOUT_S:
                return
            self._command_status[command.status_key] = "TIMEOUT"
            self._inflight_command = None
            self._send_next_command_locked()

    def start(self) -> None:
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._heartbeat_thread.start()
        self._receiver_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        for t in (self._heartbeat_thread, self._receiver_thread):
            if t is not None:
                t.join(timeout=1.0)
        self.sock.close()

    def _heartbeat_loop(self) -> None:
        heartbeat = proto.build_heartbeat()
        while not self._stop_event.is_set():
            try:
                self._send(heartbeat, count=False)
            except OSError:
                pass
            time.sleep(HEARTBEAT_INTERVAL_S)

    def _receive_loop(self) -> None:
        # Shares self.sock; only called after register_master()/enable_streams()
        # request/response exchanges are done, so there's no race on reads.
        self.sock.settimeout(0.5)
        while not self._stop_event.is_set():
            try:
                frame, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                self._expire_inflight_command()
                continue
            except OSError:
                break
            self._record_packet(self._in_samples, len(frame), outgoing=False)
            self._expire_inflight_command()
            self._dispatch(frame)

    def _dispatch(self, frame: bytes) -> None:
        if not frame:
            return
        action = frame[0]
        if len(frame) >= 2:
            with self._command_lock:
                command = self._inflight_command
                if command is not None and action == command.action:
                    status = frame[1]
                    self._command_status[command.status_key] = (
                        "OK" if status == proto.RESP_OK else proto.RESP_NAMES.get(status, hex(status))
                    )
                    self._inflight_command = None
                    self._send_next_command_locked()
                    return
        if action == proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_FRAME_CMD):
            parsed = proto.parse_lidar_frame(frame)
            if parsed:
                if self.lidar_capture is not None:
                    self.lidar_capture.write(parsed)
                self.state.set_lidar_distance(parsed)
        elif action == proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_INTENSITY_FRAME_CMD):
            parsed = proto.parse_lidar_frame(frame)
            if parsed:
                self.state.set_lidar_intensity(parsed)
        elif action == proto.make_action(proto.SERVICE_GEOMAG, proto.GEOMAG_STREAM_FRAME_CMD):
            parsed = proto.parse_geomag_frame(frame)
            if parsed:
                self.state.set_geomag(parsed)
        elif action == proto.make_action(proto.SERVICE_IMU, proto.IMU_STREAM_FRAME_CMD):
            parsed = proto.parse_imu_frame(frame)
            if parsed:
                self.state.set_imu(parsed)
        elif action == proto.make_action(proto.SERVICE_IMU, proto.IMU_BUMP_EVENT_CMD):
            parsed = proto.parse_imu_bump_event(frame)
            if parsed:
                logger.info("IMU bump: dir=%s x=%d y=%d z=%d", proto.bump_dir_label(parsed.bump_dir),
                            parsed.accel_x_mg, parsed.accel_y_mg, parsed.accel_z_mg)
                self.state.set_imu_bump(parsed)
        elif action == proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_STREAM_FRAME_CMD):
            parsed = proto.parse_huskylens_frame(frame)
            if parsed:
                self.state.set_huskylens(parsed)
