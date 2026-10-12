"""Bounded UDP session and latest-input actuator worker."""

from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from . import protocol as proto
from .config import Settings
from .drive import InputSnapshot, centered, mix

HEARTBEAT_PERIOD = 0.025
COMMAND_TIMEOUT = 0.1
REGISTRATION_TIMEOUT = 1.0
SETUP_TIMEOUT = 1.0
INPUT_TIMEOUT = 0.1
MAX_MISSED_MOTION_ACKS = 3
RECONNECT_DELAYS = (0.5, 1.0, 2.0, 5.0)
RESP_NOT_MASTER = 0x07
SOUND_CONNECTED = "jarvis-connected.wav"
SOUND_DISCONNECTED = "jarvis-disconnected.wav"
logger = logging.getLogger(__name__)


class MotionCancelled(Exception):
    pass


class CommandRejected(RuntimeError):
    def __init__(self, action: int, status: int) -> None:
        super().__init__(f"Command 0x{action:02X} rejected: status {status}")
        self.action = action
        self.status = status


@dataclass
class Pending:
    action: int
    event: threading.Event
    status: int | None = None
    sent_at: float | None = None
    acknowledged_at: float | None = None


@dataclass(frozen=True)
class MotionDisplay:
    paused: bool
    confirmed: bool
    wheels: tuple[int, ...]


