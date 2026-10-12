import json
import socket
import threading
import time
from dataclasses import replace

import pytest
from mecanum_control.config import Settings
from mecanum_control.drive import InputSnapshot
from mecanum_control.timing import JsonlObserver
from mecanum_control.udp_client import BotSession


class LoopbackBot:
    def __init__(self, register_status=0, drop_speed=False, spoof=False, drop_register=False,
                 register_delay: float = 0.0, invalid_register=False, setup_delay: float = 0.0,
                 motion_delay: float = 0.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.frames = []
        self.register_status = register_status
        self.drop_speed = drop_speed
        self.spoof = spoof
        self.drop_register = drop_register
        self.register_delay = register_delay
        self.invalid_register = invalid_register
        self.setup_delay = setup_delay
        self.motion_delay = motion_delay
        self._reply_threads = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                frame, sender = self.sock.recvfrom(128)
            except TimeoutError:
                continue
            self.frames.append((time.monotonic(), frame))
            if frame[0] == 0x43:
                continue
            if self.drop_register and frame[0] == 0x41:
                continue
            if frame[0] == 0x41 and self.register_delay:
                self.stop.wait(self.register_delay)
            if self.drop_speed and frame[0] == 0x23 and frame[2] != 0:
                continue
            delay = self.setup_delay if frame[0] == 0x22 or (frame[0] == 0x23 and frame[2] == 0) else 0.0
            if frame[0] == 0x23 and frame[2] != 0:
                delay = self.motion_delay
            if delay:
                reply_thread = threading.Thread(target=self.reply_after_delay, args=(frame, sender, delay))
                self._reply_threads.append(reply_thread)
                reply_thread.start()
                continue
            status = self.register_status if frame[0] == 0x41 else 0
            if self.spoof:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as wrong_sender:
                    wrong_sender.sendto(bytes([frame[0], 0]) + bytes(8), sender)
            self.sock.sendto(b"\x51\x00" + bytes(8), sender)
            self.sock.sendto(bytes([frame[0], status]), sender)
            if self.invalid_register and frame[0] == 0x41:
                continue
            self.sock.sendto(bytes([frame[0], status]) + bytes(8), sender)

    def reply_after_delay(self, frame, sender, delay):
        if not self.stop.wait(delay):
            self.sock.sendto(bytes([frame[0], 0]) + bytes(8), sender)

    def close(self):
        self.stop.set()
        self.thread.join(1)
        for reply_thread in self._reply_threads:
            reply_thread.join(1)
        self.sock.close()


def await_condition(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Condition timed out")
        threading.Event().wait(0.005)


@pytest.mark.parametrize("failure", [None, "registration", "timeout", "interrupt"])
def test_identification_pulses_and_cleanup(failure, monkeypatch):
    from mecanum_control.identify_servos import IdentificationSession

    bot = LoopbackBot(register_status=7 if failure == "registration" else 0,
                      drop_speed=failure == "timeout", spoof=True)
    session = IdentificationSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    def stop_on_enter(_prompt):
        threading.Event().wait(0.06)
        return ""
    monkeypatch.setattr("builtins.input", stop_on_enter)
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready or not session.alive())
        if failure == "registration":
            with pytest.raises(RuntimeError):
                session.run_until_enter(0, 10)
        elif failure == "timeout":
            with pytest.raises(TimeoutError):
                session.run_until_enter(0, 10)
        elif failure == "interrupt":
            original = session._request
            def interrupt(frame, **kwargs):
                original(frame, **kwargs)
                if frame == b"\x23\x01\x0a":
                    raise KeyboardInterrupt()
            monkeypatch.setattr(session, "_request", interrupt)
            with pytest.raises(KeyboardInterrupt):
                session.run_until_enter(0, 10)
        else:
            for channel in range(4):
                session.run_until_enter(channel, 10)
        session.close()
        session.join(5)
        assert not session.alive()
        frames = [frame for _, frame in bot.frames]
        assert frames[-1] == b"\x42"
        speeds = [frame for frame in frames if frame[0] == 0x23]
        moving = [frame for frame in speeds if frame[2]]
        if failure == "registration":
            assert not speeds
        else:
            assert moving == [bytes([0x23, 1 << channel, 10])
                              for channel in (range(4) if failure is None else (0,))]
            for index, frame in enumerate(speeds):
                if frame[2]:
                    assert speeds[index + 1] == bytes([0x23, frame[1], 0])
            for mask in (1, 2, 4, 8):
                assert bytes([0x23, mask, 0]) in frames
            assert b"\x28" in frames
            assert sum(frame == b"\x43" for frame in frames) >= 2
    finally:
        session.close()
        session.join(5)
        bot.close()


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("speed", [10, 100])
def test_identification_interactive_flow(interrupted, speed, monkeypatch, tmp_path, capsys):
    from mecanum_control import identify_servos

    bot = LoopbackBot()
    answers = iter(("", "", "", "invalid", "FLB", "", "", "frf", "", "", "rlb", "", "", "rrf"))
    def answer(_prompt):
        result = next(answers)
        if interrupted and "Press Enter to stop" in _prompt:
            raise KeyboardInterrupt()
        return result
    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(identify_servos.getpass, "getpass", lambda _prompt: "ABCDE")
    path = tmp_path / "settings.json"
    try:
        result = identify_servos.main(["--config", str(path), "--host", "127.0.0.1",
                                       "--port", str(bot.port),
                                       "--speed", str(speed)])
        assert result == (130 if interrupted else 0)
        frames = [frame for _, frame in bot.frames]
        assert [frame for frame in frames if frame[0] == 0x23 and frame[2]] == [
            bytes([0x23, 1 << channel, speed]) for channel in (range(1) if interrupted else range(4))]
        assert frames[-1] == b"\x42"
        assert not path.exists()
        output = capsys.readouterr().out
        assert "ABCDE" not in output
        if not interrupted:
            for connector, code in (("S1", "flb"), ("S2", "frf"), ("S3", "rlb"), ("S4", "rrf")):
                assert f"{connector}: {code}" in output
            assert "Use flf, flb" in output
    finally:
        bot.close()


@pytest.mark.parametrize("heartbeat_failure", [False, True])
def test_identification_waits_for_enter_with_independent_safety(heartbeat_failure, monkeypatch):
    from mecanum_control.identify_servos import IdentificationSession

    bot = LoopbackBot()
    session = IdentificationSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    errors = []
    def wait_for_enter(_prompt):
        zero_count = sum(frame == b"\x23\x01\x00" for _, frame in bot.frames)
        if heartbeat_failure:
            session._heartbeat_failed.set()
            await_condition(lambda: not session.alive())
            assert sum(frame == b"\x23\x01\x00" for _, frame in bot.frames) > zero_count
        else:
            heartbeat_count = sum(frame == b"\x43" for _, frame in bot.frames)
            threading.Event().wait(0.6)
            assert sum(frame == b"\x23\x01\x00" for _, frame in bot.frames) == zero_count
            assert sum(frame == b"\x43" for _, frame in bot.frames) > heartbeat_count
        return ""
    monkeypatch.setattr("builtins.input", wait_for_enter)
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready or not session.alive())
        try:
            session.run_until_enter(0, 100)
        except RuntimeError as error:
            errors.append(str(error))
        assert bool(errors) == heartbeat_failure
        session.close()
        session.join(5)
        frames = [frame for _, frame in bot.frames]
        assert frames[-1] == b"\x42"
        assert b"\x23\x01\x64" in frames
    finally:
        session.close()
        session.join(5)
        bot.close()


