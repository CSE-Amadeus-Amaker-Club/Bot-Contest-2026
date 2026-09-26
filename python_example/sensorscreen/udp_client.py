"""UDP client: master registration, heartbeat, and background frame receiver."""

from __future__ import annotations

import logging
import math
import socket
import threading
import time
from collections.abc import Callable
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
    require_ack: bool = True
    sent_at: float | None = None


class SensorUDPClient:
    def __init__(self, ip: str, port: int, token: str, timeout: float, state: SensorState,
                 lidar_capture: LidarCapture | None = None,
                 fire_and_forget: bool = False) -> None:
        self.target = (ip, port)
        self.token = token
        self.timeout = timeout
        self.state = state
        self.lidar_capture = lidar_capture
        self.fire_and_forget = fire_and_forget
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
        self._master_registered = False
        self._rx_message_callback: Callable[[str], None] | None = None

    def set_rx_message_callback(self, callback: Callable[[str], None] | None) -> None:
        """Attach a callback that receives one decoded line per incoming UDP frame."""
        self._rx_message_callback = callback

    def _notify_rx_message(self, frame: bytes) -> None:
        callback = self._rx_message_callback
        if callback is None:
            return
        try:
            callback(self._decode_rx_frame(frame))
        except Exception:
            # Never let diagnostics callbacks interfere with control loops.
            pass

    def _decode_rx_frame(self, frame: bytes) -> str:
        if not frame:
            return "RX empty frame"

        action = frame[0]
        action_name = self._action_name(action)
        base = f"RX 0x{action:02X} {action_name}"

        if action == proto.make_action(proto.SERVICE_AMAKER, proto.CMD_PING):
            payload = frame[1:5]
            ping_hex = payload.hex() if payload else ""
            return f"{base} ping={ping_hex} len={len(frame)}"

        if len(frame) < 2:
            return f"{base} malformed len={len(frame)}"

        status = frame[1]
        status_name = proto.RESP_NAMES.get(status, f"0x{status:02X}")

        if action == proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_FRAME_CMD):
            parsed = proto.parse_lidar_frame(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed lidar"
            return (
                f"{base} status={status_name} frame={parsed.frame_id} ts={parsed.timestamp_ms} "
                f"points={len(parsed.values)}"
            )

        if action == proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_INTENSITY_FRAME_CMD):
            parsed = proto.parse_lidar_frame(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed lidar-intensity"
            return (
                f"{base} status={status_name} frame={parsed.frame_id} ts={parsed.timestamp_ms} "
                f"points={len(parsed.values)}"
            )

        if action == proto.make_action(proto.SERVICE_GEOMAG, proto.GEOMAG_STREAM_FRAME_CMD):
            parsed = proto.parse_geomag_frame(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed geomag"
            return (
                f"{base} status={status_name} frame={parsed.frame_id} heading={parsed.heading_deg} "
                f"x={parsed.field_x_ut} y={parsed.field_y_ut} z={parsed.field_z_ut}"
            )

        if action == proto.make_action(proto.SERVICE_IMU, proto.IMU_STREAM_FRAME_CMD):
            parsed = proto.parse_imu_frame(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed imu"
            return (
                f"{base} status={status_name} sample={parsed.sample_id} "
                f"x={parsed.accel_x_mg} y={parsed.accel_y_mg} z={parsed.accel_z_mg}"
            )

        if action == proto.make_action(proto.SERVICE_IMU, proto.IMU_BUMP_EVENT_CMD):
            parsed = proto.parse_imu_bump_event(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed imu-bump"
            return (
                f"{base} status={status_name} sample={parsed.sample_id} dir={proto.bump_dir_label(parsed.bump_dir)} "
                f"x={parsed.accel_x_mg} y={parsed.accel_y_mg} z={parsed.accel_z_mg}"
            )

        if action == proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_STREAM_FRAME_CMD):
            parsed = proto.parse_huskylens_frame(frame)
            if parsed is None:
                return f"{base} status={status_name} malformed huskylens"
            return (
                f"{base} status={status_name} frame={parsed.frame_number} "
                f"size={parsed.width}x{parsed.height} blocks={len(parsed.blocks)} arrows={len(parsed.arrows)}"
            )

        if action == proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_STATUS):
            parsed = proto.parse_sound_status(frame)
            if parsed is None:
                return f"{base} status={status_name} payload={frame[2:].hex()}"
            return f"{base} status={status_name} playing={'yes' if parsed.playing else 'no'}"

        payload = frame[2:]
        payload_hex = payload.hex()
        if len(payload_hex) > 64:
            payload_hex = f"{payload_hex[:64]}..."
        return f"{base} status={status_name} payload={payload_hex}"

    def _action_name(self, action: int) -> str:
        names = {
            proto.make_action(proto.SERVICE_AMAKER, proto.CMD_MASTER_REGISTER): "master.register",
            proto.make_action(proto.SERVICE_AMAKER, proto.CMD_MASTER_UNREGISTER): "master.unregister",
            proto.make_action(proto.SERVICE_AMAKER, proto.CMD_HEARTBEAT): "master.heartbeat",
            proto.make_action(proto.SERVICE_AMAKER, proto.CMD_PING): "master.ping",
            proto.make_action(proto.SERVICE_MOTOR_SERVO, proto.MOTOR_SERVO_CMD_SET_SERVO_TYPE): "servo.set_type",
            proto.make_action(proto.SERVICE_MOTOR_SERVO, proto.MOTOR_SERVO_CMD_SET_SERVOS_SPEED): "servo.set_speed",
            proto.make_action(proto.SERVICE_MOTOR_SERVO, proto.MOTOR_SERVO_CMD_SET_SERVOS_ANGLE): "servo.set_angle",
            proto.make_action(proto.SERVICE_MOTOR_SERVO, proto.MOTOR_SERVO_CMD_STOP_ALL_MOTORS): "servo.stop_all",
            proto.make_action(proto.SERVICE_LED, proto.LED_CMD_SET_COLOR): "led.set_color",
            proto.make_action(proto.SERVICE_UI, proto.UI_CMD_SET_SCREEN): "ui.set_screen",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_CMD_SET_ILLUMINATION): "huskylens.set_illumination",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_CMD_SET_STREAM): "huskylens.set_stream",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_CMD_SET_ALGORITHM): "huskylens.set_algorithm",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_CMD_SET_RGB_LIGHT): "huskylens.set_rgb_light",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_CMD_SET_DISPLAY): "huskylens.set_display",
            proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_STREAM_FRAME_CMD): "huskylens.stream",
            proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_CMD_SET_STREAM): "lidar.set_stream",
            proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_CMD_SET_STREAM_INTENSITY): "lidar.set_stream_intensity",
            proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_FRAME_CMD): "lidar.stream_distance",
            proto.make_action(proto.SERVICE_LIDAR, proto.LIDAR_STREAM_INTENSITY_FRAME_CMD): "lidar.stream_intensity",
            proto.make_action(proto.SERVICE_GEOMAG, proto.GEOMAG_CMD_SET_STREAM): "geomag.set_stream",
            proto.make_action(proto.SERVICE_GEOMAG, proto.GEOMAG_STREAM_FRAME_CMD): "geomag.stream",
            proto.make_action(proto.SERVICE_IMU, proto.IMU_CMD_SET_STREAM): "imu.set_stream",
            proto.make_action(proto.SERVICE_IMU, proto.IMU_CMD_SET_BUMP_CONFIG): "imu.set_bump_config",
            proto.make_action(proto.SERVICE_IMU, proto.IMU_CMD_GET_BUMP_CONFIG): "imu.get_bump_config",
            proto.make_action(proto.SERVICE_IMU, proto.IMU_STREAM_FRAME_CMD): "imu.stream",
            proto.make_action(proto.SERVICE_IMU, proto.IMU_BUMP_EVENT_CMD): "imu.bump",
            proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_PLAY): "sound.play",
            proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_STOP): "sound.stop",
            proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_STATUS): "sound.status",
            proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_VOLUME): "sound.volume",
        }
        if action in names:
            return names[action]
        return f"svc{proto.action_service(action)}.cmd{proto.action_cmd(action)}"

    def _send(self, data: bytes, count: bool = True) -> None:
        with self._send_lock:
            self.sock.sendto(data, self.target)
        if count:
            self._record_packet(self._out_samples, len(data), outgoing=True)

    def _request(self, data: bytes, expected_action: int | None = None) -> bytes | None:
        """Send one request and wait for the matching action reply.

        Some services can emit asynchronous stream frames while setup commands
        are in flight. Ignore unrelated actions until timeout so those frames
        are not mistaken for this command's ACK.
        """
        if expected_action is None:
            expected_action = data[0] if data else None

        self._send(data)
        deadline = time.monotonic() + COMMAND_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None

            self.sock.settimeout(min(self.timeout, remaining))
            try:
                resp, _ = self.sock.recvfrom(2048)
            except socket.timeout:
                return None

            self._record_packet(self._in_samples, len(resp), outgoing=False)
            if expected_action is None:
                return resp
            if resp and resp[0] == expected_action:
                return resp

            logger.debug(
                "Ignoring unsolicited frame while waiting for 0x%02X: got 0x%02X",
                expected_action,
                resp[0] if resp else 0,
            )

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
        if self.fire_and_forget:
            self._send(proto.build_master_register(self.token))
            self._master_registered = True
            return

        # Firmware reply is the standard 2-byte ack: [action][resp_code].
        resp = self._request(proto.build_master_register(self.token))
        if resp is None or len(resp) < 2:
            raise MasterRegistrationError("No reply from bot during master registration (check ip/port)")
        status = resp[1]
        if status != proto.RESP_OK:
            name = proto.RESP_NAMES.get(status, hex(status))
            raise MasterRegistrationError(f"Master registration failed: {name}")
        self._master_registered = True

    def unregister(self) -> None:
        try:
            if self.fire_and_forget:
                self._send(proto.build_master_unregister())
                self._master_registered = False
                return
            self._request(proto.build_master_unregister())
        except OSError:
            pass
        self._master_registered = False

    def enable_streams(self, lidar_hz: int, geomag_hz: int, imu_hz: int, huskylens_hz: int) -> None:
        for label, data in (
            ("lidar distance", proto.build_lidar_set_stream(True, lidar_hz)),
            ("lidar intensity", proto.build_lidar_set_stream_intensity(True, lidar_hz)),
            ("geomag", proto.build_geomag_set_stream(True, geomag_hz)),
            ("imu", proto.build_imu_set_stream(True, imu_hz)),
            ("huskylens", proto.build_huskylens_set_stream(True, huskylens_hz)),
        ):
            if self.fire_and_forget:
                try:
                    self._send(data)
                except OSError:
                    logger.warning("Failed to send %s streaming command", label)
                continue

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
        if self.fire_and_forget:
            try:
                self._send(proto.build_imu_set_bump_config(threshold_mg, debounce_ms))
                logger.info(
                    "IMU bump config sent (fire-and-forget): threshold=%d mg debounce=%d ms",
                    threshold_mg,
                    debounce_ms,
                )
            except OSError:
                logger.warning("Failed to send IMU bump config (fire-and-forget)")
            return

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
        servo_mask = self._servo_mask(channel)
        if not self._master_registered:
            with self._command_lock:
                self._command_status[f"servo-{channel}"] = "NOT REGISTERED"
            return
        self._queue_command(
            proto.build_set_servo_type(servo_mask, servo_type),
            f"servo-{channel}",
            f"S{channel + 1} mode",
            coalesce_key=f"mode-{channel}",
        )

    def queue_set_servo_speed(self, channel: int, speed: int, force: bool = False) -> None:
        """Queue a continuous-servo speed update, coalescing drag updates per channel."""
        servo_mask = self._servo_mask(channel)
        if not self._master_registered:
            with self._command_lock:
                self._command_status[f"servo-{channel}"] = "NOT REGISTERED"
            return
        self._queue_command(
            proto.build_set_servos_speed(servo_mask, speed),
            f"servo-{channel}",
            f"S{channel + 1} speed",
            coalesce_key=f"motion-{channel}",
            require_ack=False,
        )

    def queue_set_servo_angle(self, channel: int, angle: int, force: bool = False) -> None:
        """Queue a positional-servo angle update, coalescing drag updates per channel."""
        servo_mask = self._servo_mask(channel)
        if not self._master_registered:
            with self._command_lock:
                self._command_status[f"servo-{channel}"] = "NOT REGISTERED"
            return
        self._queue_command(
            proto.build_set_servos_angle(servo_mask, angle),
            f"servo-{channel}",
            f"S{channel + 1} angle",
            coalesce_key=f"motion-{channel}",
            require_ack=False,
        )

    def queue_set_led_color(self, led_mask: int, red: int, green: int, blue: int, brightness: int) -> None:
        """Queue a color update for one or more LEDs."""
        if not self._master_registered:
            with self._command_lock:
                self._command_status["led-color"] = "NOT REGISTERED"
            return
        self._queue_command(
            proto.build_set_led_color(led_mask, red, green, blue, brightness),
            "led-color",
            f"LED 0x{led_mask:02X} color",
            coalesce_key="led-color",
            require_ack=False,
        )

    def queue_set_huskylens_illumination(self, enabled: bool) -> None:
        """Queue a HuskyLens illumination LED state update."""
        self._queue_command(
            proto.build_huskylens_set_illumination(enabled),
            "huskylens-illumination",
            "HuskyLens illumination",
            coalesce_key="huskylens-illumination",
            require_ack=False,
        )

    def queue_set_huskylens_algorithm(self, algorithm: int) -> None:
        """Queue a HuskyLens algorithm switch, retaining only the latest request."""
        self._queue_command(
            proto.build_huskylens_set_algorithm(algorithm),
            "huskylens-algorithm",
            "HuskyLens algorithm",
            coalesce_key="huskylens-algorithm",
            require_ack=False,
        )

    def queue_set_huskylens_rgb_light(self, enabled: bool) -> None:
        """Queue a HuskyLens RGB/status-light request without touching K10 LEDs."""
        self._queue_command(
            proto.build_huskylens_set_rgb_light(enabled),
            "huskylens-rgb-light",
            "HuskyLens RGB light",
            coalesce_key="huskylens-rgb-light",
            require_ack=False,
        )

    def queue_set_huskylens_display(self, enabled: bool) -> None:
        """Queue a HuskyLens LCD/display request without touching the K10 screen."""
        self._queue_command(
            proto.build_huskylens_set_display(enabled),
            "huskylens-display",
            "HuskyLens display",
            coalesce_key="huskylens-display",
            require_ack=False,
        )

    def queue_set_screen(self, screen: int) -> None:
        """Queue selection of a named screen on the physical K10 display."""
        self._queue_command(
            proto.build_ui_set_screen(screen),
            "k10-screen",
            "K10 screen",
            coalesce_key="k10-screen",
            require_ack=False,
        )

    def queue_play_sound(self, filename: str) -> None:
        """Queue playback of a stored WAV sound without coalescing requests."""
        self._queue_command(
            proto.build_sound_play(filename),
            "sound-play",
            f"Play {filename}",
        )

    def queue_stop_sound(self) -> None:
        """Queue stop request for the sound playback service."""
        self._queue_command(
            proto.build_sound_stop(),
            "sound-stop",
            "Stop sound",
            coalesce_key="sound-stop",
        )

    def queue_sound_status(self) -> None:
        """Queue status query for current sound playback state."""
        self._queue_command(
            proto.build_sound_status(),
            "sound-status",
            "Sound status",
            coalesce_key="sound-status",
        )

    def queue_sound_volume(self, percent: int) -> None:
        """Queue output volume change for sound playback service."""
        self._queue_command(
            proto.build_sound_volume(percent),
            "sound-volume",
            f"Sound volume {percent}%",
            coalesce_key="sound-volume",
        )

    def queue_stop_all_motors(self) -> None:
        """Immediately send firmware emergency stop and cancel pending motion commands."""
        stop_action = proto.build_stop_all_motors()[0]
        with self._command_lock:
            if self._inflight_command is not None:
                self._command_status[self._inflight_command.status_key] = "CANCELLED"
                self._inflight_command = None
            for queued in self._command_queue:
                self._command_status[queued.status_key] = "CANCELLED"
            self._command_queue.clear()
            self._command_status["stop-all"] = "SENT"
            try:
                self._send(bytes([stop_action]))
            except OSError:
                self._command_status["stop-all"] = "SEND FAILED"

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
        require_ack: bool = True,
        priority: bool = False,
        discard_queued: bool = False,
    ) -> None:
        command = PendingCommand(data, data[0], status_key, label, coalesce_key, require_ack)
        ack_required = require_ack and not self.fire_and_forget
        with self._command_lock:
            if not ack_required:
                # Fast-path for high-frequency actuator writes (servo/LED):
                # send immediately so a lost ACK from a prior command cannot
                # stall user-perceived control latency.
                self._command_status[status_key] = "SENT"
                try:
                    self._send(command.data)
                except OSError:
                    self._command_status[status_key] = "SEND FAILED"
                return

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
            self._notify_rx_message(frame)
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
                    status_label = "ok" if status == proto.RESP_OK else proto.RESP_NAMES.get(status, hex(status)).lower()
                    self._command_status[command.status_key] = (
                        "OK" if status == proto.RESP_OK else proto.RESP_NAMES.get(status, hex(status))
                    )
                    # Log servo responses with human labels (Option B)
                    if command.status_key.startswith("servo-"):
                        ch = int(command.status_key.split("-")[1])
                        logger.info(f"S{ch + 1} {command.label.lower()} resp={status_label}")
                    self._inflight_command = None
                    self._send_next_command_locked()
                    return
            if action == proto.make_action(proto.SERVICE_MOTOR_SERVO, proto.MOTOR_SERVO_CMD_STOP_ALL_MOTORS):
                status = frame[1]
                self._command_status["stop-all"] = (
                    "OK" if status == proto.RESP_OK else proto.RESP_NAMES.get(status, hex(status))
                )
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
                abs_norm_mg = int(round(math.sqrt(
                    parsed.accel_x_mg ** 2 + parsed.accel_y_mg ** 2 + parsed.accel_z_mg ** 2
                )))
                dyn_norm_mg = abs(abs_norm_mg - 1000)
                logger.info(
                    "IMU bump: dir=%s x=%d y=%d z=%d abs=%.2fg dyn=%.2fg",
                    proto.bump_dir_label(parsed.bump_dir),
                    parsed.accel_x_mg,
                    parsed.accel_y_mg,
                    parsed.accel_z_mg,
                    abs_norm_mg / 1000.0,
                    dyn_norm_mg / 1000.0,
                )
                self.state.set_imu_bump(parsed)
        elif action == proto.make_action(proto.SERVICE_HUSKYLENS, proto.HUSKYLENS_STREAM_FRAME_CMD):
            parsed = proto.parse_huskylens_frame(frame)
            if parsed:
                self.state.set_huskylens(parsed)
        elif action == proto.make_action(proto.SERVICE_SOUND, proto.SOUND_CMD_STATUS):
            parsed = proto.parse_sound_status(frame)
            if parsed is not None:
                logger.info("Sound status: playing=%s", "yes" if parsed.playing else "no")