class BotSession:
    auto_reconnect = True

    def __init__(self, settings: Settings, *,
                 timing_observer: Callable[[dict[str, object]], None] | None = None) -> None:
        """Optionally observe requests with a cheap, nonblocking, thread-safe callback.

        No callback runs on the heartbeat path or with the send lock held. Records
        omit tokens/raw frames; callback failures cannot interrupt safety cleanup.
        """
        self.settings = settings
        self._timing_observer = timing_observer
        self.status = "Disconnected"
        self.wheels = (0, 0, 0, 0)
        self.motion_confirmed = False
        self.ready = False
        self.paused = True
        self._snapshot = InputSnapshot()
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._pending: Pending | None = None
        self._rx_counts = {"received": 0, "wrong sender": 0, "malformed": 0, "unrelated": 0}
        self._leds: deque[tuple[int, int, int]] = deque(maxlen=16)
        self._sounds: deque[str] = deque(maxlen=4)
        self._shutdown = threading.Event()
        self._receiver_stop = threading.Event()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_failed = threading.Event()
        self._worker: threading.Thread | None = None
        self._receiver: threading.Thread | None = None
        self._heartbeat: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._address: tuple[str, int] | None = None
        self._resume_requested = False
        self._pause_until = 0.0
        self._connected_once = False

    def start(self, token: str) -> None:
        frame = proto.register(token)
        if self._worker is not None:
            raise RuntimeError("Create a new session when reconnecting")
        self.status = "Connecting"
        self._worker = threading.Thread(target=self._run, args=(frame,), name="mecanum-session", daemon=True)
        self._worker.start()

    def update_input(self, snapshot: InputSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    @property
    def motion_display(self) -> MotionDisplay:
        with self._lock:
            return MotionDisplay(self.paused, self.motion_confirmed, self.wheels)

    def queue_led(self, color: tuple[int, int, int]) -> None:
        proto.led_color(color)
        with self._lock:
            if self.ready:
                self._leds.append(color)

    def queue_sound(self, name: str) -> None:
        proto.sound_play(name)
        with self._lock:
            if self.ready:
                self._sounds.append(name)

    def _play_sound(self, name: str, *, cleanup: bool = False) -> None:
        # PLAY is never retried: a lost ACK does not mean the sound did not start.
        try:
            self._request(proto.sound_play(name), cleanup=cleanup)
        except (OSError, CommandRejected) as error:
            logger.warning("Sound %s not confirmed: %s", name, error)

    def resume(self) -> None:
        with self._lock:
            if self.ready:
                self._resume_requested = True

    def pause(self, reason: str = "Paused") -> None:
        with self._send_lock:
            with self._lock:
                self.paused = True
                self._resume_requested = False
                self._pause_until = time.monotonic() + COMMAND_TIMEOUT * 2
                self.wheels = (0, 0, 0, 0)
                self.motion_confirmed = False
                if self.ready:
                    self.status = reason
            if self.ready:
                self._zero_locked()

    def close(self) -> None:
        self.pause("Stopping")
        self._shutdown.set()

    def join(self, timeout: float = 2.0) -> None:
        if self._worker is not None:
            self._worker.join(timeout)

    def alive(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _send_locked(self, frame: bytes) -> None:
        if self._sock is None or self._address is None:
            raise OSError("Socket is not connected")
        self._sock.sendto(frame, self._address)

    def _send(self, frame: bytes) -> None:
        with self._send_lock:
            self._send_locked(frame)

    def _zero_locked(self) -> None:
        for channel in self.settings.channels:
            try:
                self._send_locked(proto.servo_speed(channel, 0))
            except OSError:
                pass
        try:
            self._send_locked(bytes([proto.STOP]))
        except OSError:
            pass

    def _request(self, frame: bytes, *, motion: bool = False, cleanup: bool = False,
                 timeout: float = COMMAND_TIMEOUT) -> None:
        with self._request_lock:
            pending = Pending(frame[0], threading.Event())
            error_name = None
            try:
                with self._send_lock:
                    if motion:
                        with self._lock:
                            snapshot = self._snapshot
                            if self.paused or self._shutdown.is_set() or not self._valid_input(snapshot):
                                raise MotionCancelled()
                    with self._lock:
                        self._pending = pending
                        received_before = self._rx_counts.copy()
                        if self._timing_observer is not None:
                            pending.sent_at = time.monotonic()
                    self._send_locked(frame)
                deadline = time.monotonic() + timeout
                while not pending.event.wait(0.005):
                    if time.monotonic() >= deadline:
                        with self._lock:
                            counts = {name: count - received_before[name]
                                      for name, count in self._rx_counts.items()}
                        details = ", ".join(f"{name} {count}" for name, count in counts.items())
                        endpoint = f"{self._address[0]}:{self._address[1]}" if self._address else "bot"
                        hint = "Check bot IP, UDP port, WiFi and firewall" if not counts["received"] else "Replies were rejected; check sender and firmware protocol"
                        if motion and not counts["received"]:
                            hint = "Control setup succeeded, but no live ACK arrived; compare with --no-camera and check firmware/network latency"
                        raise TimeoutError(
                            f"No matching ACK for 0x{frame[0]:02X} from {endpoint} within {timeout:g}s "
                            f"({details}); {hint}; outcome uncertain"
                        )
                    if not cleanup and (self._shutdown.is_set() or self._heartbeat_failed.is_set()):
                        raise RuntimeError("Session interrupted")
                if pending.status != 0:
                    raise CommandRejected(frame[0], pending.status)
            except BaseException as error:
                error_name = type(error).__name__
                raise
            finally:
                with self._lock:
                    self._pending = None
                    if pending.sent_at is not None:
                        counts = {name: count - received_before[name]
                                  for name, count in self._rx_counts.items()}
                if pending.sent_at is not None:
                    self._observe_request(pending, error_name, counts, motion, cleanup)

    def _observe_request(self, pending: Pending, error_name: str | None,
                         counts: dict[str, int], motion: bool, cleanup: bool) -> None:
        assert pending.sent_at is not None
        assert self._timing_observer is not None
        finished_at = time.monotonic()
        record: dict[str, object] = {
            "kind": "request", "action": pending.action, "status": pending.status,
            "sent_monotonic_s": pending.sent_at,
            "ack_monotonic_s": pending.acknowledged_at,
            "finished_monotonic_s": finished_at,
            "rtt_ms": (None if pending.acknowledged_at is None else
                       (pending.acknowledged_at - pending.sent_at) * 1000),
            "duration_ms": (finished_at - pending.sent_at) * 1000,
            "error": error_name, "rx_counts": counts, "motion": motion, "cleanup": cleanup,
        }
        try:
            self._timing_observer(record)
        except BaseException:
            pass

    def _receive_loop(self) -> None:
        assert self._sock is not None
        while not self._receiver_stop.is_set():
            try:
                frame, sender = self._sock.recvfrom(2048)
            except TimeoutError:
                continue
            except OSError:
                return
            with self._lock:
                self._rx_counts["received"] += 1
            if sender != self._address:
                with self._lock:
                    self._rx_counts["wrong sender"] += 1
                continue
            try:
                action, status, _payload = proto.decode_reply(frame)
            except ValueError:
                with self._lock:
                    self._rx_counts["malformed"] += 1
                continue
            with self._lock:
                pending = self._pending
                if (pending is not None and action == pending.action and status is not None
                        and not pending.event.is_set()):
                    pending.status = status
                    if pending.sent_at is not None:
                        pending.acknowledged_at = time.monotonic()
                    pending.event.set()
                else:
                    self._rx_counts["unrelated"] += 1

    def _heartbeat_loop(self) -> None:
        deadline = time.monotonic()
        while not self._heartbeat_stop.is_set():
            now = time.monotonic()
            if now - deadline > HEARTBEAT_PERIOD:
                self._heartbeat_failed.set()
                return
            try:
                self._send(bytes([proto.HEARTBEAT]))
            except OSError:
                self._heartbeat_failed.set()
                return
            deadline += HEARTBEAT_PERIOD
            self._heartbeat_stop.wait(max(0.0, deadline - time.monotonic()))

    @staticmethod
    def _valid_input(snapshot: InputSnapshot) -> bool:
        age = time.monotonic() - snapshot.timestamp
        return snapshot.connected and snapshot.focused and 0 <= age <= INPUT_TIMEOUT

    def _run(self, registration: bytes) -> None:
        """Own the socket and receiver; reconnect after a lost link until closed."""
        fault = ""
        failures = 0
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.settimeout(0.05)
            self._receiver = threading.Thread(target=self._receive_loop, name="mecanum-receiver", daemon=True)
            self._receiver.start()
            while not self._shutdown.is_set():
                fault, retry, reached_ready = self._connect_and_drive(registration)
                if not retry or not self.auto_reconnect or self._shutdown.is_set():
                    break
                failures = 0 if reached_ready else failures + 1
                delay = RECONNECT_DELAYS[min(failures, len(RECONNECT_DELAYS) - 1)]
                logger.warning("Control link lost; reconnecting in %gs: %s", delay, fault)
                self.status = f"Reconnecting in {delay:g}s: {fault}"
                if self._shutdown.wait(delay):
                    fault = ""
        except OSError as error:
            logger.warning("Control socket failed: %s", error)
            fault = str(error)
        finally:
            self._receiver_stop.set()
            if self._receiver is not None:
                self._receiver.join(0.2)
            if self._sock is not None:
                self._sock.close()
            self.status = f"Fault: {fault}" if fault else "Disconnected"

    def _connect_and_drive(self, registration: bytes) -> tuple[str, bool, bool]:
        """Run one registration-to-cleanup cycle; return fault, retry, and whether it became ready."""
        attempted = False
        registered = False
        fault = ""
        retry = False
        self._heartbeat_stop.clear()
        self._heartbeat_failed.clear()
        with self._lock:
            self._leds.clear()
            self._sounds.clear()
        try:
            self._address = (socket.gethostbyname(self.settings.host), self.settings.udp_port)
            attempted = True
            if self._connected_once:
                self.status = "Reconnecting: registering"
            self._request(registration, timeout=REGISTRATION_TIMEOUT)
            registered = True
            self._send(bytes([proto.HEARTBEAT]))
            self._heartbeat = threading.Thread(target=self._heartbeat_loop, name="mecanum-heartbeat", daemon=True)
            self._heartbeat.start()
            self.status = "Configuring continuous servos"
            self._request(proto.servo_type(sum(1 << channel for channel in self.settings.channels)),
                          timeout=SETUP_TIMEOUT)
            for channel in self.settings.channels:
                self._request(proto.servo_speed(channel, 0), timeout=SETUP_TIMEOUT)
            reconnected = self._connected_once
            self._connected_once = True
            self.ready = True
            self.status = ("Reconnected; paused: center sticks, then Resume" if reconnected
                           else "Paused: center sticks, then Resume")
            self._play_sound(SOUND_CONNECTED)
            last_sent_wheels = None
            last_wheel_send = 0.0
            missed_acks = 0
            while not self._shutdown.is_set():
                if self._heartbeat_failed.is_set():
                    raise RuntimeError("Heartbeat sender failed or missed its deadline")
                with self._lock:
                    snapshot = self._snapshot
                    if self._resume_requested and time.monotonic() >= self._pause_until and self._valid_input(snapshot) and centered(snapshot, self.settings):
                        self.paused = False
                        self._resume_requested = False
                        self.status = "Driving"
                    paused = self.paused
                    color = self._leds.popleft() if self._leds else None
                    sound = self._sounds.popleft() if self._sounds else None
                if not paused:
                    if not self._valid_input(snapshot):
                        self.pause("Paused: controller unavailable, stale, or unfocused")
                    else:
                        wheels = mix(snapshot, self.settings)
                        try:
                            if wheels != last_sent_wheels or time.monotonic() - last_wheel_send >= 0.25:
                                if wheels != last_sent_wheels:
                                    with self._lock:
                                        self.motion_confirmed = False
                                for channel, speed in zip(self.settings.channels, wheels):
                                    self._request(proto.servo_speed(channel, speed), motion=True)
                                with self._lock:
                                    self.wheels = wheels
                                    self.motion_confirmed = True
                                last_sent_wheels = wheels
                                last_wheel_send = time.monotonic()
                                if missed_acks:
                                    missed_acks = 0
                                    with self._lock:
                                        if not self.paused:
                                            self.status = "Driving"
                        except MotionCancelled:
                            self.pause("Paused: input interrupted")
                        except TimeoutError:
                            # Not replayed: the next pass mixes fresh input or pauses on stale input.
                            missed_acks += 1
                            last_sent_wheels = None
                            if missed_acks >= MAX_MISSED_MOTION_ACKS:
                                raise
                            logger.warning("Motion ACK missed (%d/%d)", missed_acks, MAX_MISSED_MOTION_ACKS)
                            with self._lock:
                                if not self.paused:
                                    self.status = f"Driving: motion ACK missed ({missed_acks}/{MAX_MISSED_MOTION_ACKS})"
                else:
                    last_sent_wheels = None
                if color is not None:
                    try:
                        self._request(proto.led_color(color))
                    except TimeoutError as error:
                        logger.warning("LED command not confirmed: %s", error)
                if sound is not None:
                    self._play_sound(sound)
                self._shutdown.wait(0.025)
        except (OSError, RuntimeError) as error:
            fault = str(error)
            if registered and not self.ready:
                fault = "Registered; servo setup failed: " + fault
            token_rejected = (isinstance(error, CommandRejected) and error.action == proto.REGISTER
                              and error.status == RESP_NOT_MASTER)
            if token_rejected:
                fault = "Token rejected (status 7): enter the token currently shown on the bot screen"
            # Only reconnect a link that worked; initial failures usually mean wrong settings.
            retry = self._connected_once and not token_rejected
            logger.warning("Control session failed: %s", fault)
        except Exception as error:
            logger.exception("Control session failed")
            fault = str(error)
        finally:
            reached_ready = self.ready
            with self._lock:
                self.ready = False
                self.paused = True
                self._resume_requested = False
                self.wheels = (0, 0, 0, 0)
                self.motion_confirmed = False
            if registered:
                for _attempt in range(3):
                    with self._send_lock:
                        self._zero_locked()
                    threading.Event().wait(0.02)
                self._play_sound(SOUND_DISCONNECTED, cleanup=True)
            if attempted:
                try:
                    self._request(bytes([proto.UNREGISTER]), cleanup=True)
                except (OSError, RuntimeError):
                    if not fault:
                        fault = "Unregister not confirmed"
            self._heartbeat_stop.set()
            if self._heartbeat is not None:
                self._heartbeat.join(0.2)
                self._heartbeat = None
        return fault, retry, reached_ready