@pytest.mark.parametrize("options", [("--speed", "0"), ("--speed", "101")])
def test_identification_rejects_unsafe_options(options):
    from mecanum_control.identify_servos import main

    with pytest.raises(SystemExit) as error:
        main(list(options))
    assert error.value.code == 2


def test_jsonl_observer_thread_safe_append(tmp_path):
    path = tmp_path / "timing.jsonl"
    path.write_text('{"kind": "previous"}\n')
    with JsonlObserver(path) as observer:
        threads = [threading.Thread(target=lambda index=index: [
            observer({"producer": index, "sequence": sequence}) for sequence in range(10)
        ]) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0] == {"kind": "previous"}
    assert len(records) == 41
    assert len({(record["producer"], record["sequence"]) for record in records[1:]}) == 40
    assert observer.stats() == {"written": 40, "dropped": 0, "error": None}
    observer.close()


def test_jsonl_observer_reports_failed_serialization(tmp_path):
    with JsonlObserver(tmp_path / "timing.jsonl") as observer:
        observer({"invalid": object()})
        observer({"kind": "valid"})
    assert observer.stats() == {"written": 1, "dropped": 1, "error": "TypeError"}
    observer({"kind": "closed"})
    assert observer.stats()["dropped"] == 2


@pytest.mark.parametrize("status", [0, 7])
def test_registration_cleanup(status):
    bot = LoopbackBot(register_status=status)
    records = []
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port),
                         timing_observer=records.append)
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready or not session.alive())
        if status:
            assert not session.ready
            assert not any(frame[0] in (0x22, 0x23) for _, frame in bot.frames)
        else:
            session.close()
            session.join()
            frames = [frame for _, frame in bot.frames]
            assert frames[0] == b"\x41ABCDE"
            assert frames.index(b"\x22\x0f\x02") < next(index for index, frame in enumerate(frames) if frame[0] == 0x23)
            for mask in (1, 2, 4, 8):
                assert bytes([0x23, mask, 0]) in frames
            assert frames[-1] == b"\x42"
        registration = records[0]
        assert registration["action"] == 0x41
        assert registration["status"] == status
        assert registration["error"] == ("CommandRejected" if status else None)
        assert 0 <= registration["rtt_ms"] <= registration["duration_ms"]
        assert registration["sent_monotonic_s"] <= registration["ack_monotonic_s"]
        assert registration["ack_monotonic_s"] <= registration["finished_monotonic_s"]
        assert registration["rx_counts"]["malformed"] == 1
        assert all(record["action"] != 0x43 for record in records)
        assert "ABCDE" not in repr(records)
    finally:
        session.close()
        session.join()
        bot.close()


