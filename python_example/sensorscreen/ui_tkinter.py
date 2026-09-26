"""Native Tkinter control window for SensorsScreen command and status controls."""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import tkinter as tk
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from sound_http_client import SoundHttpClient

import protocol as proto
from screen_controls import SCREEN_BUTTONS
from sound_controls import parse_sound_list
from ui_state import UiState

DRAG_COMMAND_INTERVAL_S = 0.1

MODE_LABEL_TO_TYPE = {
    "180": proto.SERVO_TYPE_180,
    "270": proto.SERVO_TYPE_270,
    "CONT": proto.SERVO_TYPE_CONTINUOUS,
}
MODE_TYPE_TO_LABEL = {value: key for key, value in MODE_LABEL_TO_TYPE.items()}
ALGORITHM_LABELS = ["FACE", "TRACK", "OBJECT", "LINE", "COLOR", "TAG"]
LED_PRESETS = [
    ("Red", (255, 0, 0)),
    ("Yellow", (255, 255, 0)),
    ("Green", (0, 255, 0)),
    ("Magenta", (255, 0, 255)),
    ("Blue", (0, 0, 255)),
    ("Purple", (128, 0, 128)),
    ("White", (255, 255, 255)),
    ("Black", (0, 0, 0)),
]

HTTP_LOG_POLL_INTERVAL_MS = 1000
HTTP_LOG_MAX_LINES = 1000
HTTP_LOG_PROBES = {
    "app": ("/logs/app", "/api/logs/app", "/data/logs/app", "/data/app.log"),
    "svc": ("/logs/svc", "/api/logs/svc", "/api/logs/service", "/data/logs/svc", "/data/svc.log"),
    "debug": ("/logs/debug", "/api/logs/debug", "/data/logs/debug", "/data/debug.log"),
    "esp": ("/logs/esp", "/api/logs/esp", "/data/logs/esp", "/data/esp.log"),
}
HTTP_LOG_LABELS = {
    "app": "APP LOG",
    "svc": "SVC LOG",
    "debug": "DEBUG LOG",
    "esp": "ESP LOG",
}


@dataclass
class _ServoWidget:
    frame: ttk.Frame
    mode_var: tk.StringVar
    value_var: tk.IntVar
    scale: ttk.Scale
    value_label: ttk.Label


class _TkQueueLogHandler(logging.Handler):
    """Thread-safe logging handler that forwards formatted records to a Tk-owned queue."""

    def __init__(self, sink: queue.Queue[str]) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:
            message = record.getMessage()
        try:
            self._sink.put_nowait(message)
        except queue.Full:
            # Drop old output under pressure rather than blocking worker threads.
            pass


