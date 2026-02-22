"""
Link18 UI Module
Contains SettingsDialog and ControllerWindow for system tray integration.
"""
import json

from PyQt6.QtCore import Qt, QPointF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QIcon, QAction,
    QPainterPath
)
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QScrollArea, QLineEdit, QSpinBox, QDoubleSpinBox,
    QCheckBox, QPushButton, QLabel, QFrame,
    QSystemTrayIcon, QMenu, QApplication
)

from config import CONFIG, VERSION_TAG


class SettingsDialog(QDialog):
    """Settings popup to edit all config.json values via GUI"""
    def __init__(self, overlay_window, parent=None):
        super().__init__(parent)
        self.overlay = overlay_window
        self.setWindowTitle(f"Link18 Settings - {VERSION_TAG}")
        self.setMinimumWidth(420)
        self.setStyleSheet("""
            QGroupBox { font-weight: bold; margin-top: 10px; padding-top: 16px; }
            QPushButton { padding: 6px 12px; }
        """)
        self.fields = {}
        self.build_ui()

    def build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(4)

        # --- Identity ---
        grp = QGroupBox("Identity")
        g = QFormLayout()
        self.add_text(g, "callsign", "Callsign")
        self.add_text(g, "color", "Color (hex)", placeholder="#FFCC11")
        grp.setLayout(g)
        layout.addWidget(grp)

        # --- Network ---
        grp = QGroupBox("Network")
        g = QFormLayout()
        self.add_text(g, "broadcast_ip", "Broadcast IP")
        self.add_int(g, "udp_port", "UDP Port", 1024, 65535)
        self.add_bool(g, "disable_lan_broadcast", "Disable LAN Broadcast")
        grp.setLayout(g)
        layout.addWidget(grp)

        # --- Map Overlay ---
        grp = QGroupBox("Map Overlay")
        g = QFormLayout()
        self.add_bool(g, "enable_map_overlay", "Enable Map Overlay")
        self.add_text(g, "activation_key", "Activation Key")
        self.add_int(g, "map_offset_x", "Map Offset X", 0, 9999)
        self.add_int(g, "map_offset_y", "Map Offset Y", 0, 9999)
        self.add_int(g, "map_width", "Map Width", 100, 9999)
        self.add_int(g, "map_height", "Map Height", 100, 9999)
        self.add_int(g, "trail_duration", "Trail Duration (s)", 0, 3600)
        grp.setLayout(g)
        layout.addWidget(grp)

        # --- Web Map ---
        grp = QGroupBox("Web Map")
        g = QFormLayout()
        self.add_bool(g, "enable_web_map", "Enable Web Map")
        self.add_float(g, "web_marker_scale", "Marker Scale", 0.1, 10.0, 1)
        grp.setLayout(g)
        layout.addWidget(grp)

        # --- Audio / VWS ---
        grp = QGroupBox("Audio / VWS")
        g = QFormLayout()
        self.add_bool(g, "enable_vws", "Enable VWS")
        self.add_float(g, "vws_volume", "Volume", 0.0, 1.0, 2)
        self.add_float(g, "vws_interval", "Warning Interval (s)", 0.1, 60.0, 1)
        self.add_bool(g, "vws_normalize", "Normalize Audio")
        grp.setLayout(g)
        layout.addWidget(grp)

        # --- Advanced ---
        grp = QGroupBox("Advanced")
        g = QFormLayout()
        self.add_int(g, "timer_interval", "Timer Interval (min)", 1, 120)
        self.add_bool(g, "unit_is_kts", "Speed in Knots")
        self.add_bool(g, "debug_mode", "Debug Mode")
        grp.setLayout(g)
        layout.addWidget(grp)

        scroll.setWidget(container)

        # Buttons
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save && Apply")
        save_btn.clicked.connect(self.save_settings)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(scroll)
        main_layout.addLayout(btn_layout)

    # --- Field Helpers ---
    def add_text(self, layout, key, label, placeholder=""):
        w = QLineEdit(str(CONFIG.get(key, "")))
        if placeholder:
            w.setPlaceholderText(placeholder)
        self.fields[key] = ('text', w)
        layout.addRow(label + ":", w)

    def add_int(self, layout, key, label, min_v=0, max_v=99999):
        w = QSpinBox()
        w.setRange(min_v, max_v)
        w.setValue(int(CONFIG.get(key, 0)))
        self.fields[key] = ('int', w)
        layout.addRow(label + ":", w)

    def add_float(self, layout, key, label, min_v=0.0, max_v=100.0, decimals=2):
        w = QDoubleSpinBox()
        w.setRange(min_v, max_v)
        w.setDecimals(decimals)
        w.setSingleStep(0.1)
        w.setValue(float(CONFIG.get(key, 0.0)))
        self.fields[key] = ('float', w)
        layout.addRow(label + ":", w)

    def add_bool(self, layout, key, label):
        w = QCheckBox()
        w.setChecked(bool(CONFIG.get(key, False)))
        self.fields[key] = ('bool', w)
        layout.addRow(label + ":", w)

    def save_settings(self):
        """Collect values, update CONFIG, write to disk, apply live"""
        for key, (ftype, widget) in self.fields.items():
            if ftype == 'text':
                CONFIG[key] = widget.text()
            elif ftype == 'int':
                CONFIG[key] = widget.value()
            elif ftype == 'float':
                CONFIG[key] = round(widget.value(), 4)
            elif ftype == 'bool':
                CONFIG[key] = widget.isChecked()

        # Save to disk
        try:
            with open('config.json', 'w') as f:
                json.dump(CONFIG, f, indent=4)
            print("[SETTINGS] Config saved to config.json")
        except Exception as e:
            print(f"[SETTINGS] Error saving config: {e}")

        # Apply live changes where possible
        if hasattr(self.overlay, 'sound_manager'):
            sm = self.overlay.sound_manager
            sm.set_volume(CONFIG.get('vws_volume', 0.5))
            sm.set_interval(CONFIG.get('vws_interval', 5))
            sm.enabled = CONFIG.get('enable_vws', True)

        self.overlay.show_debug = CONFIG.get('debug_mode', False)

        self.accept()
        print("[SETTINGS] Settings applied.")