def test_wrong_sender_cannot_register():
    bot = LoopbackBot(register_status=7, spoof=True)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: not session.alive())
        assert "rejected" in session.status
        assert not any(frame[0] == 0x22 for _, frame in bot.frames)
    finally:
        session.close()
        session.join()
        bot.close()


def test_registration_accepts_delayed_wifi_ack():
    bot = LoopbackBot(register_delay=0.25)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready or not session.alive())
        assert session.ready, session.status
        assert len([frame for _, frame in bot.frames if frame[0] == 0x41]) == 1
    finally:
        session.close()
        session.join()
        bot.close()


def test_delayed_servo_setup_keeps_heartbeat_and_never_moves():
    bot = LoopbackBot(setup_delay=0.2)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
        session.start("ABCDE")
        session.resume()
        await_condition(lambda: session.ready or not session.alive(), timeout=3)
        assert session.ready, session.status
        assert session.paused
        frames = [frame for _, frame in bot.frames]
        assert frames.count(b"\x22\x0f\x02") == 1
        assert all(frame[2] == 0 for frame in frames if frame[0] == 0x23)
        assert frames.count(b"\x43") >= 20
    finally:
        session.close()
        session.join()
        bot.close()


def test_registration_timeout_unregisters_without_moving():
    bot = LoopbackBot(drop_register=True)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: not session.alive())
        assert [frame[0] for _, frame in bot.frames] == [0x41, 0x42]
        assert "received 0" in session.status
        assert f"127.0.0.1:{bot.port}" in session.status
        assert "Check bot IP" in session.status
        assert "ABCDE" not in session.status
    finally:
        session.close()
        session.join()
        bot.close()


def test_registration_reports_rejected_packet_shapes():
    bot = LoopbackBot(invalid_register=True)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: not session.alive())
        assert "received 2" in session.status
        assert "malformed 1" in session.status
        assert "unrelated 1" in session.status
        assert "Replies were rejected" in session.status
        assert "ABCDE" not in session.status
        assert not any(frame[0] in (0x22, 0x23) for _, frame in bot.frames)
    finally:
        session.close()
        session.join()
        bot.close()


def test_stale_input_pauses_and_requires_centered_resume():
    bot = LoopbackBot()
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused)
        session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
        await_condition(lambda: any(frame == b"\x23\x01\x1e" for _, frame in bot.frames))
        await_condition(lambda: session.paused)
        assert session.ready
        assert session.wheels == (0, 0, 0, 0)
        session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
        session.resume()
        threading.Event().wait(0.04)
        assert session.paused
    finally:
        session.close()
        session.join()
        bot.close()


def test_motion_display_confirms_only_after_the_full_wheel_batch():
    from mecanum_control.drive import motion_arrows

    bot = LoopbackBot(motion_delay=0.015)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused and session.motion_display.confirmed)
        session.update_input(InputSnapshot(0, -1, 0, time.monotonic(), True, True))
        await_condition(lambda: any(frame == b"\x23\x01\x1e" for _, frame in bot.frames)
                        and not session.motion_display.confirmed)
        pending = session.motion_display
        assert not pending.paused
        assert not pending.confirmed
        await_condition(lambda: session.motion_display.confirmed)
        displayed = session.motion_display
        assert motion_arrows(displayed.wheels, session.settings.inverted) == ("↑", "-")
    finally:
        session.close()
        session.join()
        bot.close()


