"""
Link18 Tactical Overlay - Entry Point
All logic is split across modules:
  config.py      - Configuration loading and constants
  key_monitor.py - Keyboard input handling
  network.py     - NetworkReceiver & TelemetryFetcher
  overlay.py     - OverlayWindow core logic
  rendering.py   - Paint/drawing mixin
  gbu_hud.py     - GBU/JDAM HUD mixin
  ui.py          - SettingsDialog & ControllerWindow
"""
import sys
import os
import traceback
from datetime import datetime

# Disable High DPI scaling before QApplication is created
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from config import CONFIG
from key_monitor import KeyMonitor
from overlay import OverlayWindow, print_startup_banner
from ui import ControllerWindow


def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler to log crash and show message"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))

    # 1. Log to file
    try:
        with open("crash.log", "w") as f:
            f.write(f"Crash Time: {datetime.now()}\n")
            f.write("--------------------------------------------------\n")
            f.write(error_msg)
    except Exception as e:
        print(f"Failed to write crash log: {e}")

    print("CRITICAL ERROR:", error_msg)

    # 2. Show user alert (if GUI is running)
    app = QApplication.instance()
    if app:
        try:
            error_box = QMessageBox()
            error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setText("Link18 has crashed!")
            error_box.setInformativeText(
                "An unexpected error occurred. A crash log has been saved to 'crash.log'.\n\n"
                "Please send this log to the developer."
            )
            error_box.setDetailedText(error_msg)
            error_box.setWindowTitle("Link18 Critical Error")
            error_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            error_box.exec()
        except:
            pass

    sys.exit(1)


def main():
    # Register global exception handler
    sys.excepthook = handle_exception

    # Display welcome screen
    print_startup_banner()

    app = QApplication(sys.argv)

    # Create Overlay (Hidden/Transparent)
    overlay = OverlayWindow()

    # Create Controller (starts hidden in system tray)
    app.setQuitOnLastWindowClosed(False)
    controller = ControllerWindow(overlay)

    overlay.show()

    # Setup global key monitor
    activation_key = CONFIG.get('activation_key', 'm')
    monitor = KeyMonitor(activation_key)
    monitor.show_signal.connect(overlay.set_marker_visible, Qt.ConnectionType.QueuedConnection)
    monitor.hide_signal.connect(overlay.set_marker_hidden, Qt.ConnectionType.QueuedConnection)
    monitor.broadcast_airfields_signal.connect(overlay.broadcast_airfields, Qt.ConnectionType.QueuedConnection)
    monitor.calibrate_signal.connect(overlay.trigger_calibration, Qt.ConnectionType.QueuedConnection)
    monitor.bomb_release_signal.connect(overlay.on_bomb_release, Qt.ConnectionType.QueuedConnection)
    monitor.toggle_console_signal.connect(overlay.toggle_console, Qt.ConnectionType.QueuedConnection)
    controller.monitor = monitor

    sys.exit(app.exec())


if __name__ == "__main__":
    main()