"""
Link18 Keyboard Monitor Module
Handles global keyboard input for overlay activation, calibration, and GBU controls.
"""
from PyQt6.QtCore import pyqtSignal, QObject
from pynput import keyboard


class KeyMonitor(QObject):
    show_signal = pyqtSignal()
    hide_signal = pyqtSignal()
    debug_signal = pyqtSignal()
    broadcast_airfields_signal = pyqtSignal()  # New signal for manual broadcast
    calibrate_signal = pyqtSignal()  # New signal for calibration
    bomb_release_signal = pyqtSignal() # Signal for bomb release
    toggle_console_signal = pyqtSignal() # Signal for console toggle

    def __init__(self, activation_key='m'):
        super().__init__()
        self.activation_key = activation_key.lower()
        self.listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        self.listener.start()
        self.is_pressed = False
        self.gbu_enabled = True

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                if key.char.lower() == self.activation_key:
                    if not self.is_pressed:
                        self.is_pressed = True
                        self.show_signal.emit()
                elif key.char.lower() == 'n':
                    # If M is held and N is pressed, trigger calibration
                    if self.is_pressed:
                        self.calibrate_signal.emit()
                elif key.char.lower() == 'j':
                    self.toggle_console_signal.emit()
            elif key == keyboard.Key.space:
                if self.gbu_enabled:
                    self.bomb_release_signal.emit()
        except AttributeError:
            pass

    def on_release(self, key):
        try:
            if hasattr(key, 'char') and key.char and key.char.lower() == self.activation_key:
                self.is_pressed = False
                self.hide_signal.emit()
        except AttributeError:
            pass