class TkControlWindow:
    def __init__(
        self,
        root: tk.Tk,
        client,
        *,
        bot_ip: str,
        timeout: float,
        servo_types: tuple[int, ...],
        servo_angle_limits: tuple[tuple[int, int] | None, ...],
        initial_state: UiState,
    ) -> None:
        self.root = root
        self.client = client
        self.bot_ip = bot_ip
        self.timeout = timeout
        self.http_client = SoundHttpClient(bot_ip, timeout)
        self.running = True

        self._servo_types = list(servo_types)
        self._servo_angle_limits = servo_angle_limits
        self._servo_widgets: list[_ServoWidget] = []
        self._last_sent_at = [0.0] * proto.SERVO_COUNT
        self._suppress_slider_callback = False
        self._servo_last_value: list[int | None] = [None] * proto.SERVO_COUNT
        self._servo_last_sent_time = [0.0] * proto.SERVO_COUNT

        self._sounds: list[str] = []
        self._sound_refresh_lock = threading.Lock()
        self._sound_refresh_results: queue.Queue[tuple[str, list[str] | None]] = queue.Queue()
        self._ui_callbacks: queue.Queue[Callable[[], None]] = queue.Queue(maxsize=512)
        self._log_queue: queue.Queue[str] = queue.Queue(maxsize=2048)
        self._log_window: tk.Toplevel | None = None
        self._log_text: tk.Text | None = None
        self._log_paused = tk.BooleanVar(value=False)
        self._log_autoscroll = tk.BooleanVar(value=True)
        self._http_logs_window: tk.Toplevel | None = None
        self._http_logs_notebook: ttk.Notebook | None = None
        self._http_logs_texts: dict[str, tk.Text] = {}
        self._http_logs_buffers: dict[str, deque[str]] = {key: deque(maxlen=HTTP_LOG_MAX_LINES) for key in HTTP_LOG_PROBES}
        self._http_logs_paused = tk.BooleanVar(value=False)
        self._http_logs_autoscroll = tk.BooleanVar(value=True)
        self._http_logs_status_var = tk.StringVar(value="HTTP logs: idle")
        self._http_logs_fetch_lock = threading.Lock()
        self._http_log_endpoints: dict[str, str | None] = {key: None for key in HTTP_LOG_PROBES}
        self._http_logs_last_text: dict[str, str] = {key: "" for key in HTTP_LOG_PROBES}
        self._log_handler = _TkQueueLogHandler(self._log_queue)
        self._log_handler.setLevel(logging.INFO)
        self._log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"))
        self._root_logger = logging.getLogger()
        self._root_logger.addHandler(self._log_handler)
        self._rx_queue: queue.Queue[str] = queue.Queue(maxsize=4096)
        self._rx_messages: deque[str] = deque(maxlen=1000)
        self._rx_window: tk.Toplevel | None = None
        self._rx_text: tk.Text | None = None
        self._rx_paused = tk.BooleanVar(value=False)
        self._rx_autoscroll = tk.BooleanVar(value=True)
        self._rx_dirty = False

        self.screen_var = tk.StringVar(value=self._screen_label_for(initial_state.selected_screen))
        self.sound_var = tk.StringVar(value="NO SOUNDS")
        self.sound_status_var = tk.StringVar(value="SOUND: idle")
        self.status_var = tk.StringVar(value="UDP: initializing")
        self.servo_status_var = tk.StringVar(value="Servos: idle")

        self.huskylens_led_var = tk.BooleanVar(value=initial_state.huskylens_illumination_enabled)
        self.huskylens_rgb_var = tk.BooleanVar(value=initial_state.huskylens_rgb_light_enabled)
        self.huskylens_display_var = tk.BooleanVar(value=initial_state.huskylens_display_enabled)
        self.huskylens_algorithm_var = tk.StringVar(
            value=ALGORITHM_LABELS[max(0, min(proto.HUSKYLENS_ALGORITHM_MAX, initial_state.huskylens_algorithm_index))]
        )

        self.root.title("aMaker Controls")
        self.root.geometry("620x760")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if hasattr(self.client, "set_rx_message_callback"):
            self.client.set_rx_message_callback(self._on_udp_rx_message)

        self._build_menu()
        self._build_layout()
        self._trace("Native Tk control window initialized")
        self._refresh_status()
        self._poll_logs()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Traces and Logs", command=self.open_log_window)
        file_menu.add_command(label="HTTP Log Screens", command=self.open_http_logs_window)
        file_menu.add_command(label="UDP RX Monitor", command=self.open_udp_rx_window)
        file_menu.add_command(label="Exit", command=self.close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    def open_http_logs_window(self) -> None:
        if self._http_logs_window is not None and self._http_logs_window.winfo_exists():
            self._http_logs_window.deiconify()
            self._http_logs_window.lift()
            self._http_logs_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("SensorsScreen HTTP Logs")
        window.geometry("980x520")
        window.protocol("WM_DELETE_WINDOW", self._close_http_logs_window)

        controls = ttk.Frame(window, padding=(8, 8, 8, 4))
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Refresh Now", command=self._refresh_http_logs_now).pack(side=tk.LEFT)
        ttk.Button(controls, text="Clear", command=self._clear_http_logs).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(
            controls,
            text="Pause",
            variable=self._http_logs_paused,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(
            controls,
            text="Autoscroll",
            variable=self._http_logs_autoscroll,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(controls, textvariable=self._http_logs_status_var).pack(side=tk.RIGHT)

        notebook = ttk.Notebook(window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._http_logs_texts = {}

        for key in ("app", "svc", "debug", "esp"):
            tab = ttk.Frame(notebook)
            notebook.add(tab, text=HTTP_LOG_LABELS[key])
            scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL)
            text = tk.Text(tab, wrap="none", yscrollcommand=scrollbar.set)
            scrollbar.config(command=text.yview)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self._http_logs_texts[key] = text
            self._render_http_log_tab(key)

        self._http_logs_window = window
        self._http_logs_notebook = notebook
        self._trace("Opened HTTP log screens window")
        self._refresh_http_logs_now()
        self._schedule_http_logs_poll()

    def _close_http_logs_window(self) -> None:
        if self._http_logs_window is None:
            return
        try:
            self._http_logs_window.destroy()
        except tk.TclError:
            pass
        self._http_logs_window = None
        self._http_logs_notebook = None
        self._http_logs_texts = {}

    def _clear_http_logs(self) -> None:
        for key in self._http_logs_buffers:
            self._http_logs_buffers[key].clear()
            self._http_logs_last_text[key] = ""
            self._render_http_log_tab(key)

    def _render_http_log_tab(self, key: str) -> None:
        text = self._http_logs_texts.get(key)
        if text is None:
            return
        lines = self._http_logs_buffers[key]
        text.delete("1.0", tk.END)
        if lines:
            text.insert(tk.END, "\n".join(lines) + "\n")
        if self._http_logs_autoscroll.get():
            text.see(tk.END)

    def _schedule_http_logs_poll(self) -> None:
        if self.running and self._http_logs_window is not None and self._http_logs_window.winfo_exists():
            self._safe_after(HTTP_LOG_POLL_INTERVAL_MS, self._refresh_http_logs_now)

    def _refresh_http_logs_now(self) -> None:
        if self._http_logs_window is None or not self._http_logs_window.winfo_exists():
            return
        if self._http_logs_paused.get():
            self._http_logs_status_var.set("HTTP logs: paused")
            self._schedule_http_logs_poll()
            return
        if self._http_logs_fetch_lock.locked():
            self._schedule_http_logs_poll()
            return

        self._http_logs_status_var.set("HTTP logs: loading")

        def _worker() -> None:
            with self._http_logs_fetch_lock:
                results: dict[str, tuple[str | None, str | None, str | None]] = {}
                for key, probe_paths in HTTP_LOG_PROBES.items():
                    endpoint = self._http_log_endpoints.get(key)
                    paths = (endpoint,) if endpoint else probe_paths
                    try:
                        used_path, payload = self.http_client.request_first_text(paths)
                        results[key] = (payload, used_path, None)
                    except OSError as exc:
                        results[key] = (None, None, str(exc))

                def _apply() -> None:
                    ok_count = 0
                    for key, (payload, used_path, error_text) in results.items():
                        if payload is None:
                            if self._http_logs_last_text[key]:
                                self._http_logs_buffers[key].append(f"[{time.strftime('%H:%M:%S')}] HTTP error: {error_text}")
                                self._http_logs_last_text[key] = ""
                                self._render_http_log_tab(key)
                            continue

                        ok_count += 1
                        self._http_log_endpoints[key] = used_path
                        if payload == self._http_logs_last_text[key]:
                            continue
                        self._http_logs_last_text[key] = payload
                        lines = payload.splitlines()
                        self._http_logs_buffers[key].clear()
                        if lines:
                            self._http_logs_buffers[key].extend(lines[-HTTP_LOG_MAX_LINES:])
                        self._render_http_log_tab(key)

                    if ok_count == 0:
                        self._http_logs_status_var.set("HTTP logs: no endpoint found")
                    else:
                        self._http_logs_status_var.set(f"HTTP logs: {ok_count}/4 sources online")

                    self._schedule_http_logs_poll()

                self._enqueue_ui_callback(_apply)

        threading.Thread(target=_worker, daemon=True, name="tk-http-logs-refresh").start()

    def _on_udp_rx_message(self, message: str) -> None:
        timestamped = f"{time.strftime('%H:%M:%S')} {message}"
        try:
            self._rx_queue.put_nowait(timestamped)
        except queue.Full:
            pass

    def open_udp_rx_window(self) -> None:
        if self._rx_window is not None and self._rx_window.winfo_exists():
            self._rx_window.deiconify()
            self._rx_window.lift()
            self._rx_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("SensorsScreen UDP RX")
        window.geometry("980x460")
        window.protocol("WM_DELETE_WINDOW", self._close_udp_rx_window)

        controls = ttk.Frame(window, padding=(8, 8, 8, 4))
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Clear", command=self._clear_udp_rx_window).pack(side=tk.LEFT)
        ttk.Checkbutton(
            controls,
            text="Pause",
            variable=self._rx_paused,
            command=self._on_rx_pause_toggled,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(controls, text="Autoscroll", variable=self._rx_autoscroll).pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.Frame(window, padding=(8, 0, 8, 8))
        body.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL)
        text = tk.Text(body, wrap="none", yscrollcommand=scrollbar.set, height=20)
        scrollbar.config(command=text.yview)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._rx_window = window
        self._rx_text = text
        self._rx_dirty = True
        self._render_udp_rx_buffer()
        self._trace("Opened UDP RX monitor")

    def _close_udp_rx_window(self) -> None:
        if self._rx_window is None:
            return
        try:
            self._rx_window.destroy()
        except tk.TclError:
            pass
        self._rx_window = None
        self._rx_text = None

    def _clear_udp_rx_window(self) -> None:
        self._rx_messages.clear()
        self._rx_dirty = True
        self._render_udp_rx_buffer()

    def _on_rx_pause_toggled(self) -> None:
        if not self._rx_paused.get():
            self._rx_dirty = True
            self._render_udp_rx_buffer()

    def _render_udp_rx_buffer(self) -> None:
        if self._rx_text is None:
            return
        self._rx_text.delete("1.0", tk.END)
        if self._rx_messages:
            self._rx_text.insert(tk.END, "\n".join(self._rx_messages) + "\n")
        if self._rx_autoscroll.get():
            self._rx_text.see(tk.END)
        self._rx_dirty = False

    def open_log_window(self) -> None:
        if self._log_window is not None and self._log_window.winfo_exists():
            self._log_window.deiconify()
            self._log_window.lift()
            self._log_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("SensorsScreen Traces and Logs")
        window.geometry("900x420")
        window.protocol("WM_DELETE_WINDOW", self._close_log_window)

        controls = ttk.Frame(window, padding=(8, 8, 8, 4))
        controls.pack(fill=tk.X)
        ttk.Button(controls, text="Clear", command=self._clear_log_window).pack(side=tk.LEFT)
        ttk.Checkbutton(controls, text="Pause", variable=self._log_paused).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(controls, text="Autoscroll", variable=self._log_autoscroll).pack(side=tk.LEFT, padx=(8, 0))

        body = ttk.Frame(window, padding=(8, 0, 8, 8))
        body.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL)
        text = tk.Text(body, wrap="none", yscrollcommand=scrollbar.set, height=18)
        scrollbar.config(command=text.yview)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._log_window = window
        self._log_text = text
        self._trace("Opened traces/logs window")

    def _close_log_window(self) -> None:
        if self._log_window is None:
            return
        try:
            self._log_window.destroy()
        except tk.TclError:
            pass
        self._log_window = None
        self._log_text = None

    def _clear_log_window(self) -> None:
        if self._log_text is None:
            return
        self._log_text.delete("1.0", tk.END)

    def _append_log_line(self, message: str) -> None:
        if self._log_text is None:
            return
        self._log_text.insert(tk.END, f"{message}\n")
        if self._log_autoscroll.get():
            self._log_text.see(tk.END)

    def _poll_logs(self) -> None:
        callbacks_drained = 0
        while callbacks_drained < 100:
            try:
                callback = self._ui_callbacks.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except (tk.TclError, RuntimeError):
                # The window may be closing or Tk mainloop may have already ended.
                pass
            callbacks_drained += 1

        if self._log_text is not None and not self._log_paused.get():
            drained = 0
            while drained < 200:
                try:
                    message = self._log_queue.get_nowait()
                except queue.Empty:
                    break
                self._append_log_line(message)
                drained += 1

        rx_drained = 0
        while rx_drained < 500:
            try:
                message = self._rx_queue.get_nowait()
            except queue.Empty:
                break
            self._rx_messages.append(message)
            self._rx_dirty = True
            rx_drained += 1

        if self._rx_text is not None and self._rx_dirty and not self._rx_paused.get():
            self._render_udp_rx_buffer()

        if self.running:
            self._safe_after(100, self._poll_logs)

    def _safe_after(self, delay_ms: int, callback: Callable[[], None]) -> bool:
        try:
            self.root.after(delay_ms, callback)
            return True
        except (tk.TclError, RuntimeError):
            return False

    def _enqueue_ui_callback(self, callback: Callable[[], None]) -> None:
        try:
            self._ui_callbacks.put_nowait(callback)
        except queue.Full:
            self._trace("Dropped UI callback: queue full")

    def _trace(self, message: str) -> None:
        try:
            self._log_queue.put_nowait(f"{time.strftime('%H:%M:%S')} TRACE ui: {message}")
        except queue.Full:
            pass

    def _log_servo_command(self, channel: int, value: int, command_type: str) -> None:
        """Log servo command intent to tinker log."""
        try:
            servo_type = self._servo_types[channel]
            if servo_type == proto.SERVO_TYPE_CONTINUOUS:
                self._log_queue.put_nowait(f"{time.strftime('%H:%M:%S')} SERVO ui:      S{channel + 1} → speed:{value:+d}%")
            elif command_type == "angle":
                self._log_queue.put_nowait(f"{time.strftime('%H:%M:%S')} SERVO ui:      S{channel + 1} → {value}°")
            elif command_type == "type":
                type_label = MODE_TYPE_TO_LABEL.get(value, "unknown")
                self._log_queue.put_nowait(f"{time.strftime('%H:%M:%S')} SERVO ui:      S{channel + 1} type={type_label}")
        except queue.Full:
            pass

    def _update_servo_status_display(self) -> None:
        """Update the compact servo status line showing last values + timestamps."""
        parts = []
        for ch in range(proto.SERVO_COUNT):
            value = self._servo_last_value[ch]
            sent_time = self._servo_last_sent_time[ch]
            if sent_time == 0.0:
                parts.append(f"S{ch + 1}: —")
            else:
                time_str = time.strftime('%H:%M:%S', time.localtime(sent_time))
                servo_type = self._servo_types[ch]
                if value is None:
                    parts.append(f"S{ch + 1}: —")
                elif servo_type == proto.SERVO_TYPE_CONTINUOUS:
                    parts.append(f"S{ch + 1}: {value:+d}% @ {time_str}")
                else:
                    parts.append(f"S{ch + 1}: {value}° @ {time_str}")
        self.servo_status_var.set(" | ".join(parts))

    def _build_layout(self) -> None:
        container = ttk.Frame(self.root, padding=10)
        container.pack(fill=tk.BOTH, expand=True)

        self._build_screen_controls(container)
        self._build_led_controls(container)
        self._build_servo_controls(container)
        self._build_huskylens_controls(container)
        self._build_sound_controls(container)

        # Servo status display (last values sent)
        servo_status_label = ttk.Label(container, textvariable=self.servo_status_var, anchor="w", font=("TkDefaultFont", 8))
        servo_status_label.pack(fill=tk.X, pady=(0, 4))

        status_bar = ttk.Label(container, textvariable=self.status_var, anchor="w")
        status_bar.pack(fill=tk.X, pady=(10, 0))

    def _build_screen_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="K10 Screen")
        frame.pack(fill=tk.X, pady=(0, 8))

        screen_options = [label for label, _ in SCREEN_BUTTONS]
        combo = ttk.Combobox(frame, state="readonly", values=screen_options, textvariable=self.screen_var)
        combo.pack(side=tk.LEFT, padx=8, pady=8, fill=tk.X, expand=True)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._set_screen_from_var())

        ttk.Button(frame, text="Apply", command=self._set_screen_from_var).pack(side=tk.LEFT, padx=(0, 8), pady=8)

    def _build_servo_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Servos")
        frame.pack(fill=tk.BOTH, pady=(0, 8), expand=True)

        for channel in range(proto.SERVO_COUNT):
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, padx=8, pady=4)

            ttk.Label(row, text=f"S{channel + 1}", width=3).pack(side=tk.LEFT)

            mode_var = tk.StringVar(value=MODE_TYPE_TO_LABEL.get(self._servo_types[channel], "180"))
            mode_combo = ttk.Combobox(row, state="readonly", width=6, values=["180", "270", "CONT"], textvariable=mode_var)
            mode_combo.pack(side=tk.LEFT, padx=(4, 8))
            mode_combo.bind("<<ComboboxSelected>>", lambda _event, ch=channel: self._set_servo_mode(ch))

            value_var = tk.IntVar(value=0)
            scale = ttk.Scale(row, from_=0, to=100, orient=tk.HORIZONTAL)
            scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
            scale.configure(command=lambda raw, ch=channel: self._on_servo_slider(ch, raw))

            value_label = ttk.Label(row, text="0", width=9)
            value_label.pack(side=tk.LEFT, padx=6)

            ttk.Button(row, text="Stop", command=lambda ch=channel: self._on_servo_stop_clicked(ch)).pack(side=tk.LEFT)

            self._servo_widgets.append(_ServoWidget(row, mode_var, value_var, scale, value_label))
            self._configure_servo_scale(channel, keep_value=False)

        footer = ttk.Frame(frame)
        footer.pack(fill=tk.X, padx=8, pady=(8, 8))
        ttk.Button(footer, text="STOP ALL", command=self._on_stop_all_clicked).pack(side=tk.LEFT)

    def _build_led_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="LEDs")
        frame.pack(fill=tk.X, pady=(0, 8))

        grid = ttk.Frame(frame)
        grid.pack(fill=tk.X, padx=8, pady=8)

        for index, (label, color) in enumerate(LED_PRESETS):
            button = ttk.Button(grid, text=label, command=lambda rgb=color: self._set_led_color(rgb))
            row = index // 4
            column = index % 4
            button.grid(row=row, column=column, padx=4, pady=4, sticky="ew")

        for column in range(4):
            grid.columnconfigure(column, weight=1)

    def _build_huskylens_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="HuskyLens")
        frame.pack(fill=tk.X, pady=(0, 8))

        toggles = ttk.Frame(frame)
        toggles.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Checkbutton(toggles, text="LED", variable=self.huskylens_led_var,
                        command=lambda: self.client.queue_set_huskylens_illumination(self.huskylens_led_var.get())).pack(side=tk.LEFT)
        ttk.Checkbutton(toggles, text="RGB", variable=self.huskylens_rgb_var,
                        command=lambda: self.client.queue_set_huskylens_rgb_light(self.huskylens_rgb_var.get())).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Checkbutton(toggles, text="LCD", variable=self.huskylens_display_var,
                        command=lambda: self.client.queue_set_huskylens_display(self.huskylens_display_var.get())).pack(side=tk.LEFT, padx=(12, 0))

        algo_row = ttk.Frame(frame)
        algo_row.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Label(algo_row, text="Mode").pack(side=tk.LEFT)
        algo_combo = ttk.Combobox(algo_row, state="readonly", values=ALGORITHM_LABELS, textvariable=self.huskylens_algorithm_var, width=10)
        algo_combo.pack(side=tk.LEFT, padx=8)
        algo_combo.bind("<<ComboboxSelected>>", lambda _event: self._set_huskylens_algorithm_from_var())

    def _build_sound_controls(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Sound")
        frame.pack(fill=tk.X)

        row = ttk.Frame(frame)
        row.pack(fill=tk.X, padx=8, pady=(8, 4))

        self.sound_combo = ttk.Combobox(row, state="readonly", textvariable=self.sound_var)
        self.sound_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(row, text="Refresh", command=self.refresh_sounds).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row, text="Play", command=self.play_sound).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(frame, textvariable=self.sound_status_var).pack(anchor="w", padx=8, pady=(0, 8))

    def _screen_label_for(self, screen: int | None) -> str:
        if screen is None:
            return SCREEN_BUTTONS[0][0]
        for label, value in SCREEN_BUTTONS:
            if value == screen:
                return label
        return SCREEN_BUTTONS[0][0]

    def _set_screen_from_var(self) -> None:
        label = self.screen_var.get()
        self._set_screen_by_label(label)

    def _set_screen_by_label(self, label: str) -> None:
        for option_label, screen in SCREEN_BUTTONS:
            if option_label == label:
                self.screen_var.set(option_label)
                self.client.queue_set_screen(screen)
                self._trace(f"Requested screen: {option_label}")
                return

    def _set_huskylens_algorithm_from_var(self) -> None:
        label = self.huskylens_algorithm_var.get()
        if label in ALGORITHM_LABELS:
            self.client.queue_set_huskylens_algorithm(ALGORITHM_LABELS.index(label))
            self._trace(f"Requested HuskyLens algorithm: {label}")

    def _set_led_color(self, rgb: tuple[int, int, int]) -> None:
        red, green, blue = rgb
        self.client.queue_set_led_color(proto.LED_MASK_ALL, red, green, blue, 255)
        self._trace(f"Requested LED color: r={red} g={green} b={blue}")

    def _on_servo_stop_clicked(self, channel: int) -> None:
        self._stop_servo(channel)

    def _on_stop_all_clicked(self) -> None:
        self.client.queue_stop_all_motors()

    def _servo_bounds_for(self, channel: int, servo_type: int) -> tuple[int, int]:
        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            return (proto.SERVO_SPEED_MIN, proto.SERVO_SPEED_MAX)
        configured = self._servo_angle_limits[channel]
        if configured is not None:
            return configured
        if servo_type == proto.SERVO_TYPE_270:
            return (0, proto.SERVO_270_ANGLE_MAX)
        return (0, proto.SERVO_180_ANGLE_MAX)

    def _configure_servo_scale(self, channel: int, keep_value: bool = True) -> None:
        widget = self._servo_widgets[channel]
        servo_type = self._servo_types[channel]
        minimum, maximum = self._servo_bounds_for(channel, servo_type)

        current = round(widget.scale.get()) if keep_value else 0
        current = max(minimum, min(maximum, current))

        self._suppress_slider_callback = True
        widget.scale.configure(from_=minimum, to=maximum)
        widget.scale.set(current)
        self._suppress_slider_callback = False

        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            widget.value_label.config(text=f"{current:+d}%")
        else:
            widget.value_label.config(text=f"{current} deg")

    def _set_servo_mode(self, channel: int) -> None:
        widget = self._servo_widgets[channel]
        servo_type = MODE_LABEL_TO_TYPE.get(widget.mode_var.get(), proto.SERVO_TYPE_180)
        if self._servo_types[channel] == servo_type:
            return

        if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, 0, force=True)

        self._servo_types[channel] = servo_type
        self._servo_last_value[channel] = None
        self.client.queue_set_servo_type(channel, servo_type)
        self._configure_servo_scale(channel, keep_value=False)
        self._log_servo_command(channel, servo_type, "type")
        self._servo_last_sent_time[channel] = time.time()
        self._update_servo_status_display()

        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, 0, force=True)

    def _on_servo_slider(self, channel: int, raw_value: str) -> None:
        if self._suppress_slider_callback:
            return
        value = round(float(raw_value))

        servo_type = self._servo_types[channel]
        widget = self._servo_widgets[channel]
        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            widget.value_label.config(text=f"{value:+d}%")
        else:
            widget.value_label.config(text=f"{value} deg")

        if value == self._servo_last_value[channel]:
            return

        now = time.monotonic()
        if now - self._last_sent_at[channel] < DRAG_COMMAND_INTERVAL_S:
            return

        if servo_type == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, value)
        else:
            self.client.queue_set_servo_angle(channel, value)
        self._last_sent_at[channel] = now
        self._log_servo_command(channel, value, "angle" if servo_type != proto.SERVO_TYPE_CONTINUOUS else "speed")
        self._servo_last_value[channel] = value
        self._servo_last_sent_time[channel] = time.time()
        self._update_servo_status_display()

    def _stop_servo(self, channel: int) -> None:
        if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
            self.client.queue_set_servo_speed(channel, 0, force=True)
            self.set_external_value(channel, 0)
            self._trace(f"Requested S{channel + 1} stop")
            self._servo_last_value[channel] = 0
            self._servo_last_sent_time[channel] = time.time()
            self._update_servo_status_display()

    def set_external_value(self, channel: int, value: int) -> None:
        if not 0 <= channel < len(self._servo_widgets):
            return
        widget = self._servo_widgets[channel]
        minimum, maximum = self._servo_bounds_for(channel, self._servo_types[channel])
        clamped = max(minimum, min(maximum, value))

        self._suppress_slider_callback = True
        widget.scale.set(clamped)
        self._suppress_slider_callback = False

        if self._servo_types[channel] == proto.SERVO_TYPE_CONTINUOUS:
            widget.value_label.config(text=f"{clamped:+d}%")
        else:
            widget.value_label.config(text=f"{clamped} deg")

    def refresh_sounds(self) -> None:
        if self._sound_refresh_lock.locked():
            return

        self.sound_status_var.set("SOUND: loading")
        self._trace("Refreshing sound list via HTTP")

        def _worker() -> None:
            with self._sound_refresh_lock:
                try:
                    payload = self.http_client.list_sounds()
                    sounds = parse_sound_list(payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    self._sound_refresh_results.put(("offline", None))
                    return
                self._sound_refresh_results.put(("ok", sounds))

        def _apply_result() -> None:
            try:
                status, sounds = self._sound_refresh_results.get_nowait()
            except queue.Empty:
                if self._sound_refresh_lock.locked():
                    self._safe_after(50, _apply_result)
                return

            if status != "ok" or sounds is None:
                self.sound_status_var.set("SOUND: offline")
                self._trace("Sound refresh failed: endpoint offline or invalid payload")
                return

            self._sounds = sounds
            if sounds:
                self.sound_combo.configure(values=sounds)
                if self.sound_var.get() not in sounds:
                    self.sound_var.set(sounds[0])
                self.sound_status_var.set(f"SOUND: {len(sounds)} item(s)")
                self._trace(f"Sound refresh complete: {len(sounds)} item(s)")
            else:
                self.sound_combo.configure(values=[])
                self.sound_var.set("NO SOUNDS")
                self.sound_status_var.set("SOUND: empty")
                self._trace("Sound refresh complete: no sounds found")

        threading.Thread(target=_worker, daemon=True, name="tk-sound-refresh").start()
        self._safe_after(50, _apply_result)

    def play_sound(self) -> None:
        self._trigger_priority_play("play-button")

    def _trigger_priority_play(self, reason: str) -> None:
        sound = self.sound_var.get().strip()
        if not sound or sound == "NO SOUNDS":
            self.sound_status_var.set("SOUND: nothing selected")
            self._trace("Play sound ignored: nothing selected")
            return

        def _worker() -> None:
            self._enqueue_ui_callback(lambda: self.sound_status_var.set(f"SOUND: playing {sound}"))
            self._trace(f"Priority play ({reason}): {sound}")

            sent_via_udp = False
            if hasattr(self.client, "queue_play_sound") and hasattr(self.client, "queue_stop_sound"):
                try:
                    self.client.queue_stop_sound()
                    self.client.queue_play_sound(sound)
                    sent_via_udp = True
                except ValueError:
                    sent_via_udp = False

            if not sent_via_udp:
                # Fallback for environments using only HTTP sound controls.
                try:
                    self.http_client.stop_sound()
                except OSError:
                    pass
                try:
                    self.http_client.play_sound(sound)
                except OSError:
                    self._enqueue_ui_callback(lambda: self.sound_status_var.set("SOUND: play failed"))
                    self._trace(f"Play sound failed: {sound}")
                    return
            self._enqueue_ui_callback(lambda: self.sound_status_var.set(f"SOUND: played {sound}"))
            self._trace(f"Played sound: {sound}")

        threading.Thread(target=_worker, daemon=True, name="tk-sound-play").start()

    def _refresh_status(self) -> None:
        stats = self.client.stats()
        servo_status = self.client.command_status("servo-0")
        screen_status = self.client.command_status("k10-screen")
        self.status_var.set(
            f"UDP IN {stats.recv_rate:.1f}/s OUT {stats.sent_rate:.1f}/s | S1 {servo_status} | SCREEN {screen_status}"
        )
        self._update_servo_status_display()
        if self.running:
            self._safe_after(250, self._refresh_status)

    def get_persisted_state(self) -> UiState:
        selected_screen = None
        label = self.screen_var.get()
        for option_label, screen in SCREEN_BUTTONS:
            if option_label == label:
                selected_screen = screen
                break

        algorithm_index = ALGORITHM_LABELS.index(self.huskylens_algorithm_var.get())

        return UiState(
            selected_screen=selected_screen,
            huskylens_algorithm_index=algorithm_index,
            huskylens_illumination_enabled=self.huskylens_led_var.get(),
            huskylens_rgb_light_enabled=self.huskylens_rgb_var.get(),
            huskylens_display_enabled=self.huskylens_display_var.get(),
            servo_types=tuple(self._servo_types),
        )

    def close(self) -> None:
        self.running = False
        self._close_log_window()
        self._close_http_logs_window()
        self._close_udp_rx_window()
        if hasattr(self.client, "set_rx_message_callback"):
            self.client.set_rx_message_callback(None)
        try:
            self._root_logger.removeHandler(self._log_handler)
        except ValueError:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass
