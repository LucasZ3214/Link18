"""
Link18 Overlay Core
Contains the OverlayWindow class that combines all mixins.
Core state management, data processing, networking, and web sync.
"""
import math
import json
import time
import socket
import os

import requests

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QWidget, QApplication

from config import (
    CONFIG, UDP_PORT, API_URL, POLL_INTERVAL_MS, DEBUG_MODE, VERSION_TAG
)
from network import NetworkReceiver, TelemetryFetcher
from rendering import RenderingMixin
from gbu_hud import GbuHudMixin

# Lazy imports for optional modules
try:
    from jdamertti import BombTracker
except ImportError:
    class BombTracker:
        def __init__(self): self.bombs = []
        def update(self): pass
        def add_bomb(self, *a, **kw): pass
        def get_active_bombs(self): return []
        def get_logs(self): return []

try:
    from vws import SoundManager
except ImportError:
    class SoundManager:
        def __init__(self, **kw): self.enabled = False
        def play_warning(self, *a): pass
        def set_volume(self, v): pass
        def set_interval(self, i): self.interval = i

try:
    from auto_calibrate_new import auto_calibrate_map_v2
except ImportError:
    def auto_calibrate_map_v2(window): return False

try:
    from rwr_extractor import scan_rwr, RWR_AVAILABLE
except ImportError:
    RWR_AVAILABLE = False

try:
    from triangulation import triangulate, match_bearings
except ImportError:
    pass
    def scan_rwr(*args, **kwargs): return []


def print_startup_banner():
    """Display the Link18 welcome banner and config info."""
    WELCOME = r"""
    Welcome to Link18
    """
    print(WELCOME)
    print(f"[INFO] Callsign: {CONFIG.get('callsign', 'Unknown')}")
    print("[INFO] Calibrate map: Hold M + Press N")
    print(f"[INFO] Show overlay: Press {CONFIG.get('activation_key', 'm').upper()}")
    print(f"[INFO] Network: {CONFIG.get('broadcast_ip', 'N/A')}:{CONFIG.get('udp_port', 50050)}\n")


