import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mecanum_control.camera import CameraStream
from mecanum_control.config import Settings
from mecanum_control.drive import InputSnapshot
from mecanum_control.udp_client import BotSession
from test_session import LoopbackBot, await_condition


def test_http_stream_delivers_frames_and_closes():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/cam/stream"
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            frame = b"\xff\xd8" + bytes(2048) + b"\xff\xd9"
            body = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame
            try:
                self.wfile.write(body * 3)
                self.wfile.flush()
                release.wait(2)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_args):
            pass

    release = threading.Event()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    camera = CameraStream(f"http://127.0.0.1:{server.server_port}/cam/stream")
    try:
        camera.start()
        await_condition(lambda: camera.status == "Video live")
        frame = camera.take_frame()
        assert frame and frame[0].startswith(b"\xff\xd8")
    finally:
        camera.close()
        release.set()
        camera.join()
        assert not camera.alive()
        server.shutdown()
        thread.join()
        server.server_close()


def test_stalled_camera_does_not_stop_live_input_or_heartbeat():
    release = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            release.wait(2)
            try:
                self.send_response(503)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    bot = LoopbackBot()
    session = BotSession(replace(Settings(), host="127.0.0.1", udp_port=bot.port))
    camera = CameraStream(f"http://127.0.0.1:{server.server_port}/cam/stream")
    try:
        session.start("ABCDE")
        await_condition(lambda: session.ready)
        session.update_input(InputSnapshot(timestamp=time.monotonic(), connected=True, focused=True))
        session.resume()
        await_condition(lambda: not session.paused)
        camera.start()
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline:
            session.update_input(InputSnapshot(1, -1, 1, time.monotonic(), True, True))
            threading.Event().wait(0.01)
        assert not session.paused and session.ready
        assert sum(frame[0] == 0x43 for _, frame in bot.frames) >= 8
        motion = [frame for _, frame in bot.frames if frame[0] == 0x23 and frame[2]]
        assert all(bytes([0x23, mask, speed & 255]) in motion for mask, speed in ((1, 30), (2, 10), (4, 10), (8, -10)))
    finally:
        session.close()
        session.join()
        camera.close()
        release.set()
        camera.join()
        server.shutdown()
        thread.join()
        server.server_close()
        bot.close()