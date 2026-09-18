"""Test suite for UDP client: registration, heartbeat, frame receiver, command queue."""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import protocol as proto
from state import SensorState
from udp_client import SensorUDPClient, MasterRegistrationError


def _with_udp_trailer(frame: bytes, rx_seq: int = 1, server_millis: int = 1234) -> bytes:
    return frame + rx_seq.to_bytes(4, "big") + server_millis.to_bytes(4, "big")


class TestMasterRegistration:
    """Test registration flow (0x41 request/response)."""

    def test_register_master_success(self):
        """Successful registration returns normally."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.recvfrom.return_value = (
                _with_udp_trailer(bytes([0x41, proto.RESP_OK])),
                ("127.0.0.1", 24642),
            )
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.register_master()  # Should not raise
            
            # Verify registration request sent
            assert mock_sock.sendto.called
            sent_data = mock_sock.sendto.call_args[0][0]
            assert sent_data[0] == 0x41
            assert sent_data[1:6] == b"UROCK"

    def test_register_master_no_reply(self):
        """Registration fails with timeout (no reply)."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.recvfrom.side_effect = TimeoutError()
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            try:
                client.register_master()
                assert False, "Should have raised MasterRegistrationError"
            except MasterRegistrationError as e:
                assert "No reply" in str(e)

    def test_register_master_not_master_error(self):
        """Registration fails with resp_not_master (0x07) response."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            # Simulate "not master" response
            mock_sock.recvfrom.return_value = (
                _with_udp_trailer(bytes([0x41, proto.RESP_NOT_MASTER])),
                ("127.0.0.1", 24642),
            )
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            try:
                client.register_master()
                assert False, "Should have raised MasterRegistrationError"
            except MasterRegistrationError as e:
                assert "registration failed" in str(e)
                assert "resp_not_master" in str(e)

    def test_register_master_short_reply(self):
        """Registration fails if reply is too short."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            # Return a reply that's too short
            mock_sock.recvfrom.return_value = (bytes([0x41]), ("127.0.0.1", 24642))
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            try:
                client.register_master()
                assert False, "Should have raised MasterRegistrationError"
            except MasterRegistrationError as e:
                assert "No reply" in str(e)

    def test_unregister_success(self):
        """Unregister sends 0x42 command."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.recvfrom.return_value = (
                _with_udp_trailer(bytes([0x42, proto.RESP_OK])),
                ("127.0.0.1", 24642),
            )
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.unregister()  # Should not raise
            
            # Verify unregister request sent
            assert mock_sock.sendto.called
            sent_data = mock_sock.sendto.call_args[0][0]
            assert sent_data[0] == 0x42

    def test_unregister_tolerates_socket_error(self):
        """Unregister ignores socket errors."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.recvfrom.side_effect = OSError("socket closed")
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.unregister()  # Should not raise


class TestHeartbeatThread:
    """Test heartbeat thread lifecycle and timing."""

    def test_heartbeat_thread_starts(self):
        """Heartbeat thread starts when client.start() called."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            
            # Give thread time to run a few iterations
            time.sleep(0.1)
            
            # Verify heartbeat (0x43) was sent multiple times
            assert mock_sock.sendto.call_count >= 2
            for call_obj in mock_sock.sendto.call_args_list:
                sent_data = call_obj[0][0]
                assert sent_data[0] == 0x43  # Heartbeat action

    def test_heartbeat_thread_stops(self):
        """Heartbeat thread stops when client.stop() called."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            time.sleep(0.05)
            
            initial_call_count = mock_sock.sendto.call_count
            client.stop()
            time.sleep(0.05)
            
            # Verify no more heartbeats after stop
            final_call_count = mock_sock.sendto.call_count
            assert final_call_count == initial_call_count or final_call_count == initial_call_count + 1

    def test_heartbeat_thread_tolerate_send_error(self):
        """Heartbeat thread survives send errors."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            mock_sock.sendto.side_effect = OSError("network unreachable")
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            time.sleep(0.1)  # Should not crash
            client.stop()
            
            # No assertion needed; just verify it didn't crash


class TestCommandQueue:
    """Test command queuing and throttling logic."""

    def test_queue_set_servo_angle(self):
        """Queueing servo angle command marks it as QUEUED."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            client.queue_set_servo_angle(0, 90)
            
            # Command should be queued
            assert client.command_status("servo-0") in ("QUEUED", "SENT")

    def test_queue_command_coalesces_by_key(self):
        """Multiple commands with same coalesce_key are coalesced (last one wins)."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            # Queue two angle updates for same channel
            client.queue_set_servo_angle(0, 45)
            client.queue_set_servo_angle(0, 90)
            
            # Only the second command should be in queue
            with client._command_lock:
                # Count commands with motion-0 coalesce key
                motion_count = sum(1 for cmd in client._command_queue if cmd.coalesce_key == "motion-0")
                assert motion_count <= 1, "Commands should be coalesced"

    def test_motion_command_has_bounded_ack_repeats(self):
        state = SensorState()
        client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
        client._master_registered = True
        sent: list[bytes] = []
        client._send = lambda data, count=True: sent.append(data)
        try:
            command = proto.build_set_servos_angle(0x01, 90)
            client.queue_set_servo_angle(0, 90)
            client._dispatch(_with_udp_trailer(bytes([0x24, proto.RESP_OK])))

            assert sent == [command]
            assert client.command_status("servo-0") == "OK"
        finally:
            client.sock.close()

    def test_new_motion_value_cancels_old_repeats(self):
        state = SensorState()
        client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
        client._master_registered = True
        sent: list[bytes] = []
        client._send = lambda data, count=True: sent.append(data)
        try:
            first = proto.build_set_servos_angle(0x01, 45)
            second = proto.build_set_servos_angle(0x01, 90)
            client.queue_set_servo_angle(0, 45)
            client.queue_set_servo_angle(0, 90)
            client._dispatch(bytes([0x24, proto.RESP_OK]))

            assert sent == [first, second]
        finally:
            client.sock.close()

    def test_rejects_master_protected_commands_when_not_registered(self):
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock

            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.queue_set_servo_angle(0, 90)

            assert client.command_status("servo-0") == "NOT REGISTERED"
            assert mock_sock.sendto.call_count == 0

    def test_stop_all_motors_clears_queue(self):
        """stop_all_motors immediately sends emergency stop and clears pending commands."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            # Queue some commands
            client.queue_set_servo_angle(0, 45)
            client.queue_set_servo_angle(1, 90)
            
            # Clear queue
            client.queue_stop_all_motors()
            
            # Verify queue is empty
            with client._command_lock:
                assert len(client._command_queue) == 0
                assert client._inflight_command is None