class OverlayWindow(RenderingMixin, GbuHudMixin, QWidget):
    """Main overlay window combining rendering and GBU mixins with core logic."""

    def __init__(self):
        super().__init__()
        self.config = CONFIG

        # --- Window Setup ---
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        screen = QApplication.primaryScreen()
        rect = screen.geometry()
        if DEBUG_MODE:
            print(f"DEBUG: Screen Geometry: {rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        self.setGeometry(rect)

        # --- Player / Map Data ---
        self.players = {}
        self.airfields = []
        self.shared_airfields = {}
        self.airfields_broadcasted = False
        self.pois = []
        self.user_pois = []
        self.shared_pois = {}
        self.pois_broadcasted = False

        # Physics Cache
        self.cached_predrop_text = None
        self.cached_predrop_color = QColor(150, 150, 150)
        self.cached_predrop_mode = "N/A"

        self.last_event_id = 0
        self.last_damage_id = 0
        self._last_log_t = 0
        self.local_chat_cache = []
        self.map_calibrated = False
        self.calibration_status = ""
        self.current_map_hash = None
        self.map_objectives = []
        self.map_ground_units = []

        self.show_formation_mode = False
        self.respawn_timers = []

        # Bomb Tracker & Console
        self.bomb_tracker = BombTracker()
        self.show_console = False
        self.current_pitch = 0.0

        # --- VWS ---
        vws_vol = float(self.config.get('vws_volume', 1.0))
        vws_int = float(self.config.get('vws_interval', 5.0))
        vws_norm = self.config.get('vws_normalize', False)
        vws_enabled = self.config.get('enable_vws', True)
        self.vws = SoundManager(volume=vws_vol, normalize=vws_norm, enabled=vws_enabled)
        self.vws.set_interval(vws_int)

        self.vws.play_warning('STARTUP')
        QTimer.singleShot(2000, lambda: self.vws.play_warning('WELCOME'))

        # Physics Timer (10Hz)
        self.phys_timer = QTimer(self)
        self.phys_timer.timeout.connect(self.update_physics)
        self.phys_timer.start(100)

        # --- RWR Detection ---
        # --- RWR Detection ---
        self.rwr_threats = []
        self.remote_rwr_bearings = {}  # {sender: {'x', 'y', 'bearings': [...]}}
        self.rwr_enabled = CONFIG.get('enable_rwr', False)
        self.rwr_bbox = CONFIG.get('rwr_bbox', [30, 340, 200, 200])
        self.current_roll = 0.0
        self.current_heading = 0.0
        self.player_x = None
        self.player_y = None

        if self.rwr_enabled and RWR_AVAILABLE:
            rwr_hz = CONFIG.get('rwr_scan_hz', 2)
            rwr_interval = max(100, int(1000 / rwr_hz))
            self.rwr_timer = QTimer(self)
            self.rwr_timer.timeout.connect(self._rwr_scan_tick)
            self.rwr_timer.start(rwr_interval)
            print(f"[RWR] Enabled at {rwr_hz}Hz (interval={rwr_interval}ms)")
        elif self.rwr_enabled:
            print("[RWR] Enabled in config but dependencies missing")

        # Persistence for Airfield Altitude
        self.known_airfields = self.load_airfields()

        self.show_marker = False
        self.status_text = "Initializing..."
        self.status_color = Qt.GlobalColor.yellow
        self.overlay_enabled = True
        self.show_gbu_timers = CONFIG.get('show_gbu_timers', False)

        # --- Networking ---
        self.net_thread = NetworkReceiver()
        self.net_thread.data_received.connect(self.update_network_data)
        self.net_thread.start()
        self.last_player_seen_time = 0

        self.players = {}
        self.sockets = []
        self.broadcast_ip = CONFIG.get('broadcast_ip', '255.255.255.255')

        # Detect all local interfaces
        self.local_ips = set(['127.0.0.1'])
        try:
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                self.local_ips.add(ip)

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                self.local_ips.add(s.getsockname()[0])
            except: pass
            finally: s.close()

        except Exception as e:
            print(f"[NET] Local IP detection warning: {e}")

        print(f"[NET] Local Interfaces Detected: {list(self.local_ips)}")

        # Create a socket bound to each specific IP
        for ip in list(self.local_ips):
            if ip == '127.0.0.1': continue

            if CONFIG.get('disable_lan_broadcast', False):
                if ip.startswith('192.168.') or ip.startswith('172.'):
                    print(f"[NET] Skipping LAN interface {ip} (Disabled in config)")
                    continue

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((ip, 0))
                self.sockets.append({'sock': sock, 'ip': ip})
                print(f"[NET] Bound broadcaster to {ip}")
            except Exception as e:
                print(f"[NET] Failed to bind to {ip}: {e}")

        if not self.sockets:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.sockets.append({'sock': sock, 'ip': 'Default'})
                print(f"[NET] Using default sender (0.0.0.0)")
            except:
                pass

        self.last_sync_attempt = 0

        # Suggest Virtual LAN Broadcast IP
        zt_ips = [ip for ip in self.local_ips if ip.startswith('10.')]
        if zt_ips:
            print("[NET] Virtual LAN Detected!")
            for ip in zt_ips:
                parts = ip.split('.')
                suggested_bc = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                if self.broadcast_ip != suggested_bc:
                    print(f"  [SUGGESTION] Set broadcast_ip to '{suggested_bc}' in config.json")
                else:
                    print(f"  [OK] Using Virtual LAN broadcast: {suggested_bc}")

        QTimer.singleShot(2000, self.broadcast_connection_test)

        self.show()

        # Data fetching (background thread)
        self.telem_fetcher = TelemetryFetcher(API_URL, poll_interval_s=POLL_INTERVAL_MS / 1000.0)
        self.telem_fetcher.data_ready.connect(self.on_telemetry_data)
        self.telem_fetcher.start()

        self.timer = QTimer()
        self.timer.timeout.connect(self.process_web_commands)
        self.timer.start(POLL_INTERVAL_MS)

        self.hud_timer = QTimer()
        self.hud_timer.timeout.connect(self.poll_hud_messages)
        self.hud_timer.start(1000)

        # Grid/Map Info
        self.map_min = None
        self.map_max = None

        # Marker scaling
        self.baseline_width = 834
        self.baseline_height = 834
        self.marker_scale = 1.0

        self.planning_waypoints = []

        # Flight Timer
        self.spawn_time = None
        self.flight_time = 0
        self.current_altitude = 0
        self.current_speed = 0
        self.current_vehicle_real_name = ""
        self.current_vehicle_raw_type = ""

        # Load Vehicle Map
        self.vehicle_map = self.load_vehicle_names()

        self.show_debug = CONFIG.get('debug_mode', False)

        # Web Dashboard Integration
        self.shared_data = {
            'players': {},
            'airfields': [],
            'pois': [],
            'map_info': {},
            'timer': {'flight_time': 0, 'spawn_time': None},
            'commands': [],
            'commander': {
                'markers': [],
                'drawings': [],
                'active_commanders': []
            }
        }

        if CONFIG.get('enable_web_map', True):
            try:
                from web_server import start_background_server
                start_background_server(self.shared_data, port=8000)
                print("[WEB] Web Map server initialized")
            except Exception as e:
                print(f"[WEB] Failed to start server: {e}")
        else:
            print("[WEB] Web Map disabled via config")

    # ─────────────────────────────────────────────
    # Network Data Handling
    # ─────────────────────────────────────────────

    def update_network_data(self, packet):
        pid = packet.get('id')
        x = packet.get('x')
        y = packet.get('y')

        if packet.get('type') == 'ping':
            return

        if not pid: return

        raw_vehicle = packet.get('vehicle', '')
        vehicle_real_name = ""
        if raw_vehicle:
            vehicle_real_name = self.vehicle_map.get(raw_vehicle)
            if not vehicle_real_name:
                vehicle_real_name = self.vehicle_map.get(raw_vehicle.lower())
            if not vehicle_real_name:
                vehicle_real_name = raw_vehicle

        if pid in self.local_ips or pid == '127.0.0.1':
            return

        if packet.get('sender') == CONFIG.get('callsign'):
            return

        # Airfield packet
        if packet.get('type') == 'airfield':
            if x is None or y is None or math.isnan(x) or math.isnan(y):
                return
            if abs(x) < 0.001 and abs(y) < 0.001:
                return
            for local_af in self.airfields:
                if abs(local_af['x'] - x) < 0.05 and abs(local_af['y'] - y) < 0.05:
                    return

            self.shared_airfields[pid] = {
                'x': x, 'y': y,
                'angle': packet.get('angle', 0),
                'len': packet.get('len', 0),
                'is_cv': packet.get('is_cv', False),
                'color': QColor(packet.get('color', '#FFFFFF')),
                'callsign': packet.get('callsign', 'Airfield'),
                'last_seen': time.time()
            }
            return

        # POI packet
        if packet.get('type') == 'point_of_interest':
            new_x = packet.get('x')
            new_y = packet.get('y')

            sender_key = packet.get('sender', packet.get('callsign', pid))

            position_changed = True
            if sender_key in self.shared_pois:
                old_x = self.shared_pois[sender_key]['x']
                old_y = self.shared_pois[sender_key]['y']
                if abs(old_x - new_x) < 0.001 and abs(old_y - new_y) < 0.001:
                    position_changed = False

            self.shared_pois[sender_key] = {
                'x': new_x, 'y': new_y,
                'color': QColor(packet.get('color', '#FFFFFF')),
                'icon': packet.get('icon', 'point_of_interest'),
                'callsign': packet.get('callsign', 'Unknown'),
                'player_color': QColor(packet.get('player_color', '#FF0000')),
                'last_seen': time.time()
            }

            if position_changed:
                print(f"[POI RX] {sender_key}: {packet.get('icon')} at ({new_x}, {new_y})")
                print(f"[POI RX] Total POIs stored: {len(self.shared_pois)}")
            return

        # Commander Mode packets
        if packet.get('type') == 'cmd_drawing_add':
            d_data = packet.get('data', {})
            if d_data.get('id'):
                existing_ids = [d.get('id') for d in self.shared_data['commander']['drawings']]
                if d_data['id'] not in existing_ids:
                    self.shared_data['commander']['drawings'].append(d_data)
                    self.update()
            return

        if packet.get('type') == 'cmd_drawing_clear':
            self.shared_data['commander']['drawings'] = []
            self.shared_data['commander']['markers'] = []
            self.update()
            return

        if packet.get('type') == 'cmd_marker_add':
            m_data = packet.get('data', {})
            if m_data.get('id'):
                existing_ids = [m.get('id') for m in self.shared_data['commander']['markers']]
                if m_data['id'] not in existing_ids:
                    self.shared_data['commander']['markers'].append(m_data)
                    self.update()
            return

        if packet.get('type') == 'cmd_marker_update':
            m_data = packet.get('data', {})
            if m_data and 'id' in m_data:
                for idx, m in enumerate(self.shared_data['commander']['markers']):
                    if m['id'] == m_data['id']:
                        self.shared_data['commander']['markers'][idx] = m_data
                        self.update()
                        break
            return

        # Team chat packet
        if packet.get('type') == 'team_chat':
            return

        # RWR Bearings packet
        if packet.get('type') == 'rwr_bearings':
            sender = packet.get('sender', packet.get('callsign', pid))
            self.remote_rwr_bearings[sender] = {
                'x': x,
                'y': y,
                'bearings': packet.get('bearings', []),
                'last_seen': time.time()
            }
            return

        # Player position packet
        existing_trail = self.players.get(pid, {}).get('trail', [])

        self.players[pid] = {
            'x': packet.get('x'),
            'y': packet.get('y'),
            'dx': packet.get('dx', 0) or 0,
            'dy': packet.get('dy', 0) or 0,
            'alt': packet.get('alt', 0) or 0,
            'spd': packet.get('spd', 0) or 0,
            'callsign': packet.get('callsign', f"Pilot {pid[-3:]}"),
            'vehicle': vehicle_real_name,
            'color': QColor(packet.get('color', '#00FFFF')),
            'last_seen': time.time(),
            'trail': existing_trail
        }

        if hasattr(self, 'shared_data') and 'players' in self.shared_data:
            self.shared_data['players'][pid] = self.players[pid]

        self.update_trail(self.players[pid])
        self.update()

    # ─────────────────────────────────────────────
    # Trail Management
    # ─────────────────────────────────────────────

    def update_trail(self, player_data):
        if 'trail' not in player_data:
            player_data['trail'] = []

        current_time = time.time()

        if hasattr(self, 'players') and player_data['trail']:
            last_pt = player_data['trail'][-1]
            dx = player_data['x'] - last_pt['x']
            dy = player_data['y'] - last_pt['y']
            dist_sq = dx * dx + dy * dy
            if dist_sq > 0.0025:
                player_data['trail'] = []
                is_respawn = True
            else:
                is_respawn = False
        else:
            is_respawn = False

        player_data['trail'].append({
            'x': player_data['x'],
            'y': player_data['y'],
            't': current_time
        })

        duration = float(CONFIG.get('trail_duration', 30))
        player_data['trail'] = [p for p in player_data['trail'] if current_time - p['t'] < duration]

        return is_respawn

    # ─────────────────────────────────────────────
    # Web Command Processing
    # ─────────────────────────────────────────────

    def process_web_commands(self):
        if hasattr(self, 'shared_data') and 'commands' in self.shared_data and self.shared_data['commands']:
            while self.shared_data['commands']:
                cmd = self.shared_data['commands'].pop(0)
                cmd_type = cmd.get('type') or cmd.get('action')

                if cmd_type == 'cmd_drawing_add':
                    d_data = cmd.get('data', {})
                    if d_data.get('id'):
                        self.shared_data['commander']['drawings'].append(d_data)
                        self.broadcast_packet({
                            'id': f"draw_{d_data['id']}",
                            'type': 'cmd_drawing_add',
                            'sender': CONFIG.get('callsign', 'Pilot'),
                            'data': d_data
                        })

                elif cmd_type == 'cmd_drawing_clear':
                    self.shared_data['commander']['drawings'] = []
                    self.shared_data['commander']['markers'] = []
                    self.broadcast_packet({
                        'id': f"clear_{int(time.time()*1000)}",
                        'type': 'cmd_drawing_clear',
                        'sender': CONFIG.get('callsign', 'Pilot')
                    })

                elif cmd_type == 'place_marker':
                    m_type = cmd.get('marker_type')
                    x = cmd.get('x')
                    y = cmd.get('y')
                    if m_type and x is not None and y is not None:
                        new_id = f"{m_type}_{int(time.time()*1000)}"
                        m_data = {
                            'id': new_id,
                            'type': m_type,
                            'x': x,
                            'y': y,
                            'callsign': cmd.get('callsign', 'Fighter')
                        }
                        self.shared_data['commander']['markers'].append(m_data)
                        print(f"[CMD] Placed {m_type} marker at {x:.3f}, {y:.3f}")
                        self.broadcast_packet({
                            'id': f"marker_{new_id}",
                            'type': 'cmd_marker_add',
                            'sender': CONFIG.get('callsign', 'Pilot'),
                            'data': m_data
                        })

                elif cmd_type == 'cmd_marker_update':
                    m_data = cmd.get('data')
                    if m_data and 'id' in m_data:
                        for idx, m in enumerate(self.shared_data['commander']['markers']):
                            if m['id'] == m_data['id']:
                                self.shared_data['commander']['markers'][idx] = m_data
                                break
                        self.broadcast_packet({
                            'id': f"upd_{m_data['id']}",
                            'type': 'cmd_marker_update',
                            'sender': CONFIG.get('callsign', 'Pilot'),
                            'data': m_data
                        })


                elif cmd_type == 'set_formation':
                    val = cmd.get('value', False)
                    self.shared_data['formation_mode'] = val
                    self.show_formation_mode = val
                    print(f"[CMD] Formation Mode set to: {val}")
                    self.update()

                elif cmd.get('type') == 'planning_update':
                    self.planning_waypoints = cmd.get('waypoints', [])
                    print(f"[PLAN] Updated {len(self.planning_waypoints)} waypoints from Web UI")
                    self.update()

                elif cmd_type == 'claim_commander':
                    req_callsign = cmd.get('callsign', 'Unknown')
                    current_cmd = self.shared_data['commander'].get('active_commander')
                    if not current_cmd or current_cmd == req_callsign:
                        self.shared_data['commander']['active_commander'] = req_callsign
                        print(f"[CMD] Commander assigned to: {req_callsign}")
                    else:
                        print(f"[CMD] Reject claim by {req_callsign} - {current_cmd} is already commander")

                elif cmd_type == 'release_commander':
                    req_callsign = cmd.get('callsign', 'Unknown')
                    current_cmd = self.shared_data['commander'].get('active_commander')
                    if current_cmd == req_callsign:
                        self.shared_data['commander']['active_commander'] = None
                        print(f"[CMD] Commander released by: {req_callsign}")

    # ─────────────────────────────────────────────
    # Airfield / Map Reference
    # ─────────────────────────────────────────────

    def check_and_record_airfield(self, x, y):
        if self.current_speed > 80:
            return

        if self.airfields:
            for af in self.airfields:
                af_key = f"{af['x']:.0f}_{af['y']:.0f}"
                dist = math.sqrt((x - af['x']) ** 2 + (y - af['y']) ** 2)
                if dist < 3000:
                    if self.known_airfields.get(af_key) != self.current_altitude:
                        self.known_airfields[af_key] = self.current_altitude
                        af['alt'] = self.current_altitude
                        self.save_airfields()
                        print(f"[AF] Recorded Persistent Altitude {self.current_altitude:.1f}m for Airfield at {af_key}")
                    break

    def set_marker_visible(self):
        self.show_marker = True
        self.update()

    def set_marker_hidden(self):
        self.show_marker = False
        self.update()

    def set_overlay_enabled(self, enabled):
        self.overlay_enabled = enabled
        self.update()

    def trigger_calibration(self):
        print("[CALIBRATE] Hiding overlay for clean screenshot...")
        self.hide()
        QApplication.processEvents()

        time.sleep(0.15)

        print("[CALIBRATE] Manual calibration triggered (M+N pressed)...")

        try:
            if auto_calibrate_map_v2(self):
                self.map_calibrated = True
                self.calibration_status = "Calibration OK"
                print("[CALIBRATE] Calibration successful!")
            else:
                self.calibration_status = "Calibration Failed - Try again (M+N)"
                print("[CALIBRATE] Calibration failed")
        except Exception as e:
            print(f"[CALIBRATE] Error during calibration: {e}")
            self.calibration_status = f"Error: {str(e)[:20]}..."
        finally:
            self.show()
            self.update()
            QTimer.singleShot(5000, self.clear_calibration_status)

    def clear_calibration_status(self):
        self.calibration_status = ""
        self.update()

    # ─────────────────────────────────────────────
    # ITO 90 Timer
    # ─────────────────────────────────────────────

    def start_ito90_timer(self, killer_name=""):
        current_time = time.time()
        grouped = False

        label_text = f"{killer_name} ItO 90M" if killer_name else "ItO 90M"

        for timer in self.respawn_timers:
            if "ITO90" in timer['label'] or "ITO 90" in timer['label'] or "ItO 90M" in timer['label']:
                if current_time - timer['last_update'] < 5.0:
                    timer['end_time'] = current_time + 900
                    timer['last_update'] = current_time
                    if killer_name:
                        timer['label'] = label_text
                    print(f"[TIMER] Grouped ITO 90 destruction. Reset to 15m.")
                    grouped = True
                    break

        if not grouped:
            self.respawn_timers.append({
                'label': label_text,
                'end_time': current_time + 900,
                'last_update': current_time
            })
            print(f"[TIMER] Started new ITO 90 respawn timer (15m): {label_text}")

        if hasattr(self, 'shared_data'):
            self.shared_data['respawn_timers'] = self.respawn_timers

        self.update()

    def poll_hud_messages(self):
        try:
            url = f"http://127.0.0.1:8111/hudmsg?lastEvt={self.last_event_id}&lastDmg={self.last_damage_id}"
            response = requests.get(url, timeout=0.5)

            if response.status_code == 200:
                data = response.json()

                events = data.get('events', [])
                if events:
                    for evt in events:
                        evt_id = evt.get('id', 0)
                        if evt_id > self.last_event_id:
                            self.last_event_id = evt_id

                damage = data.get('damage', [])
                if damage:
                    for dmg in damage:
                        dmg_id = dmg.get('id', 0)
                        msg = dmg.get('msg', '')

                        if dmg_id > self.last_damage_id:
                            self.last_damage_id = dmg_id

                            if "destroyed" in msg and "ItO 90M" in msg:
                                killer_name = ""
                                try:
                                    if " destroyed " in msg:
                                        parts = msg.split(" destroyed ")
                                        killer_name = parts[0].strip()
                                except:
                                    pass

                                print(f"[HUD] Detected ITO 90 Kill: {msg} (Killer: {killer_name})")
                                self.start_ito90_timer(killer_name)

        except Exception:
            pass

    # ─────────────────────────────────────────────
    # Map Reference / Grid
    # ─────────────────────────────────────────────

    def get_reference_grid_data(self):
        try:
            info_resp = requests.get("http://127.0.0.1:8111/map_info.json", timeout=0.15)
            if info_resp.status_code != 200:
                return None
            map_info = info_resp.json()

            map_min = map_info.get('map_min')
            map_max = map_info.get('map_max')
            grid_size = map_info.get('grid_size')
            grid_zero = map_info.get('grid_zero')

            if not map_min or not map_max or not grid_size or not grid_zero:
                return None

            return {
                'map_min': map_min,
                'map_max': map_max,
                'grid_size': grid_size,
                'grid_steps': map_info.get('grid_steps'),
                'grid_zero': grid_zero
            }
        except Exception:
            return None

    def refresh_map_bounds(self):
        ref_data = self.get_reference_grid_data()
        if ref_data:
            self.map_min = ref_data['map_min']
            self.map_max = ref_data['map_max']
            self.grid_steps = ref_data.get('grid_steps')
            self.grid_zero = ref_data.get('grid_zero')
            self.grid_size = ref_data.get('grid_size')
            self.map_bounds = ref_data
        return ref_data

    # ─────────────────────────────────────────────
    # Telemetry Processing
    # ─────────────────────────────────────────────

    def on_telemetry_data(self, fetched):
        try:
            data = fetched.get('map_data')
            if data is None:
                if hasattr(self, 'shared_data'):
                    self.shared_data['config'] = {
                        'callsign': CONFIG.get('callsign', 'Pilot'),
                        'color': CONFIG.get('color', '#FF0000'),
                        'version': VERSION_TAG
                    }
                return

            was_disconnected = self.status_text.startswith("Init") or "Error" in self.status_text or "Searching" in self.status_text
            if was_disconnected:
                self.status_text = "8111: OK"
                self.status_color = Qt.GlobalColor.green
                print("[STATUS] Connected to War Thunder API (8111)")

            current_time = time.time()

            self.bomb_tracker.update()

            expired_pids = [pid for pid, poi in self.shared_pois.items() if (current_time - poi.get('last_seen', 0) > 20)]
            for pid in expired_pids: del self.shared_pois[pid]

            inactive_players = [pid for pid, p in self.players.items() if pid != '_local' and (current_time - p.get('last_seen', 0) > 30)]
            for pid in inactive_players: del self.players[pid]

            last_map_sync = getattr(self, 'last_map_sync_time', 0)
            if self.map_min is None or (current_time - last_map_sync) > 8.0:
                map_info = fetched.get('map_info')
                if map_info:
                    map_min = map_info.get('map_min')
                    map_max = map_info.get('map_max')
                    grid_size = map_info.get('grid_size')
                    grid_zero = map_info.get('grid_zero')
                    if map_min and map_max and grid_size and grid_zero:
                        self.map_min = map_min
                        self.map_max = map_max
                        self.grid_steps = map_info.get('grid_steps')
                        self.grid_zero = grid_zero
                        self.grid_size = grid_size
                        self.map_bounds = map_info
                        if was_disconnected:
                            print("[STATUS] Map reference data synced.")
                self.last_map_sync_time = current_time

            last_af_broadcast = getattr(self, 'last_af_broadcast_time', 0)
            if self.airfields and (current_time - last_af_broadcast > 30.0):
                self.broadcast_airfields()
                self.last_af_broadcast_time = current_time

            state_data = fetched.get('state_data')
            if state_data:
                self.current_altitude = state_data.get('H, m', 0)
                self.current_speed = state_data.get('TAS, km/h', 0)

            ind_data = fetched.get('indicator_data')
            if ind_data:
                v_type = ind_data.get('type', '')
                self.current_pitch = ind_data.get('aviahorizon_pitch', 0.0)
                self.current_roll = ind_data.get('aviahorizon_roll', 0.0)
                if v_type:
                    real_name = self.vehicle_map.get(v_type)
                    if not real_name:
                        real_name = self.vehicle_map.get(v_type.lower())
                    if real_name:
                        self.current_vehicle_real_name = real_name
                    else:
                        self.current_vehicle_real_name = v_type
                    self.current_vehicle_raw_type = v_type

            self.process_data(data)

            # Merge Shared Airfields
            stale_timeout = 300.0
            current_time = time.time()
            stale_ids = [sh_id for sh_id, sh_af in self.shared_airfields.items()
                         if current_time - sh_af.get('last_seen', 0) > stale_timeout]
            for sh_id in stale_ids:
                del self.shared_airfields[sh_id]

            if self.shared_airfields:
                for sh_id, sh_af in self.shared_airfields.items():
                    if sh_af.get('sender') == CONFIG.get('callsign', 'Pilot'):
                        continue
                    is_duplicate = False
                    for existing_af in self.airfields:
                        dist = math.sqrt((existing_af['x'] - sh_af['x']) ** 2 + (existing_af['y'] - sh_af['y']) ** 2)
                        if dist < 0.05:
                            is_duplicate = True
                            break
                    if not is_duplicate:
                        self.airfields.append({
                            'x': sh_af['x'],
                            'y': sh_af['y'],
                            'angle': sh_af.get('angle', 0),
                            'len': sh_af.get('len', 0),
                            'is_cv': sh_af.get('is_cv', False),
                            'color': QColor(255, 128, 0),
                            'id': len(self.airfields) + 1
                        })

            # --- Web Map Data Sync ---
            if hasattr(self, 'shared_data'):
                self.shared_data['players'] = self.players.copy()

                if hasattr(self, 'player_x') and self.player_x is not None:
                    local_p = self.players.get('_local', {})
                    existing_trail = local_p.get('trail', [])
                    self.shared_data['players']['_local'] = {
                        'x': self.player_x,
                        'y': self.player_y,
                        'dx': local_p.get('dx', 0),
                        'dy': local_p.get('dy', 0),
                        'spd': self.current_speed,
                        'alt': self.current_altitude,
                        'vehicle': self.current_vehicle_real_name,
                        'callsign': CONFIG.get('callsign', 'Me'),
                        'color': CONFIG.get('color', '#FFCC11'),
                        'trail': existing_trail
                    }
                    self.update_trail(self.shared_data['players']['_local'])

                self.shared_data['airfields'] = list(self.airfields)

                pois_list = []
                for poi in getattr(self, 'user_pois', []):
                    pois_list.append({
                        'x': poi['x'], 'y': poi['y'],
                        'icon': poi.get('icon', 'poi'),
                        'color': poi.get('color', '#FFCC11'),
                        'owner': poi.get('owner', 'Me')
                    })
                for poi in self.pois:
                    pois_list.append({
                        'x': poi['x'], 'y': poi['y'],
                        'icon': poi.get('icon', ''),
                        'color': CONFIG.get('color', '#FFCC11'),
                        'owner': CONFIG.get('callsign', 'Me')
                    })
                for pid, poi in self.shared_pois.items():
                    pois_list.append({
                        'x': poi['x'], 'y': poi['y'],
                        'icon': poi.get('icon', ''),
                        'color': poi.get('player_color', QColor(255, 255, 255)),
                        'owner': poi.get('callsign', 'Unknown')
                    })
                self.shared_data['pois'] = pois_list

                current_t = time.time()
                self.respawn_timers = [t for t in self.respawn_timers if t['end_time'] > current_t]
                self.shared_data['respawn_timers'] = self.respawn_timers

                self.shared_data['objectives'] = self.map_objectives
                self.shared_data['ground_units'] = self.map_ground_units
                self.shared_data['timer'] = {
                    'flight_time': self.flight_time,
                    'spawn_time': self.spawn_time
                }
                if self.map_min and self.map_max:
                    self.shared_data['map_info'] = {
                        'map_min': self.map_min,
                        'map_max': self.map_max,
                        'grid_steps': getattr(self, 'grid_steps', None),
                        'grid_zero': getattr(self, 'grid_zero', None),
                        'grid_size': getattr(self, 'grid_size', None)
                    }

                # Sync RWR threats to web
                self.shared_data['rwr_threats'] = list(self.rwr_threats)

                # Sync config to web server
                self.shared_data['config'] = {
                    'callsign': CONFIG.get('callsign', 'Pilot'),
                    'color': CONFIG.get('color', '#FF0000'),
                    'version': VERSION_TAG
                }
        except Exception as e:
            print(f"[NET] Telemetry process error: {e}")

        self.update()

    # ─────────────────────────────────────────────
    # Data Processing (Map Objects)
    # ─────────────────────────────────────────────

    def load_airfields(self):
        try:
            if os.path.exists('airfields.json'):
                with open('airfields.json', 'r') as f:
                    return json.load(f)
        except json.JSONDecodeError:
            print("[AF] airfields.json was empty/corrupt, starting fresh.")
            return {}
        except Exception as e:
            print(f"[AF] Error loading airfields.json: {e}")
        return {}

    def load_vehicle_names(self):
        try:
            if os.path.exists('vehicles.json'):
                with open('vehicles.json', 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"[INIT] Error loading vehicles.json: {e}")
        return {}

    def save_airfields(self):
        try:
            with open('airfields.json', 'w') as f:
                json.dump(self.known_airfields, f, indent=4)
        except Exception as e:
            print(f"[AF] Error saving airfields.json: {e}")

    def process_data(self, data):
        found_player = False

        self.map_objectives = []
        self.map_ground_units = []
        for obj in data:
            otype = obj.get('type')
            if otype in ['bombing_point', 'defending_point']:
                self.map_objectives.append({
                    'x': obj.get('x'), 'y': obj.get('y'),
                    'type': otype, 'color': obj.get('color')
                })
            elif otype == 'capture_zone':
                self.map_objectives.append({
                    'x': obj.get('x'), 'y': obj.get('y'),
                    'type': otype, 'color': obj.get('color'),
                    'blink': obj.get('blink', 0)
                })
            elif otype in ['ground_unit', 'ground_model', 'transport', 'armoured', 'tank', 'artillery']:
                self.map_ground_units.append({
                    'x': obj.get('x'), 'y': obj.get('y'),
                    'icon': obj.get('icon'), 'color': obj.get('color')
                })

        # Detect airfields
        self.airfields = []
        for obj in data:
            if obj.get('type') == 'airfield':
                sx = obj.get('sx')
                sy = obj.get('sy')
                ex = obj.get('ex')
                ey = obj.get('ey')
                if sx is not None and sy is not None and ex is not None and ey is not None:
                    center_x = (sx + ex) / 2
                    center_y = (sy + ey) / 2
                    runway_angle = math.degrees(math.atan2(ey - sy, ex - sx))
                    runway_len = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2)

                    if math.isnan(center_x) or math.isnan(center_y):
                        continue

                    af_key = f"{center_x:.0f}_{center_y:.0f}"
                    known_alt = self.known_airfields.get(af_key)

                    is_duplicate_frame = False
                    for existing in self.airfields:
                        if abs(existing['x'] - center_x) < 0.05 and abs(existing['y'] - center_y) < 0.05:
                            if existing.get('len', 0) < 0.001 and runway_len > 0.001:
                                self.airfields.remove(existing)
                                is_duplicate_frame = False
                            else:
                                is_duplicate_frame = True
                            break
                    if is_duplicate_frame:
                        continue

                    self.airfields.append({
                        'x': center_x, 'y': center_y,
                        'angle': runway_angle,
                        'len': runway_len,
                        'color': QColor(obj.get('color', '#FFFFFF')),
                        'alt': known_alt,
                        'id': len(self.airfields) + 1
                    })

        if self.airfields and not hasattr(self, '_airfields_detected_logged'):
            print(f"[DETECT] Found {len(self.airfields)} airfield(s) from War Thunder API")
            self._airfields_detected_logged = True

        # Detect POIs
        self.pois = []
        for obj in data:
            if obj.get('type') == 'point_of_interest':
                x = obj.get('x')
                y = obj.get('y')
                if x is not None and y is not None:
                    self.pois.append({
                        'x': x, 'y': y,
                        'color': QColor(obj.get('color', '#FFFFFF')),
                        'icon': obj.get('icon', 'point_of_interest'),
                        'owner': obj.get('owner')
                    })

        if self.pois and not hasattr(self, '_pois_detected_logged'):
            print(f"[DETECT] Found {len(self.pois)} POI(s) from War Thunder API")
            self._pois_detected_logged = True

        # Detect player
        for obj in data:
            if obj.get('icon') == 'Player':
                x = obj.get('x')
                y = obj.get('y')
                dx = obj.get('dx', 0.0)
                dy = obj.get('dy', 0.0)

                # Store for RWR and other uses
                self.player_x = x
                self.player_y = y
                if dx != 0 or dy != 0:
                    self.current_heading = math.degrees(math.atan2(dx, -dy)) % 360

                if self.spawn_time is None:
                    self.spawn_time = time.time()
                    self.flight_time = 0
                    print("[STATUS] Player spawned - Timer started")
                    self.check_and_record_airfield(x, y)

                self.last_player_seen_time = time.time()

                existing_trail = getattr(self, 'saved_local_trail', [])

                self.players['_local'] = {
                    'x': x, 'y': y,
                    'dx': dx, 'dy': dy,
                    'alt': self.current_altitude,
                    'spd': self.current_speed,
                    'callsign': CONFIG.get('callsign', 'Me'),
                    'color': QColor(CONFIG.get('color', '#FF0000')),
                    'trail': existing_trail
                }

                is_respawn = self.update_trail(self.players['_local'])
                self.saved_local_trail = self.players['_local']['trail']

                if is_respawn or self.current_speed < 80:
                    self.check_and_record_airfield(x, y)

                found_player = True

                current_time = time.time()
                last_broadcast = getattr(self, 'last_af_broadcast', 0)
                if self.airfields and (current_time - last_broadcast > 30):
                    self.broadcast_airfields()
                    self.last_af_broadcast = current_time

                break

        if hasattr(self, 'saved_local_trail'):
            current_time = time.time()
            duration = float(CONFIG.get('trail_duration', 30))
            self.saved_local_trail = [p for p in self.saved_local_trail if current_time - p['t'] < duration]

        if not found_player:
            if '_local' in self.players:
                del self.players['_local']

            grace_period = 15.0
            last_seen = getattr(self, 'last_player_seen_time', 0)

            if self.spawn_time is not None:
                if (time.time() - last_seen) > grace_period:
                    self.spawn_time = None
                    self.flight_time = 0
                    print("[STATUS] Player lost > 15s - Timer reset")

            if self.airfields_broadcasted:
                self.airfields_broadcasted = False
                print("[STATUS] Player removed - Airfield broadcast flag reset")

        # Broadcast Local Position
        if '_local' in self.players:
            p = self.players['_local']
            packet = {
                'id': CONFIG.get('callsign', 'Pilot'),
                'type': 'player',
                'sender': CONFIG.get('callsign', 'Pilot'),
                'x': p['x'], 'y': p['y'],
                'dx': p['dx'], 'dy': p['dy'],
                'alt': p.get('alt', 0),
                'spd': p.get('spd', 0),
                'vehicle': self.current_vehicle_raw_type,
                'callsign': CONFIG.get('callsign', 'Pilot'),
                'color': CONFIG.get('color', '#FF0000')
            }
            self.broadcast_packet(packet)

        # Broadcast POIs periodically
        current_time = time.time()
        last_poi_broadcast = getattr(self, 'last_poi_broadcast', 0)
        if '_local' in self.players and (self.pois or getattr(self, 'user_pois', [])) and (current_time - last_poi_broadcast > 3.0):
            self.broadcast_pois()
            self.last_poi_broadcast = current_time


        # Prune old network players
        now = time.time()
        to_remove = []
        for pid, p in self.players.items():
            if pid == '_local': continue
            if 'last_seen' in p and (now - p['last_seen'] > 5.0):
                to_remove.append(pid)
        for pid in to_remove:
            del self.players[pid]

    # ─────────────────────────────────────────────
    # RWR Scanning
    # ─────────────────────────────────────────────

    def _rwr_scan_tick(self):
        """Periodic RWR scan callback with INS-like position stabilization."""
        if not self.rwr_enabled:
            return
        if self.player_x is None or self.player_y is None:
            return
        if self.map_min is None or self.map_max is None:
            return

        # Clean up stale remote bearings (>10s old)
        now = time.time()
        stale_senders = [k for k, v in self.remote_rwr_bearings.items() if now - v.get('last_seen', 0) > 10.0]
        for k in stale_senders:
            del self.remote_rwr_bearings[k]

        try:
            threats = scan_rwr(
                bbox=self.rwr_bbox,
                heading_deg=self.current_heading,
                roll_deg=self.current_roll,
                player_x=self.player_x,
                player_y=self.player_y,
                map_min=self.map_min,
                map_max=self.map_max
            )

            now = time.time()
            high_roll = abs(self.current_roll) > 30  # Suppress updates during hard banks

            if threats:
                # Match new detections to existing tracks
                for new_t in threats:
                    matched = False
                    for existing in self.rwr_threats:
                        # Match by proximity on the map (within ~3km normalized)
                        world_w = self.map_max[0] - self.map_min[0]
                        match_threshold = 3000 / world_w if world_w > 0 else 0.05
                        
                        ex_x = existing.get('raw_x', existing['x'])
                        ex_y = existing.get('raw_y', existing['y'])
                        
                        dx = new_t['x'] - ex_x
                        dy = new_t['y'] - ex_y
                        dist = math.sqrt(dx * dx + dy * dy)

                        if dist < match_threshold:
                            # Existing track found — smooth update (skip if high roll)
                            existing['timestamp'] = now
                            if new_t.get('label', 'UNK') != 'UNK':
                                existing['label'] = new_t['label']
                                existing['type'] = new_t.get('type', existing.get('type', 'UNK'))

                            ex_x = existing.get('raw_x', existing['x'])
                            ex_y = existing.get('raw_y', existing['y'])
                            ex_dist = existing.get('raw_dist_m', existing.get('dist_m', 0))

                            if not high_roll:
                                # Exponential moving average for position stability
                                alpha = 0.15
                                ex_x = ex_x * (1 - alpha) + new_t['x'] * alpha
                                ex_y = ex_y * (1 - alpha) + new_t['y'] * alpha
                                ex_dist = new_t.get('dist_m', ex_dist)
                            
                            existing['raw_x'] = ex_x
                            existing['raw_y'] = ex_y
                            existing['raw_dist_m'] = ex_dist
                            
                            # Restore single-source coordinates as default for the upcoming frame
                            existing['x'] = ex_x
                            existing['y'] = ex_y
                            existing['dist_m'] = ex_dist
                            
                            existing['bearing_abs'] = new_t.get('bearing_abs', existing.get('bearing_abs', 0))
                            existing['player_x'] = self.player_x
                            existing['player_y'] = self.player_y
                            matched = True
                            break

                    if not matched and not high_roll:
                        # New track — lock initial position
                        new_t['timestamp'] = now
                        new_t['raw_x'] = new_t['x']
                        new_t['raw_y'] = new_t['y']
                        new_t['raw_dist_m'] = new_t.get('dist_m', 0)
                        self.rwr_threats.append(new_t)

            # Expire old tracks (hold time = 5 seconds)
            self.rwr_threats = [
                t for t in self.rwr_threats
                if now - t.get('timestamp', 0) < 5.0
            ]

            # Broadcast local bearings
            if self.rwr_threats:
                local_bearings = []
                for t in self.rwr_threats:
                    if t.get('bearing_abs') is not None:
                        local_bearings.append({
                            'bearing_abs': round(t['bearing_abs'], 1),
                            'label': t.get('label', 'UNK')
                        })
                
                if local_bearings:
                    packet = {
                        'type': 'rwr_bearings',
                        'id': f"{CONFIG.get('callsign')}_rwr",
                        'sender': CONFIG.get('callsign', 'Pilot'),
                        'callsign': CONFIG.get('callsign', 'Me'),
                        'x': round(self.player_x, 4),
                        'y': round(self.player_y, 4),
                        'bearings': local_bearings
                    }
                    self.broadcast_packet(packet)

            # --- Multi-Aircraft Triangulation ---
            # Try to triangulate local threats with remote bearings
            if 'match_bearings' in globals() and self.remote_rwr_bearings:
                matched_groups = match_bearings(self.rwr_threats, self.remote_rwr_bearings, threshold_deg=15.0)
                for group in matched_groups:
                    res = triangulate(group)
                    if res:
                        # Find the local threat to update it
                        for t in self.rwr_threats:
                            if t.get('bearing_abs') == group[0]['bearing_deg']:
                                # Update position with triangulated result
                                t['x'] = res['x']
                                t['y'] = res['y']
                                t['is_triangulated'] = True
                                t['triangulation_confidence'] = res['confidence']
                                
                                # Convert triangulated normalized pos back to meters for distance
                                world_w = self.map_max[0] - self.map_min[0]
                                world_h = self.map_max[1] - self.map_min[1]
                                dx_norm = t['x'] - self.player_x
                                dy_norm = t['y'] - self.player_y
                                t['dist_m'] = math.sqrt((dx_norm * world_w)**2 + (dy_norm * world_h)**2)
                                break

            if CONFIG.get('debug_mode', False) and threats:
                print(f"[RWR] Active tracks: {len(self.rwr_threats)}, "
                      f"roll={self.current_roll:.1f}°, "
                      f"labels={[t.get('label','?') for t in self.rwr_threats]}")

        except Exception as e:
            print(f"[RWR] Scan error: {e}")

    def set_rwr_enabled(self, enabled):
        """Enable or disable RWR detection at runtime."""
        self.rwr_enabled = enabled
        if enabled and RWR_AVAILABLE and not hasattr(self, 'rwr_timer'):
            rwr_hz = CONFIG.get('rwr_scan_hz', 2)
            rwr_interval = max(100, int(1000 / rwr_hz))
            self.rwr_timer = QTimer(self)
            self.rwr_timer.timeout.connect(self._rwr_scan_tick)
            self.rwr_timer.start(rwr_interval)
            print(f"[RWR] Enabled at {rwr_hz}Hz")
        elif not enabled and hasattr(self, 'rwr_timer'):
            self.rwr_timer.stop()
            self.rwr_threats = []
            print("[RWR] Disabled")

    # ─────────────────────────────────────────────
    # Broadcasting
    # ─────────────────────────────────────────────

    def broadcast_airfields(self):
        if not self.airfields:
            print("[BROADCAST] No airfields detected to broadcast")
            return

        print(f"[BROADCAST] Broadcasting {len(self.airfields)} airfield(s)...")

        for idx, airfield in enumerate(self.airfields):
            stable_suffix = f"{airfield['x']:.2f}_{airfield['y']:.2f}"
            packet_id = f"{CONFIG.get('callsign', 'Pilot')}_af_{stable_suffix}"

            label_prefix = "CV" if airfield.get('is_cv') else "AF"

            packet = {
                'id': packet_id,
                'type': 'airfield',
                'sender': CONFIG.get('callsign', 'Pilot'),
                'callsign': CONFIG.get('callsign', 'Pilot'),
                'x': airfield['x'],
                'y': airfield['y'],
                'angle': airfield['angle'],
                'len': airfield.get('len', 0),
                'is_cv': airfield.get('is_cv', False),
                'color': airfield['color'].name(),
                'label': f"{label_prefix}{idx + 1}"
            }
            print(f"[BROADCAST]   [{idx + 1}] ID={packet_id}, Pos=({airfield['x']:.3f}, {airfield['y']:.3f})")
            self.broadcast_packet(packet)

        self.airfields_broadcasted = True

    def broadcast_connection_test(self):
        test_packet = {
            'id': CONFIG.get('callsign', 'Pilot'),
            'type': 'team_chat',
            'sender': '[System]',
            'message': f"{CONFIG.get('callsign', 'Pilot')} is now Online",
            'timestamp': time.time()
        }
        print(f"[NET] Sending startup connection test...")
        self.broadcast_packet(test_packet)

    def broadcast_pois(self):
        all_pois = list(self.pois) + list(getattr(self, 'user_pois', []))

        if not all_pois:
            return

        print(f"[BROADCAST] Broadcasting {len(all_pois)} POI(s)...")

        for idx, poi in enumerate(all_pois):
            stable_suffix = f"{poi['x']:.3f}_{poi['y']:.3f}"
            packet_id = f"{CONFIG.get('callsign', 'Pilot')}_poi_{stable_suffix}"

            packet = {
                'id': packet_id,
                'type': 'point_of_interest',
                'sender': CONFIG.get('callsign', 'Pilot'),
                'x': poi['x'],
                'y': poi['y'],
                'color': poi['color'].name() if isinstance(poi.get('color'), QColor) else poi.get('color', '#FFCC11'),
                'icon': poi.get('icon', 'poi'),
                'callsign': CONFIG.get('callsign', 'Me'),
                'player_color': CONFIG.get('color', '#FFCC11')
            }
            self.broadcast_packet(packet)

        self.pois_broadcasted = True

    def broadcast_packet(self, packet):
        try:
            msg = json.dumps(packet).encode('utf-8')

            targets = set()
            targets.add(('255.255.255.255', UDP_PORT))
            if self.broadcast_ip and self.broadcast_ip != '255.255.255.255':
                targets.add((self.broadcast_ip, UDP_PORT))

            for sock_info in self.sockets:
                sock = sock_info['sock']
                for target in targets:
                    try:
                        sock.sendto(msg, target)
                    except Exception:
                        pass

        except Exception as e:
            print(f"[NET] Broadcast Error: {e}")