class ControllerWindow(QWidget):
    def __init__(self, overlay_window):
        super().__init__()
        self.overlay = overlay_window
        self.setup_tray()
        self.setup_ui()
        
        # Start Timer for Player List Updates
        self.player_timer = QTimer(self)
        self.player_timer.timeout.connect(self.update_player_list)
        self.player_timer.start(2000)
        self.setStyleSheet("background-color: #F0F0F0;")
        # Start minimized to tray
        self.hide()
        
    def setup_tray(self):
        """Create system tray icon with context menu"""
        self.tray = QSystemTrayIcon(self)
        
        from PyQt6.QtGui import QPixmap
        pix = QPixmap(64, 64)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(32, 32)
        s = 3.5
        p.setPen(QPen(QColor(255, 255, 255), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 30, 30)
        path = QPainterPath()
        path.moveTo(0, -10 * s)
        path.lineTo(-6 * s, 8 * s)
        path.lineTo(0, 4 * s)
        path.lineTo(6 * s, 8 * s)
        path.closeSubpath()
        p.setPen(QPen(QColor(0, 0, 0), 2))
        p.setBrush(QBrush(QColor('#FFCC11')))
        p.drawPath(path)
        p.end()
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip("Link18 Tactical Overlay")
        
        menu = QMenu()
        show_action = QAction("Show Controller", self)
        show_action.triggered.connect(self.toggle_window)
        menu.addAction(show_action)
        
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        
        menu.addSeparator()
        quit_action = QAction("Quit Link18", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_click)
        self.tray.show()
    
    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window()
    
    def toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def setup_ui(self):
        self.setWindowTitle(f"Link18 Controller - {VERSION_TAG}")
        self.setGeometry(100, 100, 350, 400)
        
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Settings Button
        settings_btn = QPushButton(" Open Settings")
        settings_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d2d44; 
                color: white; 
                padding: 10px; 
                font-weight: bold; 
                border-radius: 5px; 
                border: 1px solid #555;
            }
            QPushButton:hover { background-color: #3d3d54; }
        """)
        settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(settings_btn)
        
        # Map URL Link
        map_url = QLabel("<a href='http://localhost:8000' style='color: #043FFF; text-decoration: none;'>Web Map: http://localhost:8000</a>")
        map_url.setOpenExternalLinks(True)
        map_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_url.setStyleSheet("font-size: 14px; margin: 5px 0;")
        layout.addWidget(map_url)

        # -- Toggles Group --
        toggles_group = QWidget()
        toggles_layout = QVBoxLayout(toggles_group)
        toggles_layout.setContentsMargins(5, 5, 5, 5)
        toggles_layout.setSpacing(5)
        
        self.overlay_toggle = QCheckBox("Enable Map Overlay")
        self.overlay_toggle.setChecked(CONFIG.get('default_map_visible', True))
        self.overlay_toggle.setStyleSheet("font-size: 14px; color: #222;")
        self.overlay_toggle.stateChanged.connect(self.toggle_overlay)
        toggles_layout.addWidget(self.overlay_toggle)
        
        self.formation_toggle = QCheckBox("Enable Formation Mode")
        self.formation_toggle.setChecked(False)
        self.formation_toggle.setStyleSheet("font-size: 14px; color: #222;")
        self.formation_toggle.stateChanged.connect(self.toggle_formation)
        toggles_layout.addWidget(self.formation_toggle)
        
        self.gbu_toggle = QCheckBox("Enable GBU Timers (BETA)")
        self.gbu_toggle.setChecked(True)
        self.gbu_toggle.setStyleSheet("font-size: 14px; color: #222;")
        self.gbu_toggle.stateChanged.connect(self.toggle_gbu)
        toggles_layout.addWidget(self.gbu_toggle)
        
        layout.addWidget(toggles_group)
        
        # -- Online Players --
        players_frame = QFrame()
        players_frame.setStyleSheet("background-color: #FFFFFF; border: 1px solid #ccc; border-radius: 5px;")
        p_layout = QVBoxLayout(players_frame)
        
        players_header = QLabel("Online Players:")
        players_header.setStyleSheet("font-weight: bold; color: #333; border: none;")
        p_layout.addWidget(players_header)
        
        self.players_label = QLabel("Waiting for data...")
        self.players_label.setStyleSheet("color: #555; padding: 2px; border: none;")
        self.players_label.setWordWrap(True)
        p_layout.addWidget(self.players_label)
        
        layout.addWidget(players_frame)
        
        layout.addStretch()
        
        # Shutdown Button
        shutdown_btn = QPushButton("TERMINATE APP")
        shutdown_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shutdown_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff4444; 
                color: white; 
                padding: 12px; 
                font-weight: bold; 
                border-radius: 5px;
                border: none;
            }
            QPushButton:hover { background-color: #cc0000; }
        """)
        shutdown_btn.clicked.connect(self.quit_app)
        layout.addWidget(shutdown_btn)
        
        # Version Label
        version_label = QLabel(f"Version: {VERSION_TAG}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        version_label.setStyleSheet("color: #888; font-size: 10px; margin-top: 5px;")
        layout.addWidget(version_label)
        
        self.setLayout(layout)
        
    def toggle_overlay(self, state):
        enabled = (state == 2)
        self.overlay.set_overlay_enabled(enabled)
        print(f"[CONTROLLER] Overlay {'ENABLED' if enabled else 'DISABLED'}")

    def toggle_formation(self, state):
        enabled = (state == 2)
        self.overlay.show_formation_mode = enabled
        print(f"[CONTROLLER] Formation Mode {'ENABLED' if enabled else 'DISABLED'}")

    def toggle_gbu(self, state):
        enabled = (state == 2)
        self.overlay.show_gbu_timers = enabled
        if hasattr(self, 'monitor'):
            self.monitor.gbu_enabled = enabled
        print(f"[CONTROLLER] GBU Timers {'ENABLED' if enabled else 'DISABLED'}")
        QTimer.singleShot(500, self.update_player_list)

    def update_player_list(self):
        """Refresh the online players display"""
        players = self.overlay.players
        
        lines = []
        
        if '_local' in players:
            p = players['_local']
            cards = self.format_player_card(p, is_local=True)
            lines.append(cards)
            
        others = {k: v for k, v in players.items() if k != '_local'}
        if others:
            for pid, p in others.items():
                lines.append(self.format_player_card(p, is_local=False))
        
        if not lines:
            self.players_label.setText("No players connected")
            return

        final_html = "<br>".join(lines)
        self.players_label.setText(final_html)

    def format_player_card(self, p, is_local=False):
        name = p.get('callsign', 'Unknown')
        
        color_val = p.get('color', '#FFFFFF')
        if hasattr(color_val, 'name'):
            hex_color = color_val.name()
        else:
            hex_color = str(color_val)
            
        spd = p.get('spd', 0) or 0
        alt = p.get('alt', 0) or 0
        vehicle = p.get('vehicle', '')
        
        if spd > 5 and alt > 50:
            status = "In Flight"
            status_color = "#44CC44"
        elif spd > 1:
            status = "On Ground"
            status_color = "#CCCC44"
        else:
            status = "In Hangar"
            status_color = "#888888"
            
        vehicle_str = f' ({vehicle})' if vehicle else ''
        
        prefix = "YOU" if is_local else "PLY"
        prefix_style = "font-weight:bold; color:#00BBFF;" if is_local else "color:#999;"
        
        return (
            f'<span style="{prefix_style}">[{prefix}]</span> '
            f'<span style="color:{hex_color};">●</span> {name}'
            f'{vehicle_str}'
            f' — <span style="color:{status_color};">{status}</span>'
        )

    def open_settings(self):
        dlg = SettingsDialog(self.overlay, self)
        dlg.exec()
        
    def closeEvent(self, event):
        event.ignore()
        self.hide()
    
    def quit_app(self, *args):
        """Actually quit the application"""
        self.overlay.close()
        self.tray.hide()
        QApplication.quit()