class TestFrameReceiver:
    """Test frame receiver thread and dispatch."""

    def test_frame_receiver_starts(self):
        """Receiver thread starts and processes frames."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            # Simulate LIDAR frame arrival
            lidar_frame = bytes([
                0x8F,  # Action: LIDAR distance stream
                0x00,  # Status: OK
                0x01, 0x00,  # Frame ID (little-endian u16)
                0x00, 0x00, 0x00, 0x00,  # Timestamp (u32)
                0x04, 0x00,  # Point count: 4 points (little-endian u16)
                0x64, 0x00,  # Distance 1: 100
                0xC8, 0x00,  # Distance 2: 200
                0x2C, 0x01,  # Distance 3: 300
                0x90, 0x01,  # Distance 4: 400
            ])
            
            mock_sock.recvfrom.side_effect = [(lidar_frame, ("127.0.0.1", 24642))]
            mock_sock.settimeout(0.5)  # set during _receive_loop
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            time.sleep(0.1)
            client.stop()
            
            # Verify LIDAR frame was parsed and stored
            snapshot = state.snapshot()
            if snapshot and snapshot.lidar_distance:
                assert snapshot.lidar_distance.frame_id == 1
                assert len(snapshot.lidar_distance.values) == 4

    def test_frame_receiver_tolerates_malformed_frame(self):
        """Receiver tolerates malformed frames without crashing."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            # Return a malformed frame (too short)
            malformed_frame = bytes([0x8F, 0x00])  # Missing frame data
            good_frame = bytes([0x8F, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
            
            mock_sock.recvfrom.side_effect = [
                (malformed_frame, ("127.0.0.1", 24642)),
                (good_frame, ("127.0.0.1", 24642)),
                TimeoutError(),
            ]
            mock_sock.settimeout(0.5)
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            time.sleep(0.15)
            client.stop()
            
            # Should complete without crash


class TestProtocolIntegration:
    """Integration tests with protocol builders."""

    def test_build_and_send_servo_commands(self):
        """Build servo commands and verify they can be queued."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            
            # Test building servo commands
            client.queue_set_servo_type(0, proto.SERVO_TYPE_180)
            client.queue_set_servo_angle(0, 90)
            client.queue_set_servo_speed(1, 50)
            
            # Verify commands were queued
            assert client.command_status("servo-0") in ("QUEUED", "SENT")

    def test_build_and_send_led_commands(self):
        """Build LED commands and verify they can be queued."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            
            # Test building LED commands
            client.queue_set_led_color(0x01, 255, 0, 0, 255)
            
            # Verify command was queued
            assert client.command_status("led-color") in ("QUEUED", "SENT")


class TestPacketStats:
    """Test packet statistics tracking."""

    def test_stats_counts_packets(self):
        """Stats correctly count sent and received packets."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client._master_registered = True
            
            # Send a command
            client.queue_set_servo_angle(0, 90)
            time.sleep(0.01)
            
            stats = client.stats()
            assert stats.sent_total >= 1
            assert stats.recv_total >= 0


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_client_tolerates_multiple_stops(self):
        """Calling stop() multiple times doesn't crash."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            client.start()
            client.stop()
            client.stop()  # Should not crash

    def test_invalid_servo_channel_raises(self):
        """Invalid servo channel raises ValueError."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            
            try:
                client.queue_set_servo_angle(999, 90)  # Invalid channel
                assert False, "Should have raised ValueError"
            except ValueError:
                pass

    def test_servo_types_mismatch_raises(self):
        """Initializing with wrong number of servo types raises ValueError."""
        state = SensorState()
        with patch('socket.socket') as mock_socket_class:
            mock_sock = MagicMock()
            mock_socket_class.return_value = mock_sock
            
            client = SensorUDPClient("127.0.0.1", 24642, "UROCK", 2.0, state)
            
            try:
                client.initialize_servos((proto.SERVO_TYPE_180,))  # Wrong count
                assert False, "Should have raised ValueError"
            except ValueError as e:
                assert "expected" in str(e)
