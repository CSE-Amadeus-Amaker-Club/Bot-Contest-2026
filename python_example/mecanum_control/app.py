"""Camera-first native desktop application for Linux and Windows."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from dataclasses import replace
from pathlib import Path


def restore_snap_desktop_environment() -> None:
    """Restore host GTK settings and avoid Snap-inherited GNOME integration."""
    if sys.platform != "linux":
        return
    inherited_snap_desktop = False
    for name in ("GSETTINGS_SCHEMA_DIR", "GTK_PATH", "GTK_EXE_PREFIX",
                 "GTK_IM_MODULE_FILE", "GDK_BACKEND"):
        original_name = f"{name}_VSCODE_SNAP_ORIG"
        if original_name in os.environ:
            inherited_snap_desktop = True
            original = os.environ[original_name]
            if original:
                os.environ[name] = original
            else:
                os.environ.pop(name, None)
    if inherited_snap_desktop:
        os.environ.setdefault("QT_QPA_PLATFORMTHEME", "generic")


restore_snap_desktop_environment()

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .camera import CameraStream
from .config import Settings, default_path, load_settings, save_settings
from .drive import motion_arrows
from .gamepad import Gamepad
from .udp_client import BotSession

WHEEL_NAMES = ("Front left", "Front right", "Rear left", "Rear right")


class VideoView(QLabel):
    def __init__(self) -> None:
        super().__init__("Video disconnected")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 240)
        self.setStyleSheet("background: #161b1c; color: #cbd7d5;")
        self._image = QImage()

    def display(self, frame: bytes) -> bool:
        image = QImage.fromData(frame)
        if image.isNull() or image.width() > 4096 or image.height() > 4096:
            return False
        self._image = image
        self._render()
        return True

    def clear_video(self, text: str) -> None:
        self._image = QImage()
        self.clear()
        self.setText(text)

    def _render(self) -> None:
        if not self._image.isNull():
            self.setPixmap(QPixmap.fromImage(self._image).scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bot settings")
        self.settings = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.host = QLineEdit(settings.host)
        self.udp_port = QSpinBox()
        self.udp_port.setRange(1, 65535)
        self.udp_port.setValue(settings.udp_port)
        self.http_port = QSpinBox()
        self.http_port.setRange(1, 65535)
        self.http_port.setValue(settings.http_port)
        form.addRow("Bot IP / hostname", self.host)
        form.addRow("UDP port", self.udp_port)
        form.addRow("HTTP port", self.http_port)
        self.deadzone = QDoubleSpinBox()
        self.deadzone.setRange(0, 0.95)
        self.deadzone.setSingleStep(0.01)
        self.deadzone.setValue(settings.deadzone)
        self.rotation = QDoubleSpinBox()
        self.rotation.setRange(0, 2)
        self.rotation.setSingleStep(0.1)
        self.rotation.setValue(settings.rotation_gain)
        form.addRow("Stick deadzone", self.deadzone)
        form.addRow("Rotation sensitivity", self.rotation)
        layout.addLayout(form)
        grid = QGridLayout()
        grid.addWidget(QLabel("Wheel"), 0, 0)
        grid.addWidget(QLabel("Connector"), 0, 1)
        grid.addWidget(QLabel("Reverse"), 0, 2)
        self.channels = []
        self.inverted = []
        for row, name in enumerate(WHEEL_NAMES, 1):
            channel = QComboBox()
            channel.addItems([f"S{number}" for number in range(1, 7)])
            channel.setCurrentIndex(settings.channels[row - 1])
            inverted = QCheckBox()
            inverted.setChecked(settings.inverted[row - 1])
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(channel, row, 1)
            grid.addWidget(inverted, row, 2)
            self.channels.append(channel)
            self.inverted.append(inverted)
        layout.addLayout(grid)
        self.axes = QLineEdit(",".join(map(str, settings.axes)))
        self.buttons = QLineEdit(",".join(map(str, settings.buttons)))
        mapping = QFormLayout()
        mapping.addRow("Raw axes: right X, right Y, left X", self.axes)
        mapping.addRow("Raw buttons: A, B, X, Y", self.buttons)
        layout.addLayout(mapping)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        try:
            self.settings = replace(
                self.settings, host=self.host.text().strip(),
                udp_port=self.udp_port.value(), http_port=self.http_port.value(),
                deadzone=self.deadzone.value(), rotation_gain=self.rotation.value(),
                channels=tuple(widget.currentIndex() for widget in self.channels),
                inverted=tuple(widget.isChecked() for widget in self.inverted),
                axes=tuple(int(value.strip()) for value in self.axes.text().split(",")),
                buttons=tuple(int(value.strip()) for value in self.buttons.text().split(",")),
            )
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, "Invalid settings", str(error))
            return
        super().accept()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, config_path: Path) -> None:
        super().__init__()
        self.settings = settings
        self.config_path = config_path
        self.session: BotSession | None = None
        self.camera: CameraStream | None = None
        self.gamepad = Gamepad(settings)
        self._last_frame = 0.0
        self._camera_requested = False
        self._closing = False
        self.setWindowTitle("K10 Mecanum Bot")
        self.resize(1060, 740)
        self.setMinimumSize(640, 480)
        root = QWidget()
        layout = QVBoxLayout(root)
        toolbar = QHBoxLayout()
        self.endpoint = QLabel(f"{settings.host}:{settings.udp_port}")
        self.token = QLineEdit()
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setMaxLength(5)
        self.token.setPlaceholderText("Master token")
        self.token.setMaximumWidth(150)
        self.token.setAccessibleName("Master token")
        self.connect_button = QPushButton("Connect")
        self.connect_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self.connect_button.clicked.connect(self.toggle_connection)
        self.settings_button = QPushButton()
        self.settings_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.settings_button.setToolTip("Bot settings")
        self.settings_button.setAccessibleName("Bot settings")
        self.settings_button.clicked.connect(self.edit_settings)
        self.camera_enabled = QCheckBox("Camera")
        self.camera_enabled.setChecked(True)
        toolbar.addWidget(self.endpoint)
        toolbar.addStretch()
        toolbar.addWidget(self.camera_enabled)
        toolbar.addWidget(self.token)
        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(self.settings_button)
        layout.addLayout(toolbar)
        self.video = VideoView()
        layout.addWidget(self.video, 1)
        controls = QHBoxLayout()
        self.stop_button = QPushButton("STOP")
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.setStyleSheet("QPushButton {background: #be303a; color: white; font-weight: bold; padding: 10px 24px;}")
        self.stop_button.clicked.connect(self.stop_motion)
        self.resume_button = QPushButton("Resume")
        self.resume_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.resume_button.clicked.connect(self.resume_motion)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, 100)
        self.speed.setValue(settings.speed_limit)
        self.speed.setMinimumWidth(100)
        self.speed_label = QLabel(f"{settings.speed_limit}%")
        self.speed_label.setFixedWidth(45)
        self.speed.valueChanged.connect(self.change_speed)
        controls.addWidget(self.stop_button)
        controls.addWidget(self.resume_button)
        controls.addStretch()
        controls.addWidget(QLabel("Speed limit"))
        controls.addWidget(self.speed)
        controls.addWidget(self.speed_label)
        layout.addLayout(controls)
        self.connection_status = QLabel("Disconnected")
        self.controller_status = QLabel("No controller")
        self.video_status = QLabel("Video disconnected")
        self.wheel_status = QLabel("FL 0   FR 0   RL 0   RR 0")
        self.resume_button.setEnabled(False)
        for label in (self.connection_status, self.controller_status, self.video_status, self.wheel_status):
            label.setWordWrap(True)
            layout.addWidget(label)
        self.translation_direction = QLabel("Move  -")
        self.translation_direction.setFixedWidth(90)
        self.translation_direction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.translation_direction.setAccessibleName("Robot-relative translation direction")
        self.translation_direction.setToolTip("Translation: ↑ forward, ↓ backward, ←/→ strafe; diagonals combine them")
        self.rotation_direction = QLabel("Turn  -")
        self.rotation_direction.setFixedWidth(90)
        self.rotation_direction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rotation_direction.setAccessibleName("Robot-relative rotation direction")
        self.rotation_direction.setToolTip("Rotation: ⟲ counterclockwise, ⟳ clockwise")
        directions = QHBoxLayout()
        directions.addWidget(self.translation_direction)
        directions.addWidget(self.rotation_direction)
        directions.addStretch()
        layout.addLayout(directions)
        self.setCentralWidget(root)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(16)

    def toggle_connection(self) -> None:
        if self.session is not None and self.session.alive():
            self._camera_requested = False
            self.session.close()
            if self.camera is not None:
                self.camera.close()
            self.connect_button.setEnabled(False)
            return
        token = self.token.text()
        try:
            self.session = BotSession(self.settings)
            self.session.start(token)
        except (ValueError, UnicodeError, RuntimeError) as error:
            QMessageBox.warning(self, "Connection failed", str(error))
            return
        self.camera = None
        self._camera_requested = self.camera_enabled.isChecked()
        self.camera_enabled.setEnabled(False)
        self.video.clear_video("Waiting for control setup" if self._camera_requested else "Camera disabled")
        self.video_status.setText("Video waiting for control setup" if self._camera_requested else "Camera disabled")
        self._last_frame = 0
        self.connect_button.setText("Disconnect")
        self.settings_button.setEnabled(False)
        self.token.setEnabled(False)

    def stop_motion(self) -> None:
        if self.session is not None:
            self.session.pause("Paused: STOP")

    def resume_motion(self) -> None:
        if self.session is not None:
            self.session.resume()

    def change_speed(self, value: int) -> None:
        self.settings = replace(self.settings, speed_limit=value)
        self.speed_label.setText(f"{value}%")
        if self.session is not None:
            self.session.settings = replace(self.session.settings, speed_limit=value)
        try:
            save_settings(self.config_path, self.settings)
        except OSError as error:
            self.connection_status.setText(f"Settings not saved: {error}")

    def edit_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                save_settings(self.config_path, dialog.settings)
            except OSError as error:
                QMessageBox.warning(self, "Settings not saved", str(error))
                return
            self.settings = dialog.settings
            self.gamepad.settings = self.settings
            self.endpoint.setText(f"{self.settings.host}:{self.settings.udp_port}")

    def tick(self) -> None:
        snapshot, colors = self.gamepad.poll(self.isActiveWindow())
        sounds = self.gamepad.take_sounds()
        self.controller_status.setText(self.gamepad.name)
        if self.session is not None:
            self.session.update_input(snapshot)
            for color in colors:
                self.session.queue_led(color)
            for sound in sounds:
                self.session.queue_sound(sound)
            self.connection_status.setText(self.session.status)
            self.wheel_status.setText("   ".join(f"{name} {speed:+d}" for name, speed in zip(("FL", "FR", "RL", "RR"), self.session.wheels)))
            motion = self.session.motion_display
            if motion.paused:
                translation, rotation = "-", "-"
            elif motion.confirmed:
                translation, rotation = motion_arrows(motion.wheels, self.session.settings.inverted)
            else:
                translation, rotation = "?", "?"
            self.translation_direction.setText(f"Move  {translation}")
            self.rotation_direction.setText(f"Turn  {rotation}")
            active = self.session.alive()
            if active and self.session.ready and self._camera_requested and self.camera is None:
                self.camera = CameraStream(f"http://{self.settings.host}:{self.settings.http_port}/cam/stream")
                self.camera.start()
            self.resume_button.setEnabled(self.session.ready and self.session.paused)
            if not active:
                camera_requested = self._camera_requested
                self._camera_requested = False
                if self.camera is None and camera_requested:
                    self.video_status.setText("Video not started: control setup failed")
                    self.video.clear_video("Video not started")
                self.connect_button.setText("Connect")
                camera_closed = self.camera is None or not self.camera.alive()
                self.connect_button.setEnabled(camera_closed)
                self.settings_button.setEnabled(camera_closed)
                self.camera_enabled.setEnabled(camera_closed)
                self.token.setEnabled(True)
                if self.camera is not None:
                    self.camera.close()
        if self.camera is not None:
            frame = self.camera.take_frame()
            if frame is not None:
                if self.video.display(frame[0]):
                    self._last_frame = frame[1]
                else:
                    self.camera.status = "Video unavailable: invalid JPEG"
            self.video_status.setText(self.camera.status)
            if time.monotonic() - self._last_frame > 1.5:
                self.video.clear_video("Video unavailable")
                if self.camera.status == "Video live":
                    self.video_status.setText("Video stale")

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and not self.isActiveWindow() and self.session is not None:
            self.session.pause("Paused: window unfocused")

    def closeEvent(self, event) -> None:
        if self._closing:
            event.accept()
            return
        self._closing = True
        self.timer.stop()
        if self.session is not None:
            self.session.close()
            self.session.join()
        if self.camera is not None:
            self.camera.close()
            self.camera.join()
        self.gamepad.close()
        event.accept()


def main() -> int:
    parser = argparse.ArgumentParser(description="K10 mecanum camera and gamepad controller")
    parser.add_argument("--config", type=Path, default=default_path())
    parser.add_argument("--ip")
    parser.add_argument("--udp-port", type=int)
    parser.add_argument("--http-port", type=int)
    parser.add_argument("--no-camera", action="store_true")
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        overrides = {key: value for key, value in
                     (("host", args.ip), ("udp_port", args.udp_port), ("http_port", args.http_port)) if value is not None}
        settings = replace(settings, **overrides)
    except (OSError, ValueError, TypeError) as error:
        parser.error(str(error))
    app = QApplication(sys.argv[:1])
    app.setApplicationName("K10 Mecanum Bot")
    window = MainWindow(settings, args.config)
    window.camera_enabled.setChecked(not args.no_camera)
    signal.signal(signal.SIGINT, lambda *_args: window.close())
    signal.signal(signal.SIGTERM, lambda *_args: window.close())
    window.show()
    return app.exec()