@pytest.mark.parametrize("observer_fails", [False, True])
def test_single_motion_timeout_does_not_replay_or_end_session(observer_fails):
    bot = LoopbackBot(drop_speed=True)
    records = []

    def observe(record):
        records.append(record)
        if observer_fails:
            raise RuntimeError("Observer failed")

    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port),
                         timing_observer=observe)
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused)
        session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
        await_condition(lambda: session.paused)
        threading.Event().wait(0.1)
        motion = [frame for _, frame in bot.frames if frame[0] == 0x23 and frame[2] != 0]
        assert motion == [b"\x23\x01\x1e"]
        assert session.alive() and session.ready
        assert session.wheels == (0, 0, 0, 0)
        assert session.motion_display.paused
        assert not session.motion_display.confirmed
        failed = [record for record in records if record["motion"] and record["error"]]
        assert len(failed) == 1
        assert failed[0]["action"] == 0x23
        assert failed[0]["error"] == "TimeoutError"
        assert failed[0]["rtt_ms"] is None
        assert failed[0]["status"] is None
    finally:
        session.close()
        session.join()
        bot.close()


def test_repeated_motion_timeouts_reconnect_paused():
    bot = LoopbackBot(drop_speed=True)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused)
        deadline = time.monotonic() + 2
        while not session.status.startswith("Reconnecting"):
            assert time.monotonic() < deadline, session.status
            session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
            threading.Event().wait(0.01)
        assert "Control setup succeeded" in session.status
        assert "--no-camera" in session.status
        assert "ABCDE" not in session.status
        session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
        await_condition(lambda: session.ready, timeout=3)
        assert session.alive() and session.paused
        assert session.status.startswith("Reconnected")
        frames = [frame for _, frame in bot.frames]
        first_unregister = frames.index(b"\x42")
        assert b"\x28" in frames[:first_unregister]
        motion = [frame for frame in frames if frame[0] == 0x23 and frame[2] != 0]
        assert len(motion) == 3
        assert all(frame[2] == 0 for frame in frames[first_unregister:] if frame[0] == 0x23)
        assert frames[first_unregister:].count(b"\x41ABCDE") == 1
    finally:
        session.close()
        session.join()
        bot.close()
    assert session.status == "Disconnected"
    assert [frame for _, frame in bot.frames][-1] == b"\x42"


def test_wrong_token_after_reconnect_stops_retrying():
    bot = LoopbackBot()
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        bot.register_status = 7
        session._heartbeat_failed.set()
        await_condition(lambda: not session.alive(), timeout=3)
        assert session.status.startswith("Fault: Token rejected")
        assert [frame for _, frame in bot.frames].count(b"\x41ABCDE") == 2
    finally:
        session.close()
        session.join()
        bot.close()


def test_steady_sticks_suppress_unchanged_writes_but_refresh():
    bot = LoopbackBot()
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused)
        started = time.monotonic()
        while time.monotonic() - started < 0.18:
            session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
            threading.Event().wait(0.01)
        motion = [frame for _, frame in bot.frames if frame[0] == 0x23 and frame[2]]
        assert len(motion) == 4
        while time.monotonic() - started < 0.4:
            session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
            threading.Event().wait(0.01)
        motion = [frame for _, frame in bot.frames if frame[0] == 0x23 and frame[2]]
        assert len(motion) == 8
        assert motion[:4] == motion[4:]
        assert session.ready and not session.paused
    finally:
        session.close()
        session.join()
        bot.close()


def test_connect_gamepad_and_disconnect_sounds():
    bot = LoopbackBot()
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.queue_sound("Rocket-okay-panic.wav")
        await_condition(lambda: b"\xb1Rocket-okay-panic.wav" in [frame for _, frame in bot.frames])
        with pytest.raises(ValueError):
            session.queue_sound("../secret.wav")
        session.close()
        session.join()
        frames = [frame for _, frame in bot.frames]
        sounds = [frame for frame in frames if frame[0] == 0xB1]
        assert sounds == [b"\xb1jarvis-connected.wav", b"\xb1Rocket-okay-panic.wav",
                          b"\xb1jarvis-disconnected.wav"]
        assert frames.index(b"\xb1jarvis-connected.wav") > frames.index(b"\x22\x0f\x02")
        assert frames.index(b"\xb1jarvis-disconnected.wav") > frames.index(b"\x28")
        assert frames[-1] == b"\x42"
        assert session.status == "Disconnected"
    finally:
        session.close()
        session.join()
        bot.close()


def test_failed_registration_plays_no_sound():
    bot = LoopbackBot(register_status=7)
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    try:
        session.start("ABCDE")
        await_condition(lambda: not session.alive())
        assert not any(frame[0] == 0xB1 for _, frame in bot.frames)
    finally:
        session.close()
        session.join()
        bot.close()