import pytest
from mecanum_control.app import MainWindow, SettingsDialog
from mecanum_control.config import Settings
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QImageWriter
from PySide6.QtWidgets import QApplication, QLineEdit


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def test_window_and_video(application, tmp_path):
    window = MainWindow(Settings(), tmp_path / "settings.json")
    try:
        window.show()
        application.processEvents()
        assert window.token.echoMode() == QLineEdit.EchoMode.Password
        assert window.translation_direction.text() == "Move  -"
        assert window.rotation_direction.text() == "Turn  -"
        assert "forward" in window.translation_direction.toolTip()
        assert "clockwise" in window.rotation_direction.toolTip()
        window.speed.setValue(25)
        assert window.settings.speed_limit == 25
        assert "token" not in (tmp_path / "settings.json").read_text()
        image = QImage(480, 320, QImage.Format.Format_RGB32)
        image.fill(QColor("#259977"))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        writer = QImageWriter(buffer, b"jpeg")
        assert writer.write(image)
        assert window.video.display(buffer.data().data())
        for width, height in ((1060, 740), (640, 480)):
            window.resize(width, height)
            application.processEvents()
            assert window.video.pixmap().width() <= window.video.width()
            assert window.video.pixmap().height() <= window.video.height()
            window.grab().save(str(tmp_path / f"desktop-{width}.png"))
        assert window.session is None
    finally:
        window.close()


def test_settings_dialog(application):
    dialog = SettingsDialog(Settings())
    dialog.host.setText("127.0.0.1")
    dialog.accept()
    assert dialog.settings.host == "127.0.0.1"


@pytest.mark.parametrize("setup_succeeds", [True, False])
@pytest.mark.parametrize("camera_enabled", [True, False])
def test_camera_waits_for_servo_setup(application, monkeypatch, tmp_path, setup_succeeds, camera_enabled):
    import mecanum_control.app as desktop
    from mecanum_control.camera import CameraStream
    from mecanum_control.udp_client import BotSession

    starts = []

    class OfflineSession(BotSession):
        def start(self, token):
            self.running = True
            self.status = "Configuring continuous servos"
        def alive(self):
            return self.running
        def close(self):
            self.running = False

    class OfflineCamera(CameraStream):
        def start(self):
            starts.append(self.url)

    monkeypatch.setattr(desktop, "BotSession", OfflineSession)
    monkeypatch.setattr(desktop, "CameraStream", OfflineCamera)
    window = MainWindow(Settings(), tmp_path / "settings.json")
    try:
        window.camera_enabled.setChecked(camera_enabled)
        window.toggle_connection()
        assert not window.camera_enabled.isEnabled()
        window.tick()
        assert not starts
        assert window.camera is None
        assert window.session is not None
        window.session.ready = setup_succeeds
        if not setup_succeeds:
            window.session.close()
        else:
            window.session.paused = False
            window.session.motion_confirmed = False
            window.tick()
            assert window.translation_direction.text() == "Move  ?"
            assert window.rotation_direction.text() == "Turn  ?"
            window.session.wheels = (4, 0, 2, -2)
            window.session.motion_confirmed = True
            window.tick()
            assert window.translation_direction.text() == "Move  ↗"
            assert window.rotation_direction.text() == "Turn  ⟳"
            window.session.paused = True
            window.tick()
            assert window.translation_direction.text() == "Move  -"
            assert window.rotation_direction.text() == "Turn  -"
        window.tick()
        if setup_succeeds and camera_enabled:
            assert starts == ["http://192.168.4.1:80/cam/stream"]
            window.tick()
            assert len(starts) == 1
        elif camera_enabled:
            assert not starts
            assert "setup failed" in window.video_status.text()
        else:
            assert not starts
            assert window.video_status.text() == "Camera disabled"
    finally:
        window.close()


def test_snap_desktop_restores_host_settings(monkeypatch):
    import mecanum_control.app as desktop
    environment = {
        "GSETTINGS_SCHEMA_DIR": "/snap/code/schemas",
        "GSETTINGS_SCHEMA_DIR_VSCODE_SNAP_ORIG": "",
        "GTK_PATH": "/snap/code/gtk",
        "GTK_PATH_VSCODE_SNAP_ORIG": "/host/gtk",
        "DISPLAY": ":0",
    }
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "environ", environment)
    desktop.restore_snap_desktop_environment()
    assert "GSETTINGS_SCHEMA_DIR" not in environment
    assert environment["GTK_PATH"] == "/host/gtk"
    assert environment["QT_QPA_PLATFORMTHEME"] == "generic"
    assert environment["DISPLAY"] == ":0"


def test_snap_desktop_preserves_explicit_theme(monkeypatch):
    import mecanum_control.app as desktop
    environment = {"GTK_PATH_VSCODE_SNAP_ORIG": "", "QT_QPA_PLATFORMTHEME": "custom"}
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop.os, "environ", environment)
    desktop.restore_snap_desktop_environment()
    assert environment["QT_QPA_PLATFORMTHEME"] == "custom"


@pytest.mark.parametrize("platform", ["linux", "win32", "darwin"])
def test_desktop_without_snap_is_unchanged(monkeypatch, platform):
    import mecanum_control.app as desktop
    environment = {"GTK_PATH": "/custom/gtk", "GSETTINGS_SCHEMA_DIR": "/custom/schemas"}
    original = environment.copy()
    monkeypatch.setattr(desktop.sys, "platform", platform)
    monkeypatch.setattr(desktop.os, "environ", environment)
    desktop.restore_snap_desktop_environment()
    assert environment == original


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_snap_markers_do_not_affect_other_platforms(monkeypatch, platform):
    import mecanum_control.app as desktop
    environment = {"GTK_PATH": "/custom/gtk", "GTK_PATH_VSCODE_SNAP_ORIG": ""}
    original = environment.copy()
    monkeypatch.setattr(desktop.sys, "platform", platform)
    monkeypatch.setattr(desktop.os, "environ", environment)
    desktop.restore_snap_desktop_environment()
    assert environment == original