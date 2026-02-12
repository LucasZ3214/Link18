import sys
import math
import requests
import socket
import json
import os
import time
from datetime import datetime
import numpy as np
from PIL import Image, ImageDraw
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal, QObject, QThread, QLineF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QFontMetrics, QPainterPath
from pynput import keyboard
from auto_calibrate_new import auto_calibrate_map_v2  # Import new calibration logic
import web_server # Import Web Server Module
from jdamertti import BombTracker # Import BombTracker
from vws import SoundManager # Import VWS

# Configuration
# Load Configuration
try:
    with open('config.json', 'r') as f:
        CONFIG = json.load(f)
except Exception as e:
    print(f"Config Load Error: {e}")
    CONFIG = {
        "callsign": "Pilot",
        "color": "#FF0000",
        "udp_port": 50050,
        "broadcast_ip": "255.255.255.255"
    }

API_URL = "http://127.0.0.1:8111/map_obj.json"
POLL_INTERVAL_MS = 100
UDP_PORT = CONFIG.get('udp_port', 50050)
UDP_BROADCAST_IP = CONFIG.get('broadcast_ip', "255.255.255.255")

# ==========================================
# MAP AREA CONFIGURATION
# Adjust these values in config.json to match the position of the map on your screen.
# ==========================================
MAP_OFFSET_X = CONFIG.get('map_offset_x', 715)      # Pixel offset from left
MAP_OFFSET_Y = CONFIG.get('map_offset_y', 183)      # Pixel offset from top
MAP_WIDTH = CONFIG.get('map_width', 834)            # Width of the map area in pixels
MAP_HEIGHT = CONFIG.get('map_height', 834)          # Height of the map area in pixels
DEBUG_MODE = CONFIG.get('debug_mode', False)        # Enable/disable debug print statements

# Keyboard Monitor Class
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

class NetworkReceiver(QThread):
    data_received = pyqtSignal(dict)
    
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('0.0.0.0', UDP_PORT))
            if DEBUG_MODE:
                print(f"[NET] NetworkReceiver listening on 0.0.0.0:{UDP_PORT}")
        except Exception as e:
            print(f"[NET] FATAL: NetworkReceiver failed to bind to port {UDP_PORT}: {e}")
            return
        
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                packet = json.loads(data.decode('utf-8'))
                # No longer overwriting ID with IP to support multi-interface reception deduplication
                self.data_received.emit(packet)
            except Exception as e:
                print(f"UDP Recv Error: {e}")
                time.sleep(1)

class TelemetryFetcher(QThread):
    """Background thread for HTTP polling - prevents audio stutter"""
    data_ready = pyqtSignal(dict)  # Emits all fetched data
    
    def __init__(self, api_url, poll_interval_s=0.1):
        super().__init__()
        self.api_url = api_url
        self.poll_interval = poll_interval_s
        self._running = True
    
    def run(self):
        while self._running:
            result = {
                'map_data': None,
                'state_data': None,
                'indicator_data': None,
                'map_info': None,
            }
            
            try:
                # Fetch main map data
                resp = requests.get(self.api_url, timeout=0.3)
                if resp.status_code == 200:
                    result['map_data'] = resp.json()
            except:
                pass
            
            try:
                # Fetch state (altitude, speed)
                resp = requests.get("http://127.0.0.1:8111/state", timeout=0.1)
                if resp.status_code == 200:
                    result['state_data'] = resp.json()
            except:
                pass
            
            try:
                # Fetch indicators (vehicle type, pitch)
                resp = requests.get("http://127.0.0.1:8111/indicators", timeout=0.1)
                if resp.status_code == 200:
                    result['indicator_data'] = resp.json()
            except:
                pass
            
            try:
                # Fetch map info (bounds, grid)
                resp = requests.get("http://127.0.0.1:8111/map_info.json", timeout=0.2)
                if resp.status_code == 200:
                    result['map_info'] = resp.json()
            except:
                pass
            
            # Emit all data at once (thread-safe via signal)
            if result['map_data'] is not None:
                self.data_ready.emit(result)
            
            time.sleep(self.poll_interval)
    
    def stop(self):
        self._running = False

class OverlayWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = CONFIG # Access global config
               
        # Window setup for transparent overlay
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Full screen logic
        screen = QApplication.primaryScreen()
        rect = screen.geometry()
        if DEBUG_MODE:
            print(f"DEBUG: Screen Geometry: {rect.x()},{rect.y()} {rect.width()}x{rect.height()}")
        self.setGeometry(rect)
        
        self.players = {} # {'id': {'x':0, 'y':0, 'dx':0, 'dy':0, 'color': QColor}}
        self.airfields = [] # List of airfield locations
        self.shared_airfields = {} # Airfields shared by other players
        self.airfields_broadcasted = False # Track if we've broadcasted airfields this session
        self.pois = [] # List of points of interest (Game Objects)
        self.user_pois = [] # List of user-created POIs (Web/Shared)
        self.shared_pois = {} # POIs shared by other players
        self.pois_broadcasted = False # Track if we've broadcasted POIs this session
        
        # Physics Cache (Optimize Render Loop)
        self.cached_predrop_text = None
        self.cached_predrop_color = QColor(150, 150, 150)
        self.cached_predrop_mode = "N/A"
        
        self.team_chat_messages = [] # Received team chat messages from network
        self.last_chat_id = 0 # Track last processed chat message ID
        self._last_log_t = 0 # Timer for diagnostic logging
        self.local_chat_cache = []  # Cache of local messages from 8111 API (for deduplication)
        self.map_calibrated = False # Track if map has been calibrated
        self.calibration_status = "" # Status message for calibration
        self.current_map_hash = None # Track current map to detect changes
        self.map_objectives = []
        self.map_objectives = []
        self.map_ground_units = []
        
        self.show_formation_mode = False # Toggle state for Formation Info
        
        # Bomb Tracker & Console
        self.bomb_tracker = BombTracker()
        self.show_console = False
        self.current_pitch = 0.0 # From indicators
        
        # --- VWS ---
        vws_vol = float(self.config.get('vws_volume', 1.0))
        vws_int = float(self.config.get('vws_interval', 5.0))
        vws_norm = self.config.get('vws_normalize', False)
        vws_enabled = self.config.get('enable_vws', True)
        self.vws = SoundManager(volume=vws_vol, normalize=vws_norm, enabled=vws_enabled)
        self.vws.set_interval(vws_int)
        
        # Play Startup Sequence
        self.vws.play_warning('STARTUP')
        QTimer.singleShot(2000, lambda: self.vws.play_warning('WELCOME'))
        
        # Physics Timer (10Hz - Decoupled from Render)
        self.phys_timer = QTimer(self)
        self.phys_timer.timeout.connect(self.update_physics)
        self.phys_timer.start(100)
        
        # Persistence for Airfield Altitude
        self.known_airfields = self.load_airfields()
        
        self.show_marker = False
        self.status_text = "Initializing..."
        self.status_color = Qt.GlobalColor.yellow
        self.overlay_enabled = True # Added toggle state
        self.show_gbu_timers = True # Global GBU timer toggle
        
        # Networking
        self.net_thread = NetworkReceiver()
        self.net_thread.data_received.connect(self.update_network_data)
        self.net_thread.start()  # CRITICAL: Start the receiver thread!
        self.last_player_seen_time = 0 
        
        # Initialize Data structures
        self.players = {}
        self.sockets = []
        self.broadcast_ip = CONFIG.get('broadcast_ip', '255.255.255.255')
        
        # 1. Try to detect all local interfaces (More Robustly)
        self.local_ips = set(['127.0.0.1'])
        try:
            # Method 1: Hostname-based
            hostname = socket.gethostname()
            for ip in socket.gethostbyname_ex(hostname)[2]:
                self.local_ips.add(ip)
            
            # Method 2: Connection-based probe (doesn't send data)
            # This helps find the IP used for external/ZeroTier routes
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Use a dummy non-routable IP
                s.connect(("8.8.8.8", 80))
                self.local_ips.add(s.getsockname()[0])
            except: pass
            finally: s.close()
            
        except Exception as e:
            print(f"[NET] Local IP detection warning: {e}")
            
        print(f"[NET] Local Interfaces Detected: {list(self.local_ips)}")
        
        # 2. Create a socket bound to each specific IP
        for ip in list(self.local_ips):
            if ip == '127.0.0.1': continue # Skip loopback for broadcasting
            
            # Check for LAN broadcast disablement (Default: False)
            if CONFIG.get('disable_lan_broadcast', False):
                # Standard LAN IP ranges (RFC 1918) - but let's keep it simple for 192.168/172
                if ip.startswith('192.168.') or ip.startswith('172.'):
                    print(f"[NET] Skipping LAN interface {ip} (Disabled in config)")
                    continue

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.bind((ip, 0)) # Bind to ephemeral port on this specific IP
                self.sockets.append({'sock': sock, 'ip': ip})
                print(f"[NET] Bound broadcaster to {ip}")
            except Exception as e:
                print(f"[NET] Failed to bind to {ip}: {e}")

        # 3. Fallback: If no specific bindings succeeded, use default 0.0.0.0
        if not self.sockets:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                self.sockets.append({'sock': sock, 'ip': 'Default'})
                print(f"[NET] Using default sender (0.0.0.0)")
            except:
                pass

        self.last_sync_attempt = 0
        
        # 4. Suggest Virtual LAN Broadcast IP
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
                    
        # 5. Send Connection Test Packet
        QTimer.singleShot(2000, self.broadcast_connection_test)
        
        self.show()

        # Data fetching (background thread - no main thread blocking)
        self.telem_fetcher = TelemetryFetcher(API_URL, poll_interval_s=POLL_INTERVAL_MS / 1000.0)
        self.telem_fetcher.data_ready.connect(self.on_telemetry_data)
        self.telem_fetcher.start()
        
        # Lightweight timer for non-HTTP tasks only
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_web_commands)
        self.timer.start(POLL_INTERVAL_MS)
        
        # Chat polling timer (every 2 seconds)
        self.chat_timer = QTimer()
        self.chat_timer.timeout.connect(self.poll_team_chat)
        self.chat_timer.start(2000)  # 2 second interval
        
        # Handle T- Timer logic (target: XX:00:00 every polling interval)
        
        # Grid/Map Info
        self.map_min = None
        self.map_max = None
        
        # Marker scaling based on resolution
        self.baseline_width = 834  # Baseline map width (from current config)
        self.baseline_height = 834  # Baseline map height (from current config)
        self.baseline_height = 834  # Baseline map height (from current config)
        self.marker_scale = 1.0  # Scale factor for markers
        
        self.planning_waypoints = [] # Waypoints from Web Plan
        
        # Flight Timer
        self.spawn_time = None
        self.flight_time = 0
        self.current_altitude = 0  # Current altitude in meters from /state endpoint
        self.current_speed = 0  # Current speed (TAS) in km/h
        self.current_speed = 0  # Current speed (TAS) in km/h
        self.current_vehicle_real_name = "" # Resolved Real Name (e.g. "F-16C")
        self.current_vehicle_raw_type = "" # Raw War Thunder ID (e.g. "f_16c_block_50")
        
        # Load Vehicle Map
        self.vehicle_map = self.load_vehicle_names()


        
        # Debug overlay
        self.show_debug = CONFIG.get('debug_mode', False)
        
        # Web Dashboard Integration
        # Create a shared data container for the web thread
        self.shared_data = {
            'players': {},
            'airfields': [],
            'pois': [],
            'map_info': {},
            'timer': {'flight_time': 0, 'spawn_time': None},
            'commands': [] # Command queue from Web UI
        }
        
        # Conditionally start Web Map server
        if CONFIG.get('enable_web_map', True):
            try:
                from web_server import start_background_server
                # Start on port 8000
                start_background_server(self.shared_data, port=8000)
                print("[WEB] Web Map server initialized")
            except Exception as e:
                print(f"[WEB] Failed to start server: {e}")
        else:
            print("[WEB] Web Map disabled via config")
        
        # toggle_debug Removed
        
    def update_network_data(self, packet):
        pid = packet.get('id')
        x = packet.get('x')
        y = packet.get('y')
        
        # 0. Ignore 'ping' type packets (from diagnostic tools)
        if packet.get('type') == 'ping':
            return
            
        if not pid: return
        
        # Translate Vehicle ID (if present)
        # We receive RAW ID (e.g. "f_14b") and translate it locally
        raw_vehicle = packet.get('vehicle', '')
        vehicle_real_name = ""
        if raw_vehicle:
             # Try direct lookup
             vehicle_real_name = self.vehicle_map.get(raw_vehicle)
             if not vehicle_real_name:
                 # Try lowercase
                 vehicle_real_name = self.vehicle_map.get(raw_vehicle.lower())
             if not vehicle_real_name:
                 # Fallback to raw
                 vehicle_real_name = raw_vehicle

        # 1. Ignore own packets (echo) to prevent "Ghost" player
        if pid in self.local_ips or pid == '127.0.0.1':
            return
            
        # 2. Ignore if callsign matches local config (Ghost player fix)
        if packet.get('sender') == CONFIG.get('callsign'):
            return
        
        # Check if this is an airfield packet
        if packet.get('type') == 'airfield':
            # Airfields are filtered by callsign/ID at top of method.
            # No additional self-filtering needed here.

            # Filter invalid or ghost coordinates (Near 0,0 is likely a glitch)
            # Use 100m threshold (Airfields shouldn't be exactly at 0,0 usually)
            if x is None or y is None or math.isnan(x) or math.isnan(y):
                return
            # Filter exact (0,0) - use normalized threshold since x,y are 0-1 range
            if abs(x) < 0.001 and abs(y) < 0.001:
                return
            # Deduplicate against local airfields at reception time
            for local_af in self.airfields:
                if abs(local_af['x'] - x) < 0.05 and abs(local_af['y'] - y) < 0.05:
                   return
                
            self.shared_airfields[pid] = {
                'x': x,
                'y': y,
                'angle': packet.get('angle', 0),  # Runway angle
                'len': packet.get('len', 0),      # Runway length
                'is_cv': packet.get('is_cv', False),
                'color': QColor(packet.get('color', '#FFFFFF')),
                'callsign': packet.get('callsign', 'Airfield'),
                'last_seen': time.time()
            }
            return
        
        # Check if this is a POI packet
        if packet.get('type') == 'point_of_interest':
            new_x = packet.get('x')
            new_y = packet.get('y')
            
            # Use sender (callsign) as key to enforce ONE POI per user
            sender_key = packet.get('sender', packet.get('callsign', pid))
            
            # Check if position changed
            position_changed = True
            if sender_key in self.shared_pois:
                old_x = self.shared_pois[sender_key]['x']
                old_y = self.shared_pois[sender_key]['y']
                if abs(old_x - new_x) < 0.001 and abs(old_y - new_y) < 0.001:
                    position_changed = False
            
            self.shared_pois[sender_key] = {
                'x': new_x,
                'y': new_y,
                'color': QColor(packet.get('color', '#FFFFFF')),
                'icon': packet.get('icon', 'point_of_interest'),
                'callsign': packet.get('callsign', 'Unknown'),
                'player_color': QColor(packet.get('player_color', '#FF0000')),
                'last_seen': time.time()
            }
            
            # Only log when position changes
            if position_changed:
                print(f"[POI RX] {sender_key}: {packet.get('icon')} at ({new_x}, {new_y})")
                print(f"[POI RX] Total POIs stored: {len(self.shared_pois)}")
            return
        
        # Check if this is a team chat packet
        if packet.get('type') == 'team_chat':
            sender = packet.get('sender', 'Unknown')
            message = packet.get('message', '')
            
            # Check against recent received messages to prevent loops
            is_net_duplicate = any(
                msg['sender'] == sender and msg['message'] == message
                for msg in self.team_chat_messages[-15:] # Check last 15
            )
            
            if not is_net_duplicate:
                chat_msg = {
                    'sender': sender,
                    'message': message,
                    'timestamp': packet.get('timestamp', time.time()),
                    'time': time.time(),  # Local receive time for fading
                    'local': False  # Mark as received from network
                }
                self.team_chat_messages.append(chat_msg)
                # Keep only last 20 messages
                if len(self.team_chat_messages) > 20:
                    self.team_chat_messages = self.team_chat_messages[-20:]
                print(f"[CHAT RX] {sender}: {message}")
            else:
                # Silently ignore duplicate
                pass
            return
        
        # Preserve existing trail
        existing_trail = self.players.get(pid, {}).get('trail', [])
        
        self.players[pid] = {
            'x': packet.get('x'),
            'y': packet.get('y'),
            'dx': packet.get('dx', 0) or 0,
            'dy': packet.get('dy', 0) or 0,
            'alt': packet.get('alt', 0) or 0,
            'spd': packet.get('spd', 0) or 0,
            'callsign': packet.get('callsign', f"Pilot {pid[-3:]}"),
            'vehicle': vehicle_real_name, # Store Translated Name
            'color': QColor(packet.get('color', '#00FFFF')), 
            'last_seen': time.time(),
            'trail': existing_trail
        }
        self.update_trail(self.players[pid])
        self.update() # Trigger redraw for new network data
    
    def update_trail(self, player_data):
        # Add current point
        if 'trail' not in player_data:
            player_data['trail'] = []
            
        current_time = time.time()
        
        # Check for teleport/respawn (large distance jump)
        if hasattr(self, 'players') and player_data['trail']:
            last_pt = player_data['trail'][-1]
            dx = player_data['x'] - last_pt['x']
            dy = player_data['y'] - last_pt['y']
            dist_sq = dx*dx + dy*dy
            # Threshold: 0.05^2 = 0.0025. Normalized coords 0-1.
            # If jump is > 5% of map size instantly, it's a respawn.
            if dist_sq > 0.0025:
                # print(f"[TRAIL] Detected respawn for {player_data.get('callsign')}, clearing trail.")
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
        
        # Prune older than configured duration (default 30s)
        duration = float(CONFIG.get('trail_duration', 30))
        player_data['trail'] = [p for p in player_data['trail'] if current_time - p['t'] < duration]
        
        return is_respawn

    def process_web_commands(self):
        """Check for commands from the Web UI (runs on timer)"""
        if not hasattr(self, 'shared_data') or 'commands' not in self.shared_data:
            return

        # Process all pending commands
        while self.shared_data['commands']:
            cmd = self.shared_data['commands'].pop(0)

            # 1. Planning Actions
            if cmd.get('type') == 'planning_update':
                self.planning_waypoints = cmd.get('waypoints', [])
                print(f"[PLAN] Updated {len(self.planning_waypoints)} waypoints")
            
            # 2. Formation Mode
            elif cmd.get('action') == 'set_formation':
                val = cmd.get('value', False)
                self.show_formation_mode = val
                print(f"[CMD] Formation Mode set to: {val}")
                self.update()
                
            # 3. Create POI
            elif cmd.get('action') == 'create_poi':
                try:
                    x = float(cmd.get('x', 0))
                    y = float(cmd.get('y', 0))
                    label = cmd.get('label', 'POI')
                    
                    # Add to local USER POIs list (Single Marker Mode - "Latest Only")
                    self.user_pois = [{
                        'x': x,
                        'y': y,
                        'label': label,
                        'icon': 'poi',
                        'color': CONFIG.get('color', '#FFCC11'),
                        'owner': CONFIG.get('callsign', 'Me')
                    }]
                    print(f"[CMD] Created Web POI '{label}' at {x:.3f}, {y:.3f}")
                    
                    # FORCE SYNC: Update shared_data immediately
                    if hasattr(self, 'shared_data'):
                        pois_list = self.shared_data.get('pois', [])
                        if not isinstance(pois_list, list): pois_list = []
                        
                        new_poi = {
                            'x': x,
                            'y': y,
                            'icon': 'poi',
                            'color': CONFIG.get('color', '#FFCC11'),
                            'owner': CONFIG.get('callsign', 'Me')
                        }
                        pois_list.append(new_poi)
                        self.shared_data['pois'] = pois_list
                        
                    print(f"[DEBUG] Local POIs: {len(self.pois)} | Shared: {len(self.shared_data.get('pois', []))}")
                    self.update()
                except Exception as e:
                    print(f"[CMD] Failed to create POI: {e}")
                    import traceback
                    traceback.print_exc()

    def check_and_record_airfield(self, x, y):
        """Check if player is on an airfield and record altitude"""
        # Only record if moving slowly (spawn/taxi)
        if self.current_speed > 80: 
            return

        if self.airfields:
             for af in self.airfields:
                 # Generate persistent key
                 af_key = f"{af['x']:.0f}_{af['y']:.0f}"
                 
                 # Optimization: specific check to avoid spamming saves if we already have it?
                 # User might want to Update it if it's wrong? 
                 # Let's save if we are confident.
                 
                 dist = math.sqrt((x - af['x'])**2 + (y - af['y'])**2)
                 if dist < 3000: # 3km radius
                     # Check if we need to update (first time or significant change?)
                     # For now, just overwrite to be safe.
                     if self.known_airfields.get(af_key) != self.current_altitude:
                         self.known_airfields[af_key] = self.current_altitude
                         af['alt'] = self.current_altitude # Update current instance
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
        """Toggle the map overlay rendering via controller (HUD remains visible)"""
        self.overlay_enabled = enabled
        self.update()
        
    # check_web_commands DEPRECATED - Merged into process_web_commands


    def trigger_calibration(self):
        """Manually trigger map calibration"""
        # Completely hide the window during calibration to avoid interference
        print("[CALIBRATE] Hiding overlay for clean screenshot...")
        self.hide()
        QApplication.processEvents()
        
        # Delay to ensure window is fully hidden
        import time
        time.sleep(0.15)
        
        print("[CALIBRATE] Manual calibration triggered (M+N pressed)...")
        
        try:
            if auto_calibrate_map_v2(self):  # Pass self to update status
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
            # Show the window again immediately
            self.show()
            self.update()
            
            # Hide status message after 5 seconds
            QTimer.singleShot(5000, self.clear_calibration_status)

    def clear_calibration_status(self):
        self.calibration_status = ""
        self.update()
    
    def poll_team_chat(self):
        """Poll War Thunder chat API and broadcast team messages"""
        try:
            response = requests.get("http://127.0.0.1:8111/gamechat?lastId=" + str(self.last_chat_id), timeout=1.0)
            if response.status_code == 200:
                messages = response.json()
                
                for msg in messages:
                    msg_id = msg.get('id', 0)
                    mode = msg.get('mode', 'All')
                    sender = msg.get('sender', 'Unknown')
                    text = msg.get('msg', '')
                    enemy = msg.get('enemy', False)
                    
                    # Update last seen ID
                    if msg_id > self.last_chat_id:
                        self.last_chat_id = msg_id
                    
                    # Only process "Team" mode messages
                    if mode == 'Team' and not enemy:
                        # 1. Deduplicate against existing messages on overlay
                        is_duplicate = any(
                            msg['sender'] == sender and msg['message'] == text
                            for msg in self.team_chat_messages[-15:]
                        )
                        
                        if not is_duplicate:
                            # 2. Add to local overlay list
                            self.team_chat_messages.append({
                                'sender': sender,
                                'message': text,
                                'timestamp': time.time(),
                                'time': time.time(),
                                'local': False  # Will be marked True when received from network
                            })
                            if len(self.team_chat_messages) > 20:
                                self.team_chat_messages = self.team_chat_messages[-20:]
                                
                            # 3. Broadcast all team messages (deduplication prevents loops)
                            packet = {
                                'type': 'team_chat',
                                'sender': sender,
                                'message': text,
                                'timestamp': time.time()
                            }
                            try:
                                self.broadcast_packet(packet)
                                print(f"[CHAT TX] {sender}: {text}")
                            except:
                                pass
        except Exception as e:
            pass

    def set_marker_hidden(self):
        self.show_marker = False
        self.update()

    def check_web_commands(self):
        """Check for commands from the Web UI"""
        if hasattr(self, 'shared_data') and 'commands' in self.shared_data and self.shared_data['commands']:
            # Process all pending commands
            while self.shared_data['commands']:
                cmd = self.shared_data['commands'].pop(0)
                
                if cmd.get('action') == 'set_formation':
                    val = cmd.get('value', False)
                    self.show_formation_mode = val
                    print(f"[CMD] Formation Mode set to: {val}")
                    self.update()
                    
                elif cmd.get('type') == 'planning_update':
                    self.planning_waypoints = cmd.get('waypoints', [])
                    print(f"[PLAN] Updated {len(self.planning_waypoints)} waypoints from Web UI")
                    self.update()

    def get_reference_grid_data(self):
        try:
            # Use 127.0.0.1 to avoid localhost resolution issues on Windows
            info_resp = requests.get("http://127.0.0.1:8111/map_info.json", timeout=0.15)
            if info_resp.status_code != 200:
                if DEBUG_MODE:
                    print(f"Sync Failed: HTTP {info_resp.status_code}")
                return None
            map_info = info_resp.json()
            
            map_min = map_info.get('map_min')
            map_max = map_info.get('map_max')
            grid_size = map_info.get('grid_size')
            grid_zero = map_info.get('grid_zero')
            
            if not map_min or not map_max or not grid_size or not grid_zero:
                if DEBUG_MODE:
                    print(f"Sync Failed: Missing required fields in {map_info}")
                return None
            
            return {
                'map_min': map_min,
                'map_max': map_max,
                'grid_size': grid_size,
                'grid_steps': map_info.get('grid_steps'), # Capture grid steps
                'grid_zero': grid_zero
            }
        except Exception as e:
            if DEBUG_MODE:
                print(f"Sync Exception: {e}")
            return None

    def refresh_map_bounds(self):
        """Fetch latest map bounds from API to handle tactical zoom changes"""
        ref_data = self.get_reference_grid_data()
        if ref_data:
            self.map_min = ref_data['map_min']
            self.map_max = ref_data['map_max']
            self.grid_steps = ref_data.get('grid_steps') # Store grid steps
            self.grid_zero = ref_data.get('grid_zero')   # Store grid zero
            self.grid_size = ref_data.get('grid_size')   # Store grid size
            self.map_bounds = ref_data # Sync for paintEvent
            # print(f"[DEBUG] Map Bounds Refreshed: {self.map_min} to {self.map_max}")
        return ref_data

    def on_telemetry_data(self, fetched):
        """Process pre-fetched telemetry data (called from background thread signal)"""
        try:
            data = fetched.get('map_data')
            if data is None:
                return
                
            was_disconnected = self.status_text.startswith("Init") or "Error" in self.status_text or "Searching" in self.status_text
            if was_disconnected:
                 self.status_text = "8111: OK"
                 self.status_color = Qt.GlobalColor.green
                 print("[STATUS] Connected to War Thunder API (8111)")
            
            # Periodically refresh map bounds (handle tactical zoom)
            current_time = time.time()
            
            # Update JDAM state
            self.bomb_tracker.update()
            
            # Cleanup Shared Data (POIs/Players)
            expired_pids = [pid for pid, poi in self.shared_pois.items() if (current_time - poi.get('last_seen', 0) > 20)]
            for pid in expired_pids: del self.shared_pois[pid]
            
            inactive_players = [pid for pid, p in self.players.items() if pid != '_local' and (current_time - p.get('last_seen', 0) > 30)]
            for pid in inactive_players: del self.players[pid]
            
            last_map_sync = getattr(self, 'last_map_sync_time', 0)
            if self.map_min is None or (current_time - last_map_sync) > 8.0:
                # Process map_info from background fetch
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

            # Auto-broadcast airfields periodically (every 30s)
            last_af_broadcast = getattr(self, 'last_af_broadcast_time', 0)
            if self.airfields and (current_time - last_af_broadcast > 30.0):
                self.broadcast_airfields()
                self.last_af_broadcast_time = current_time
            
            # Process state data (altitude, speed) - already fetched by thread
            state_data = fetched.get('state_data')
            if state_data:
                self.current_altitude = state_data.get('H, m', 0)
                self.current_speed = state_data.get('TAS, km/h', 0)
            
            # Process indicator data (vehicle type, pitch) - already fetched by thread
            ind_data = fetched.get('indicator_data')
            if ind_data:
                v_type = ind_data.get('type', '')
                self.current_pitch = ind_data.get('aviahorizon_pitch', 0.0)
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

            # Merge Shared Airfields (from network)
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
                        dist = math.sqrt((existing_af['x'] - sh_af['x'])**2 + (existing_af['y'] - sh_af['y'])**2)
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
                     self.shared_data['players']['_local'] = {
                         'x': self.player_x,
                         'y': self.player_y,
                         'spd': self.current_speed,
                         'alt': self.current_altitude,
                         'vehicle': self.current_vehicle_real_name,
                         'callsign': CONFIG.get('callsign', 'Me'),
                         'color': CONFIG.get('color', '#FFCC11')
                     }
                
                all_airfields = list(self.airfields)
                self.shared_data['airfields'] = all_airfields
                
                pois_list = []
                for poi in getattr(self, 'user_pois', []):
                    pois_list.append({
                        'x': poi['x'],
                        'y': poi['y'],
                        'icon': poi.get('icon', 'poi'),
                        'color': poi.get('color', '#FFCC11'),
                        'owner': poi.get('owner', 'Me')
                    })
                for poi in self.pois:
                    pois_list.append({
                        'x': poi['x'],
                        'y': poi['y'],
                        'icon': poi.get('icon', ''),
                        'color': CONFIG.get('color', '#FFCC11'),
                        'owner': CONFIG.get('callsign', 'Me')
                    })
                for pid, poi in self.shared_pois.items():
                    pois_list.append({
                        'x': poi['x'],
                        'y': poi['y'],
                        'icon': poi.get('icon', ''),
                        'color': poi.get('player_color', QColor(255, 255, 255)),
                        'owner': poi.get('callsign', 'Unknown')
                    })
                self.shared_data['pois'] = pois_list
                
                if self.show_debug:
                    print(f"[DEBUG-AF] Total: {len(self.airfields)}")
                    for i, af in enumerate(self.airfields):
                        print(f"  [{i}] ID={af.get('id')} X={af['x']:.3f} Y={af['y']:.3f} Ang={af.get('angle',0):.1f}")
                        
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

        except Exception as e:
            # Non-fatal: just skip this tick
            pass
        
        
        # --- ALWAYS Sync Players/POIs (regardless of API status) ---
        # This ensures network players are visible even if local game API is down
        if hasattr(self, 'shared_data'):
            self.shared_data['players'] = self.players.copy()
            
            # POIs (from network) - always sync
            pois_list = []
            
            # 1. User POIs (Web Markers) - "Less Priority" (Draw First / Background)
            for poi in getattr(self, 'user_pois', []):
                pois_list.append({
                    'x': poi['x'],
                    'y': poi['y'],
                    'icon': poi.get('icon', 'poi'),
                    'color': poi.get('color', '#FFCC11'),
                    'owner': poi.get('owner', 'Me')
                })

            # 2. Game POIs (8111 API) - "Higher Priority" (Draw Top)
            for poi in getattr(self, 'pois', []):
                pois_list.append({
                    'x': poi['x'],
                    'y': poi['y'],
                    'icon': poi.get('icon', ''),
                    'color': CONFIG.get('color', '#FFCC11'),
                    'owner': CONFIG.get('callsign', 'Me')
                })
            for pid, poi in self.shared_pois.items():
                pois_list.append({
                    'x': poi['x'],
                    'y': poi['y'],
                    'icon': poi.get('icon', ''),
                    'color': poi.get('player_color', QColor(255, 255, 255)),
                    'owner': poi.get('callsign', 'Unknown')
                })
            self.shared_data['pois'] = pois_list
            
            self.shared_data['timer'] = {
                'flight_time': self.flight_time,
                'spawn_time': self.spawn_time
            }
        
        self.update()

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
        
        # Reset and Extract bombing/defending objectives and ground units for NATO symbology
        self.map_objectives = []
        self.map_ground_units = []
        for obj in data:
            otype = obj.get('type')
            if otype in ['bombing_point', 'defending_point']:
                self.map_objectives.append({
                    'x': obj.get('x'),
                    'y': obj.get('y'),
                    'type': otype,
                    'color': obj.get('color')
                })
            elif otype == 'capture_zone':
                self.map_objectives.append({
                    'x': obj.get('x'),
                    'y': obj.get('y'),
                    'type': otype,
                    'color': obj.get('color'),
                    'blink': obj.get('blink', 0)
                })
            elif otype in ['ground_unit', 'ground_model', 'transport', 'armoured', 'tank', 'artillery']:
                self.map_ground_units.append({
                    'x': obj.get('x'),
                    'y': obj.get('y'),
                    'icon': obj.get('icon'),
                    'color': obj.get('color')
                })

        # Detect airfields
        self.airfields = []
        for obj in data:
            if obj.get('type') == 'airfield':
                # Airfields have sx, sy, ex, ey coordinates
                sx = obj.get('sx')
                sy = obj.get('sy')
                ex = obj.get('ex')
                ey = obj.get('ey')
                if sx is not None and sy is not None and ex is not None and ey is not None:
                    # DEBUG: Print all detected airfields to check for oddities
                    # print(f"DEBUG: AF Detect sx={sx:.1f} sy={sy:.1f} ex={ex:.1f} ey={ey:.1f}")
                    # Calculate center
                    center_x = (sx + ex) / 2
                    center_y = (sy + ey) / 2
                    # Calculate runway angle (direction from start to end)
                    runway_angle = math.degrees(math.atan2(ey - sy, ex - sx))
                    # Calculate normalized length
                    runway_len = math.sqrt((ex - sx)**2 + (ey - sy)**2)
                    
                    # Filter ghost airfields near 0,0 or NaN
                    if math.isnan(center_x) or math.isnan(center_y):
                        continue

                    # Generate persistent key for this airfield
                    af_key = f"{center_x:.0f}_{center_y:.0f}"
                    known_alt = self.known_airfields.get(af_key)
                    
                    # Deduplicate against already detected airfields in this frame
                    is_duplicate_frame = False
                    for existing in self.airfields:
                        if abs(existing['x'] - center_x) < 0.05 and abs(existing['y'] - center_y) < 0.05:
                             # Check if better quality? (longer?)
                             # If existing is tiny and this is long, replace?
                             if existing.get('len', 0) < 0.001 and runway_len > 0.001:
                                 self.airfields.remove(existing)
                                 is_duplicate_frame = False # Allow adding this one
                             else:
                                 is_duplicate_frame = True
                             break
                    if is_duplicate_frame:
                         continue
                         
                    self.airfields.append({
                        'x': center_x,
                        'y': center_y,
                        'angle': runway_angle,
                        'len': runway_len, # Store Normalized Length
                        'color': QColor(obj.get('color', '#FFFFFF')),
                        'alt': known_alt, 
                        'id': len(self.airfields) + 1 
                    })
        
        # Only print detection once when airfields are first detected
        if self.airfields and not hasattr(self, '_airfields_detected_logged'):
            print(f"[DETECT] Found {len(self.airfields)} airfield(s) from War Thunder API")
            self._airfields_detected_logged = True
        
        # Detect POIs (points of interest)
        self.pois = []
        for obj in data:
            if obj.get('type') == 'point_of_interest':
                x = obj.get('x')
                y = obj.get('y')
                if x is not None and y is not None:
                    self.pois.append({
                        'x': x,
                        'y': y,
                        'color': QColor(obj.get('color', '#FFFFFF')),
                        'icon': obj.get('icon', 'point_of_interest'),
                        'owner': obj.get('owner')
                    })
        
        # Only print detection once when POIs are first detected
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
                
                # Start spawn timer if this is the first time seeing the player
                if self.spawn_time is None:
                    self.spawn_time = time.time()
                    self.flight_time = 0
                    print("[STATUS] Player spawned - Timer started")
                    
                    # 1. Check Airfield on Initial Spawn
                    self.check_and_record_airfield(x, y)
                
                # Update last seen time for grace period check
                self.last_player_seen_time = time.time()
                
                # Preserve existing trail from persistent storage
                existing_trail = getattr(self, 'saved_local_trail', [])
                
                self.players['_local'] = {
                    'x': x, 'y': y, 
                    'dx': dx, 'dy': dy,
                    'alt': self.current_altitude,  # Use altitude from /state endpoint
                    'spd': self.current_speed,
                    'callsign': CONFIG.get('callsign', 'Me'),
                    'color': QColor(CONFIG.get('color', '#FF0000')),
                    'trail': existing_trail
                }
                
                # Update trail (appends to list) and check for respawn
                is_respawn = self.update_trail(self.players['_local'])
                # Update persistent storage reference (in case list object changed)
                self.saved_local_trail = self.players['_local']['trail']
                
                # Check Airfield Record Triggers
                # 1. New Spawn (Timer Start) - Handled above
                # 2. Respawn (Teleport)
                # 3. Low Speed Check (Taxiing)
                if is_respawn or self.current_speed < 80:
                    self.check_and_record_airfield(x, y)
                
                found_player = True
                
                # Broadcast airfields periodically (every 30s) instead of just once
                # This ensures they don't expire for other players (who timeout after 120s)
                current_time = time.time()
                last_broadcast = getattr(self, 'last_af_broadcast', 0)
                if self.airfields and (current_time - last_broadcast > 30):
                    self.broadcast_airfields()
                    self.last_af_broadcast = current_time
                 
                break
        
        # Prune local trail even if player not visible (to expire old points)
        if hasattr(self, 'saved_local_trail'):
            current_time = time.time()
            duration = float(CONFIG.get('trail_duration', 30))
            self.saved_local_trail = [p for p in self.saved_local_trail if current_time - p['t'] < duration]

        if not found_player:
            if '_local' in self.players:
                del self.players['_local']
            
            # Update last seen time if we just lost the player?
            # actually last_player_seen_time is updated ONLY when found.
            
            # Reset spawn time if player is lost (dead/respawn screen) longer than grace period
            # Grace period handles map blinking or short 8111 dropouts
            grace_period = 15.0 
            last_seen = getattr(self, 'last_player_seen_time', 0)
            
            if self.spawn_time is not None:
                if (time.time() - last_seen) > grace_period:
                    self.spawn_time = None
                    self.flight_time = 0
                    print("[STATUS] Player lost > 15s - Timer reset")
                else:
                    # Within grace period, keep timer alive
                    pass

            # Reset broadcast flag when player is removed (died/left match)
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
                'alt': p.get('alt', 0),
                'spd': p.get('spd', 0),
                'vehicle': self.current_vehicle_raw_type, # Broadcast RAW ID
                'callsign': CONFIG.get('callsign', 'Pilot'),
                'color': CONFIG.get('color', '#FF0000')
            }
            self.broadcast_packet(packet)
        
        # Broadcast POIs periodically (every 3s)
        current_time = time.time()
        last_poi_broadcast = getattr(self, 'last_poi_broadcast', 0)
        if '_local' in self.players and (self.pois or getattr(self, 'user_pois', [])) and (current_time - last_poi_broadcast > 3.0):
            self.broadcast_pois()
            self.last_poi_broadcast = current_time
        
        # NOTE: Web sync now happens at correct location (after map_obj processing), not here.
        
        # Prune old network players (> 5s timeout)
        now = time.time()
        to_remove = []
        for pid, p in self.players.items():
            if pid == '_local': continue
            if 'last_seen' in p and (now - p['last_seen'] > 5.0):
                to_remove.append(pid)
        for pid in to_remove:
            del self.players[pid]
    
    def broadcast_airfields(self):
        """Broadcast all detected airfields to connected players"""
        if not self.airfields:
            print("[BROADCAST] No airfields detected to broadcast")
            return
            
        print(f"[BROADCAST] Broadcasting {len(self.airfields)} airfield(s)...")
        
        for idx, airfield in enumerate(self.airfields):
            # Use Coordinate-based ID for stability (Index is unstable if API order changes)
            # Round to 2 decimals to tolerate micro-jitter
            stable_suffix = f"{airfield['x']:.2f}_{airfield['y']:.2f}"
            packet_id = f"{CONFIG.get('callsign', 'Pilot')}_af_{stable_suffix}"
            
            # Determine label
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
                'is_cv': airfield.get('is_cv', False), # Send CV flag
                'color': airfield['color'].name(),
                'label': f"{label_prefix}{idx + 1}"
            }
            print(f"[BROADCAST]   [{idx+1}] ID={packet_id}, Pos=({airfield['x']:.3f}, {airfield['y']:.3f})")
            self.broadcast_packet(packet)
        
        self.airfields_broadcasted = True

    def broadcast_connection_test(self):
        """Send a one-time chat message to verify connectivity"""
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
        """Broadcast all detected POIs to connected players"""
        # Combine lists for broadcasting
        # Game POIs + User POIs
        all_pois = list(self.pois) + list(getattr(self, 'user_pois', []))
        
        if not all_pois:
            # print("[BROADCAST] No POIs detected to broadcast") # Too noisy
            return
            
        print(f"[BROADCAST] Broadcasting {len(all_pois)} POI(s)...")
        
        for idx, poi in enumerate(all_pois):
            # Use stable ID based on coordinates to differentiate (idx is unstable if list changes)
            stable_suffix = f"{poi['x']:.3f}_{poi['y']:.3f}"
            packet_id = f"{CONFIG.get('callsign', 'Pilot')}_poi_{stable_suffix}"
            
            packet = {
                'id': packet_id,
                'type': 'point_of_interest', # Receivers look for this type
                'sender': CONFIG.get('callsign', 'Pilot'),
                'x': poi['x'],
                'y': poi['y'],
                'color': poi['color'].name() if isinstance(poi.get('color'), QColor) else poi.get('color', '#FFCC11'),
                'icon': poi.get('icon', 'poi'),
                'callsign': CONFIG.get('callsign', 'Me'), # Display Name
                'player_color': CONFIG.get('color', '#FFCC11')
            }
            # print(f"[BROADCAST]   POI {packet_id} at ({poi['x']:.3f}, {poi['y']:.3f})")
            self.broadcast_packet(packet)
        
        self.pois_broadcasted = True

    def broadcast_packet(self, packet):
        """Broadcasts a packet across all bound interfaces"""
        try:
            msg = json.dumps(packet).encode('utf-8')
            
            # Send to Global Broadcast + Configured Broadcast on ALL sockets
            targets = set()
            targets.add(('255.255.255.255', UDP_PORT))
            if self.broadcast_ip and self.broadcast_ip != '255.255.255.255':
                targets.add((self.broadcast_ip, UDP_PORT))
                
            for sock_info in self.sockets:
                sock = sock_info['sock']
                for target in targets:
                    try:
                        if DEBUG_MODE:
                            # Only print once in a while or just once per packet
                            pass 
                        sock.sendto(msg, target)
                    except Exception as e:
                        pass
            
        except Exception as e:
            print(f"[NET] Broadcast Error: {e}")

    def draw_compass_rose(self, painter, x, y, radius, heading_rad, others=None, local_player=None):
        if others is None:
            others = []
        
        # Clip drawing to the Compass Circle to contain Waypoint Lines
        painter.save()
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(x, y), radius, radius)
        painter.setClipPath(clip_path)

        heading_deg = math.degrees(heading_rad)
        
        # Draw Planning Lines (Bottom Layer)
        if self.planning_waypoints and local_player and self.map_min and self.map_max:
            p_x = local_player.get('x', 0)
            p_y = local_player.get('y', 0)
            
            # Map Dimensions for Normalized -> Meters
            m_min = self.map_min
            m_max = self.map_max
            
            world_w = m_max[0] - m_min[0]
            world_h = m_max[1] - m_min[1]
            
            # Display Scale: Radius = 50km (50,000m)
            disp_range_m = 50000 
            scale = radius / disp_range_m
            
            painter.setPen(QPen(QColor('#00FFFF'), 2)) # Cyan Lines
            
            pts_screen = []
            
            # Convert all WPs to Screen Relative
            for wp in self.planning_waypoints:
                dx_norm = wp['x'] - p_x
                dy_norm = wp['y'] - p_y
                
                dx_m = dx_norm * world_w
                dy_m = dy_norm * world_h
                
                # Use same formula as player positioning (line 1553)
                # bearing from atan2(dy, dx), then: bearing_deg - heading_deg - 90
                bearing_rad = math.atan2(dy_m, dx_m)
                bearing_deg = math.degrees(bearing_rad)
                screen_angle_deg = bearing_deg - heading_deg - 90
                screen_angle = math.radians(screen_angle_deg)
                
                dist_m = math.hypot(dx_m, dy_m)
                r_px = dist_m * scale
                
                sx = x + math.cos(screen_angle) * r_px
                sy = y + math.sin(screen_angle) * r_px
                
                pts_screen.append(QPointF(sx, sy))
            
            # Draw Lines
            if len(pts_screen) > 1:
                path = QPainterPath()
                path.moveTo(pts_screen[0])
                for i in range(1, len(pts_screen)):
                    path.lineTo(pts_screen[i])
                painter.drawPath(path)
                
            # Draw Dots
            painter.setBrush(QColor('#00FFFF'))
            painter.setPen(Qt.PenStyle.NoPen)
            for pt in pts_screen:
                painter.drawEllipse(pt, 3, 3)
                
        painter.restore() # End Clipping

            
        heading_deg = math.degrees(heading_rad)
        
        # PRE-CALCULATE TICKS
        # We need to iterate twice (Black pass, White pass). 
        # So pre-calc geometry to avoid duplication.
        ticks = []
        for i in range(0, 360, 15):
             # Angle formula (Heading Up)
             # screen_angle_deg = (i - 90) - heading_deg - 90 (?)
             # Wait, logic from previous step:
             # Ticks: Target = i - 90 (North=-90).
             # Compass Rotation = -Heading - 90.
             # Result = (i - 90) - heading_deg - 90.
             # Correct.
             
             screen_angle_deg = (i - 90) - heading_deg - 90
             rad = math.radians(screen_angle_deg)
             
             is_cardinal = (i % 90 == 0)
             is_inter = (i % 45 == 0)
             
             if is_cardinal:
                 tick_len = 10
                 tick_width = 3.0
                 outline_inc = 2.5 # Bold for Cardinals
                 color = QColor(255, 255, 255, 255)
                 label_text = ""
                 if i == 0: label_text = "N"
                 elif i == 90: label_text = "E"
                 elif i == 180: label_text = "S"
                 elif i == 270: label_text = "W"
                 
             elif is_inter:
                 tick_len = 8
                 tick_width = 2.5
                 outline_inc = 2.5
                 color = QColor(255, 255, 255, 230)
                 label_text = ""
                 if i == 45: label_text = "NE"
                 elif i == 135: label_text = "SE"
                 elif i == 225: label_text = "SW"
                 elif i == 315: label_text = "NW"
                 
             else:
                 tick_len = 5
                 tick_width = 1.5
                 outline_inc = 1.5
                 color = QColor(255, 255, 255, 150)
                 label_text = ""
                 
             # Geometry for Radial Line (Crossing the ring)
             p1_x = x + math.cos(rad) * (radius - tick_len)
             p1_y = y + math.sin(rad) * (radius - tick_len)
             p2_x = x + math.cos(rad) * (radius + tick_len)
             p2_y = y + math.sin(rad) * (radius + tick_len)
             
             ticks.append({
                 'p1': QPointF(p1_x, p1_y),
                 'p2': QPointF(p2_x, p2_y),
                 'width': tick_width,
                 'outline_w': tick_width + outline_inc,
                 'color': color,
                 'label': label_text,
                 'rad': rad
             })
             
        # Add POI Ticks (Merged into seamless rendering)
        for item in others:
            if item.get('type') == 'poi':
                bearing = item.get('bearing', 0)
                color = item.get('color', QColor(255, 255, 0)) # Default Yellow
                
                # Turn bearing into screen angle
                bearing_deg = math.degrees(bearing)
                screen_angle_deg = bearing_deg - heading_deg - 90
                rad = math.radians(screen_angle_deg)
                
                # Cardinal Style
                tick_len = 10
                tick_width = 3.0
                outline_inc = 2.5
                
                p1_x = x + math.cos(rad) * (radius - tick_len)
                p1_y = y + math.sin(rad) * (radius - tick_len)
                p2_x = x + math.cos(rad) * (radius + tick_len)
                p2_y = y + math.sin(rad) * (radius + tick_len)
                
                ticks.append({
                     'p1': QPointF(p1_x, p1_y),
                     'p2': QPointF(p2_x, p2_y),
                     'width': tick_width,
                     'outline_w': tick_width + outline_inc,
                     'color': color,
                     'label': "", # No label for POI tick itself (maybe owner name elsewhere?)
                     'rad': rad
                 })

        # PASS 1: BLACK OUTLINE (Ring + Ticks)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        
        # Ring Outline
        painter.setPen(QPen(QColor(0, 0, 0, 255), 4.5))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        
        # Ticks Outline
        for t in ticks:
            pen = QPen(QColor(0,0,0, 255), t['outline_w'])
            pen.setCapStyle(Qt.PenCapStyle.RoundCap) # Round caps for outline
            painter.setPen(pen)
            painter.drawLine(t['p1'], t['p2'])
            
        # PASS 2: WHITE FILL (Ring + Ticks)
        
        # Ring Fill
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2.5))
        painter.drawEllipse(QPointF(x, y), radius, radius)
        
        # Ticks Fill
        for t in ticks:
            pen = QPen(t['color'], t['width'])
            pen.setCapStyle(Qt.PenCapStyle.FlatCap) # Butt/Flat caps for inner
            painter.setPen(pen)
            painter.drawLine(t['p1'], t['p2'])

        # LABELS (Drawn on top)
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        
        for t in ticks:
             if t['label']:
                 r_text = radius - 25
                 tx = x + math.cos(t['rad']) * r_text
                 ty = y + math.sin(t['rad']) * r_text
                 
                 is_card = (len(t['label']) == 1)
                 font_size = 12 if is_card else 10
                 painter.setFont(QFont("Consolas", font_size, QFont.Weight.Bold))
                 fm = painter.fontMetrics()
                 tw = fm.horizontalAdvance(t['label'])
                 th = fm.height()
                 
                 # Outline Text
                 painter.setPen(QPen(QColor(0,0,0), 3))
                 painter.drawText(int(tx - tw/2), int(ty + th/4), t['label'])
                 
                # Fill Text
                 painter.setPen(QColor(255,255,255))
                 painter.drawText(int(tx - tw/2), int(ty + th/4), t['label'])
                 

        # Draw Others (Players) - Separate Pass for Triangles (On Top)
        # POIs are now handled as Ticks above.
        
        for item in others:
            if item.get('type') == 'poi':
                continue # Already drawn as tick
                
            # Players (Triangles)
            bearing = item.get('bearing', 0)
            color = item.get('color', QColor(255, 255, 255))
            label_text = item.get('label', '') 
            
            # Angle on screen
            bearing_deg = math.degrees(bearing)
            screen_angle_deg = bearing_deg - heading_deg - 90
            item_rad = math.radians(screen_angle_deg)
            
            ix = x + math.cos(item_rad) * radius
            iy = y + math.sin(item_rad) * radius
            
            painter.save()
            painter.translate(ix, iy)
            # Rotate to point INWARD (matching HDG marker style)
            # Shape points Right (0 deg).
            # We want it pointing towards center.
            # At Top (-90), we want Down (90). Diff = 180.
            # At Right (0), we want Left (180). Diff = 180.
            painter.rotate(screen_angle_deg + 180) 
            
            # Triangle
            painter.setPen(QPen(QColor(0,0,0), 1))
            painter.setBrush(QBrush(color))
            path = QPainterPath()
            path.moveTo(0, -6)
            path.lineTo(0, 6)
            path.lineTo(14, 0) 
            path.closeSubpath()
            painter.drawPath(path)
                
            painter.restore()
            
            # Label
            if label_text:
                 lx = x + math.cos(item_rad) * (radius + 20)
                 ly = y + math.sin(item_rad) * (radius + 20)
                 painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                 text_w = fm.horizontalAdvance(label_text)
                 painter.setPen(QPen(QColor(0,0,0), 2))
                 painter.drawText(int(lx - text_w/2), int(ly), label_text) 
                 painter.setPen(QColor(255,255,255))
                 painter.drawText(int(lx - text_w/2), int(ly), label_text)

        # Draw Fixed Heading Marker (Numeric Text + Triangle) at Top
        
        # 1. Numeric Text "HDG"
        heading_val = int((heading_deg + 90) % 360)
        heading_str = f"{heading_val:03d}"
        
        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        hw = fm.horizontalAdvance(heading_str)
        
        text_y = y - radius - 25 
        # Outline
        painter.setPen(QPen(QColor(0,0,0), 3))
        painter.drawText(int(x - hw/2), int(text_y), heading_str)
        # Fill
        painter.setPen(QColor(255,255,255)) 
        painter.drawText(int(x - hw/2), int(text_y), heading_str)
        
        # 2. Fixed Triangle at Top
        tip_x = x
        tip_y = y - radius - 5
        base_y = tip_y - 12
        
        path = QPainterPath()
        path.moveTo(tip_x, tip_y)
        path.lineTo(tip_x - 6, base_y)
        path.lineTo(tip_x + 6, base_y)
        path.closeSubpath()
        
        painter.setPen(QPen(QColor(0,0,0), 1))
        # Use configured color
        config_color = QColor(CONFIG.get('color', '#FFFF00'))

        painter.setPen(QPen(QColor(0,0,0), 1))
        painter.setBrush(config_color)
        painter.drawPath(path)
        
        # 3. Center Player Arrow (Fixed Up)
        # config_color already defined above
        painter.setBrush(QBrush(config_color)) 
        scale = 1.5
        
        path = QPainterPath()
        path.moveTo(x, y - 10 * scale)
        path.lineTo(x - 6 * scale, y + 8 * scale)
        path.lineTo(x, y + 4 * scale) 
        path.lineTo(x + 6 * scale, y + 8 * scale)
        path.closeSubpath()
        
        painter.setPen(QPen(QColor(0,0,0), 2))
        painter.drawPath(path)
        
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def paintEvent(self, event):
        # Poll web commands continuously (even if game is off)
        # self.check_web_commands() # DEPRECATED: Handled by process_web_commands timer

        # Always visible (Persistent Overlay)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- TIMER DISPLAY (Top Right - Always Visible) ---
        
        # Calculate flight time
        if self.spawn_time is not None:
            self.flight_time = time.time() - self.spawn_time
            
        screen_width = self.width()
        right_margin = 2  # Consistent margin for right-aligned elements
        top_margin = 13  # Moved 1px down
        line_height = 15
        
        # Calculate marker scale based on map resolution (baseline: 1920x1080)
        self.marker_scale = min(MAP_WIDTH / self.baseline_width, MAP_HEIGHT / self.baseline_height)
        
        # Format time as T+HH:MM:SS (no milliseconds)
        total_seconds = self.flight_time
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        time_str = f"T+{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # Calculate time until next mark (T-)
        interval = CONFIG.get('timer_interval', 15)
        next_mark = ((minutes // interval) + 1) * interval
        if next_mark >= 60:
             # This logic handles within-hour looping. 
             # If next_mark is 60 (e.g. at 45m with 15m interval), it targets top of hour.
             next_mark = 0
            
        # Total seconds from top of hour to now
        current_seconds_in_hour = minutes * 60 + seconds
        target_seconds_in_hour = next_mark * 60
        
        # Handle wrap around (e.g. 58m -> 00m)
        if target_seconds_in_hour <= current_seconds_in_hour:
             target_seconds_in_hour += 3600
             
        time_to_next = target_seconds_in_hour - current_seconds_in_hour
        
        countdown_hours = int(time_to_next // 3600)
        countdown_minutes = int((time_to_next % 3600) // 60)
        countdown_seconds = int(time_to_next % 60)
        countdown_str = f"T-{countdown_hours:02d}:{countdown_minutes:02d}:{countdown_seconds:02d}"
        
        # Calculate text width for right alignment (use monospace font for consistency)
        font_timer = QFont('Courier New', 11, QFont.Weight.Bold)  # Size 9 to match Arial visual size
        metrics_timer = QFontMetrics(font_timer)
        
        text_width_plus = metrics_timer.horizontalAdvance(time_str)
        text_width_minus = metrics_timer.horizontalAdvance(countdown_str)
        
        # Use the wider of the two for consistent alignment
        max_width = max(text_width_plus, text_width_minus)
        
        # Position both timers at the same right edge
        timer_x = screen_width - max_width - right_margin
        
        # Draw T+ timer
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setFont(font_timer)
        painter.drawText(timer_x, top_margin + 1, time_str)  # Moved 1px down
        
        # Draw T- countdown below
        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.setFont(font_timer)
        painter.drawText(timer_x, top_margin + line_height + 1, countdown_str)  # Moved 1px down

        # Mode Check: HUD vs Full Map
        if not self.show_marker:
            # HUD Mode: Only Compass Top Right
            if getattr(self, 'show_compass', True) and '_local' in self.players:
                p = self.players['_local']
                dx = p.get('dx', 0)
                dy = p.get('dy', 0)
                heading_rad = 0
                if abs(dx) > 0.001 or abs(dy) > 0.001:
                    heading_rad = math.atan2(dy, dx)
                
                # Calculate others (Players & POIs)
                others = []
                
                # Other Players
                for pid, other_p in self.players.items():
                    if pid == '_local': continue
                    
                    dx = other_p.get('x', 0) - p.get('x', 0)
                    dy = other_p.get('y', 0) - p.get('y', 0)
                    
                    if abs(dx) > 0.0001 or abs(dy) > 0.0001:
                        bearing = math.atan2(dy, dx)
                        others.append({
                            'type': 'player',
                            'bearing': bearing,
                            'color': other_p.get('color', QColor(255, 255, 255)),
                            'label': '' # Can add callsign if needed, but might clutter
                        })
                        
                # POIs (Local + Shared)
                if hasattr(self, 'pois'):
                    for poi in self.pois:
                        p_dx = poi.get('x', 0) - p.get('x', 0)
                        p_dy = poi.get('y', 0) - p.get('y', 0)
                        
                        if abs(p_dx) > 0.0001 or abs(p_dy) > 0.0001:
                             p_bearing = math.atan2(p_dy, p_dx)
                             others.append({
                                 'type': 'poi',
                                 'bearing': p_bearing,
                                 'color': Qt.GlobalColor.yellow # Local POIs yellow
                             })
                             
                if hasattr(self, 'shared_pois'):
                     for pid, poi in self.shared_pois.items():
                        p_dx = poi.get('x', 0) - p.get('x', 0)
                        p_dy = poi.get('y', 0) - p.get('y', 0)
                        
                        if abs(p_dx) > 0.0001 or abs(p_dy) > 0.0001:
                             p_bearing = math.atan2(p_dy, p_dx)
                             # Use player_color to identify owner, fall back to generic color
                             # User asked for "there colour" -> Owner Color
                             use_color = poi.get('player_color', poi.get('color', Qt.GlobalColor.yellow))
                             others.append({
                                 'type': 'poi',
                                 'bearing': p_bearing,
                                 'color': use_color
                             })

                # Top Right Position (Width - 133 - Margin)
                # Radius 102.5 (Diameter - 5px). Center Y = 150 (Up 50px).
                rx = self.width() - 133
                ry = 150
                
                # Pass local player data for relative rendering (Planning paths)
                self.draw_compass_rose(painter, rx, ry, 102.5, heading_rad, others, local_player=p)
                
                # --- HEADING & TARGET TEXT ---
                heading_deg = math.degrees(heading_rad) % 360
                
                # Determine Target
                target_bearing = None
                target_dist = None
                
                if self.planning_waypoints:
                    # Target is the first waypoint
                    wp = self.planning_waypoints[0]
                    # Calc bearing
                    # Need map dimensions to convert normalized coords to meters for angle calc?
                    # Actually angle is same in normalized if aspect ratio is 1:1.
                    # BUT map might not be 1:1. 
                    # Use pixel diff or normalized diff. Assuming 1:1 aspect for angle is okay if map is square.
                    # War Thunder maps are usually square.
                    
                    dx_t = wp['x'] - p.get('x', 0)
                    dy_t = wp['y'] - p.get('y', 0)
                    
                    if abs(dx_t) > 0.0001 or abs(dy_t) > 0.0001:
                       target_bearing = math.degrees(math.atan2(dy_t, dx_t)) % 360
                       
                       # Calc Distance (approx in km, assuming 65km map size)
                       # Better to use actual map size if known, but for HUD text approx is fine?
                       # We have self.map_bounds.
                       map_size_m = float(CONFIG.get('map_size_meters', 65000))
                       if hasattr(self, 'map_bounds') and self.map_bounds:
                            map_min = self.map_bounds.get('map_min', [0, 0])
                            map_max = self.map_bounds.get('map_max', [map_size_m, map_size_m])
                            map_size_m = max(map_max[0] - map_min[0], map_max[1] - map_min[1])
                            
                       dist_norm = math.hypot(dx_t, dy_t)
                       target_dist = (dist_norm * map_size_m) / 1000.0 # km

                # Draw Text
                painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                metrics = QFontMetrics(painter.font())
                
                text_y = ry + 125 # Below Compass
                
                # Heading (REMOVED as per user request)
                # hdg_str = f"HDG: {int(heading_deg):03d}"
                # painter.setPen(QPen(Qt.GlobalColor.white))
                # painter.drawText(rx - 40, text_y, hdg_str)
                
                # Target
                if target_bearing is not None:
                    tgt_str = f"TGT: {int(target_bearing):03d}"
                    painter.setPen(QPen(Qt.GlobalColor.cyan)) # Cyan for Target
                    painter.drawText(rx - 40, text_y + 15, tgt_str)
                    
                    # Delta (Turn indicator)
                    diff = (target_bearing - heading_deg + 180) % 360 - 180
                    # Arrow? or just L/R
                    direction = "R" if diff > 0 else "L"
                    if abs(diff) < 2: direction = ""
                    delta_str = f"{direction} {abs(int(diff))}"
                    
                    dist_str = f"{target_dist:.1f}km"
                    
                    painter.drawText(rx + 35, text_y + 15, dist_str)
                
                # Draw Formation Panel below Compass (if enabled)
                if getattr(self, 'show_formation_mode', False):
                    # Position with fixed 20px margin from right edge
                    # Table width = 340px + padding, center = width/2 = ~178
                    table_center_x = self.width() - 20 - 178
                    self.draw_formation_panel(painter, table_center_x, ry + 120, others)

            # Removed return to allow JDAM overlay to draw
            # return

        # --- Full Map Mode ---

        # Draw status & debug text (Top Left - Tighter to corner)
        painter.setPen(QPen(Qt.GlobalColor.green if self.status_text.startswith("8111: OK") else Qt.GlobalColor.red))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.drawText(2, 13, self.status_text)  # Moved 1px down
        
        # Draw calibration status if present
        if self.calibration_status:
            status_color = Qt.GlobalColor.yellow if "Calibrating" in self.calibration_status else (
                Qt.GlobalColor.green if "OK" in self.calibration_status else Qt.GlobalColor.red
            )
            painter.setPen(QPen(status_color))
            painter.drawText(2, 26, f"{self.calibration_status}")



        # Draw Player List (exclude local player) - only when M is pressed
        if self.show_marker:
            list_y = 55 # Below timers
            
            # Header
            header_text = "Active Aircraft:"
            font_header = QFont('Arial', 10, QFont.Weight.Bold)
            metrics_header = QFontMetrics(font_header)
            header_width = metrics_header.horizontalAdvance(header_text)
            
            # Use consistent right margin
            header_x = screen_width - header_width - right_margin
            
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setFont(font_header)
            painter.drawText(header_x, list_y, header_text)
            
            # Players
            y_offset = 20
            font_player = QFont('Arial', 9)
            metrics_player = QFontMetrics(font_player)
            
            # Sort: Local first, then others
            sorted_pids = sorted(self.players.keys(), key=lambda x: 0 if x == '_local' else 1)
            
            for pid in sorted_pids:
                p = self.players[pid]
                callsign = p.get('callsign', pid)
                if pid == '_local':
                    callsign = f"{callsign} (You)"
                    
                color = p.get('color', Qt.GlobalColor.white)
                
                # Calculate alignment using consistent margin
                text_width = metrics_player.horizontalAdvance(callsign)
                text_x = screen_width - text_width - right_margin
                indicator_x = text_x - 15
                
                # Draw color indicator
                painter.setBrush(QBrush(color))
                painter.setPen(QPen(color, 2))
                painter.drawEllipse(indicator_x, list_y + y_offset - 8, 8, 8)
                
                # Draw Name
                painter.setPen(QPen(QColor(255, 255, 255), 2))
                painter.setFont(font_player)
                painter.drawText(text_x, list_y + y_offset, callsign)
                
                y_offset += 20

        # (Chat rendering moved to bottom of paintEvent)
        if self.show_marker and self.map_min and self.overlay_enabled:
            
            # Iterate over all players (Draw Local FIRST so Remote appears on top)
            # print(f"DEBUG: Painting Players: {list(self.players.keys())}") # Uncomment to trace paint list

            # --- Draw Airfields ---
            if self.airfields:
                 for af in self.airfields:
                      ax = MAP_OFFSET_X + (af['x'] * MAP_WIDTH)
                      ay = MAP_OFFSET_Y + (af['y'] * MAP_HEIGHT)
                      
                      painter.save()
                      painter.translate(ax, ay)
                      painter.rotate(af['angle'])
                      
                      # Calculate dynamic width
                      # Use stored length if available, else fixed fallback
                      rect_w = 30 * self.marker_scale # Default
                      if 'len' in af and af['len'] > 0:
                          # Scale length by 1.0x (true to game scale)
                          rect_w = (af['len'] * MAP_WIDTH) * 1.0
                          # Ensure minimum visibility (15px scaled)
                          rect_w = max(rect_w, 15 * self.marker_scale)
                          
                      rect_h = 6 * self.marker_scale
                      
                      # Draw Runway
                      painter.setPen(QPen(Qt.GlobalColor.black, 1))
                      color = af.get('color', Qt.GlobalColor.white)
                      painter.setBrush(QBrush(color))
                      
                      # Centered rectangle
                      painter.drawRect(QRectF(-rect_w/2, -rect_h/2, rect_w, rect_h))
                      
                      painter.restore()
                      
                      # Label drawn in main airfield loop (line ~1960)
            
            # Sort: Local (0) first, then others (1)
            sorted_pids = sorted(self.players.keys(), key=lambda x: 0 if x == '_local' else 1)
            
            for pid in sorted_pids:
                player = self.players[pid]
                
                # --- Compass Rose section removed (HUD Only) ---

                # --- Draw Contrail ---
                if 'trail' in player and len(player['trail']) > 1:
                    trail_points = []
                    for pt in player['trail']:
                        if pt.get('x') is None or pt.get('y') is None:
                            continue
                        tx = MAP_OFFSET_X + (pt['x'] * MAP_WIDTH)
                        ty = MAP_OFFSET_Y + (pt['y'] * MAP_HEIGHT)
                        trail_points.append(QPointF(tx, ty))
                    
                    # Robust Trimming: Remove points within exclusion radius of current position
                    # to prevent trail being visible inside the hollow marker.
                    if len(trail_points) >= 2:
                        head_pt = QPointF(MAP_OFFSET_X + (player['x'] * MAP_WIDTH), 
                                          MAP_OFFSET_Y + (player['y'] * MAP_HEIGHT))
                        exclusion_radius = 8 * self.marker_scale
                        
                        trimmed_points = []
                        cut_index = -1
                        # Iterate backwards to find first point outside radius
                        for i in range(len(trail_points)-1, -1, -1):
                            pt = trail_points[i]
                            dx = pt.x() - head_pt.x()
                            dy = pt.y() - head_pt.y()
                            dist = math.hypot(dx, dy)
                            if dist > exclusion_radius:
                                cut_index = i
                                # Found first point outside. 
                                # Interpolate a start point exactly at radius edge for smoothness
                                v_x = pt.x() - head_pt.x()
                                v_y = pt.y() - head_pt.y()
                                factor = exclusion_radius / dist
                                start_x = head_pt.x() + v_x * factor
                                start_y = head_pt.y() + v_y * factor
                                
                                # Take all points up to i, and append the start point
                                trimmed_points = trail_points[:i+1]
                                trimmed_points.append(QPointF(start_x, start_y))
                                break
                        
                        if cut_index != -1:
                            trail_points = trimmed_points
                        else:
                            # All points inside radius
                            trail_points = []

                    if len(trail_points) > 1:
                        # Draw trail with some transparency (alpha 150)
                        trail_color = QColor(player['color'])
                        trail_color.setAlpha(150)
                        painter.setPen(QPen(trail_color, 2)) # 2px width
                        painter.drawPolyline(trail_points)
                
                raw_x, raw_y = player['x'], player['y']
                
                # Bounds Check: Hide players outside the map [0.0, 1.0]
                # Also handles the 0,0 glitch for out-of-bounds players
                if not (0.0 <= raw_x <= 1.0 and 0.0 <= raw_y <= 1.0):
                    continue
                
                # Check for exact 0.0, 0.0 which often means invalid data
                if abs(raw_x) < 0.001 and abs(raw_y) < 0.001:
                    continue
                
                # SIMPLIFIED MAPPING LOGIC
                x = MAP_OFFSET_X + (raw_x * MAP_WIDTH)
                y = MAP_OFFSET_Y + (raw_y * MAP_HEIGHT)
                
                # --- Draw Arrow ---
                painter.save()
                painter.translate(x, y)
                
                # Orientation
                rotation = 0.0
                dx, dy = player['dx'], player['dy']
                if abs(dx) > 0.001 or abs(dy) > 0.001:
                    rotation = math.degrees(math.atan2(dy, dx))
                
                painter.rotate(rotation)

                color = player.get('color', QColor(0, 0, 255, 200))
                painter.setPen(QPen(color, 2))
                painter.setBrush(QBrush(color))
                
                # Draw Callsign Text
                painter.setPen(QPen(Qt.GlobalColor.white))
                painter.setFont(QFont("Arial", 8))
                # Rotate text back to be upright? No, let it rotate with plane usually looks cooler/standard in sims
                # Actually, usually text stays upright. But let's keep it simple first.
                # To make text upright, we'd need to rotate inverse. 
                painter.save()
                painter.rotate(-rotation) # Counter-rotate for upright text
                painter.drawText(-20, -15, player.get('callsign', 'Unknown'))
                painter.restore()
                
                # Reset Pen for Arrow
                painter.setPen(QPen(color, 2))

                # Arrow Shape (Pointing Right) - scaled by resolution
                scale = self.marker_scale
                arrow_polygon = QPolygonF([
                    QPointF(14 * scale, 0),   # Tip
                    QPointF(-5 * scale, -7 * scale), # Back Left
                    QPointF(-5 * scale, 7 * scale)   # Back Right
                ])
                
                # Draw colored arrow outline on top (hollow)
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolygon(arrow_polygon)
                
                # Draw Speed Vector Line
                spd = player.get('spd', 0)
                if spd > 10:  # Only draw if moving
                    # Length factor: e.g. 20px for 1000 km/h -> factor 0.02
                    vector_len = spd * 0.03 * scale
                    painter.drawLine(QPointF(14 * scale, 0), QPointF(14 * scale + vector_len, 0))
                
                # Draw Altitude and Speed Text (below arrow)
                painter.save()
                painter.rotate(-rotation)  # Counter-rotate for upright text
                
                alt_m = player.get('alt', 0)
                alt_km = alt_m / 1000.0  # Convert meters to kilometers
                
                spd_kmh = player.get('spd', 0)
                
                # Check speed unit from config (boolean, default True for kts)
                is_kts = CONFIG.get('unit_is_kts', True)
                if is_kts:
                    spd_display = spd_kmh * 0.539957
                else:
                    spd_display = spd_kmh
                
                # Format: "900 4.5" (Speed Alt) - Speed first as requested
                stats_text = f"{int(spd_display)} {alt_km:.1f}"
                
                painter.setPen(QPen(Qt.GlobalColor.white))
                font_stats = QFont("Arial", 8)
                painter.setFont(font_stats)
                
                # Center text
                metrics = QFontMetrics(font_stats)
                text_width = metrics.horizontalAdvance(stats_text)
                painter.drawText(-text_width // 2, 30, stats_text)
                
                painter.restore()
                
                painter.restore()

            # --- Draw Airfields (Unified Local + Shared) ---
            if self.airfields:
                for idx, airfield in enumerate(self.airfields):
                    # Skip invalid coordinates
                    raw_x, raw_y = airfield['x'], airfield['y']
                    if raw_x is None or raw_y is None: continue
                    
                    # Filter ghost airfields near 0,0 (phantom data)
                    if abs(raw_x) < 0.01 and abs(raw_y) < 0.01:
                        continue

                    # Map to screen coordinates
                    x = MAP_OFFSET_X + (raw_x * MAP_WIDTH)
                    y = MAP_OFFSET_Y + (raw_y * MAP_HEIGHT)
                    
                    painter.save()
                    painter.translate(x, y)
                    angle = airfield.get('angle', 0)
                    painter.rotate(angle)
                    
                    # Determine Color (Orange for Shared/Blue for Local? Or just use object color)
                    # Shared airfields are appended with Orange color in update_telemetry
                    c = airfield.get('color', QColor(100, 100, 255))
                    
                    # Calculate scaled runway length
                    runway_len = 20 * self.marker_scale  # Default
                    if airfield.get('len') and airfield['len'] > 0.001:
                        # Scale based on normalized length
                        runway_len = (airfield['len'] * MAP_WIDTH) * 0.5
                        runway_len = max(runway_len, 10 * self.marker_scale)  # Minimum visibility
                    
                    # Draw Runway Line (scaled length)
                    painter.setPen(QPen(c, 6))
                    painter.drawLine(int(-runway_len/2), 0, int(runway_len/2), 0)
                    
                    # --- Draw 12km Radius Circle for Long Runways (>3000m) ---
                    # Calculate runway length in meters (approx)
                    # Assume map_size is approximately 65km (typical WT map)
                    map_size_m = float(CONFIG.get('map_size_meters', 65000))
                    runway_meters = (airfield.get('len', 0) * map_size_m)
                    
                    if runway_meters > 3000:
                        # 12km radius in pixels
                        radius_normalized = 12000 / map_size_m
                        radius_pixels = radius_normalized * MAP_WIDTH
                        
                        # Draw circle (counter-rotate to undo runway angle)
                        painter.rotate(-angle)
                        circle_pen = QPen(c, 4, Qt.PenStyle.DashLine)
                        circle_pen.setColor(QColor(c.red(), c.green(), c.blue(), 100))  # Semi-transparent
                        painter.setPen(circle_pen)
                        painter.setBrush(Qt.BrushStyle.NoBrush)
                        painter.drawEllipse(int(-radius_pixels), int(-radius_pixels), 
                                            int(radius_pixels * 2), int(radius_pixels * 2))
                        painter.rotate(angle)  # Re-rotate for label
                    
                    # Draw Label (AF1, AF2, etc)
                    # Use 'id' if available, else index
                    af_label = f"AF{airfield.get('id', idx+1)}"
                    if airfield.get('is_cv'):
                        af_label = f"CV{airfield.get('id', idx+1)}"
                        
                    painter.setPen(QPen(Qt.GlobalColor.white))
                    # Counter-rotate text to keep it upright vs screen
                    painter.rotate(-angle) 
                    
                    # Simple Text Label (No Outline)
                    painter.setPen(QPen(Qt.GlobalColor.white))
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    painter.drawText(-15, -20, af_label)
                    
                    painter.restore()

                # Only print once per map view
                # if self.show_debug and not hasattr(self, '_af_render_log'):
                #      print(f"[RENDER] Drew {len(self.airfields)} airfields")
                #      self._af_render_log = True
                
                
                # Draw Debug Map Boundary
                if self.show_debug:
                    painter.setPen(QPen(Qt.GlobalColor.green, 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(int(MAP_OFFSET_X), int(MAP_OFFSET_Y), int(MAP_WIDTH), int(MAP_HEIGHT))
                    
                    # Draw Debug Text info
                    painter.setPen(QPen(Qt.GlobalColor.green))
                    painter.setFont(QFont("Arial", 10))
                    
                    trail_info = ""
                    if '_local' in self.players:
                        t_len = len(self.players['_local'].get('trail', []))
                        trail_info = f" | Trail: {t_len}"
                        
                    painter.drawText(int(MAP_OFFSET_X), int(MAP_OFFSET_Y) - 5, 
                                   f"Map: {MAP_WIDTH}x{MAP_HEIGHT} ({MAP_OFFSET_X},{MAP_OFFSET_Y}){trail_info}")

            # --- Draw Scale Bar (Bottom Right of Map) ---
            # Use actual map dimensions if available, otherwise config default
            map_size_m = float(CONFIG.get('map_size_meters', 65000))
            
            # Check if we have map_info with actual bounds
            if hasattr(self, 'map_bounds') and self.map_bounds:
                map_min = self.map_bounds.get('map_min', [0, 0])
                map_max = self.map_bounds.get('map_max', [map_size_m, map_size_m])
                map_size_m = max(map_max[0] - map_min[0], map_max[1] - map_min[1])
            
            # Calculate grid cell size (map typically divided into 8 squares)
            grid_cells = 8
            grid_cell_m = map_size_m / grid_cells
            grid_cell_km = grid_cell_m / 1000
            
            # --- Scale Bar (Ruler Style) ---
            
            # Flush RIGHT against Map Edge
            map_right_edge = MAP_OFFSET_X + MAP_WIDTH
            
            # Determine Bar Max Range (target 10km if possible)
            max_km = 10
            if map_size_m < 12000: max_km = 5
            if map_size_m < 6000: max_km = 2
            
            # Calculate pixel ratio
            pixels_per_km = MAP_WIDTH / (map_size_m / 1000)
            
            # Calculate Bar Width
            bar_width = round(max_km * pixels_per_km)
            bar_x = int(map_right_edge - bar_width)
            bar_y = int(MAP_OFFSET_Y + MAP_HEIGHT - 35) # Ruler position
            
            # Draw Base Line (Outline)
            painter.setPen(QPen(Qt.GlobalColor.black, 4))
            painter.drawLine(bar_x, bar_y, bar_x + bar_width, bar_y)
            # Draw Base Line (White)
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(bar_x, bar_y, bar_x + bar_width, bar_y)
            
            # Draw Ticks and Labels (Right to Left)
            # 0 is at map_right_edge (bar_x + bar_width)
            
            tick_marks = [0, 1, 5, 10]
            if max_km < 10: tick_marks = [0, 1, 2, 5] if max_km >= 5 else [0, 0.5, 1, 2]
            
            painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
            fm = QFontMetrics(painter.font())
            
            # --- KM Scale ---
            for km in tick_marks:
                if km > max_km: continue
                
                px_offset = round(km * pixels_per_km)
                tick_x = (bar_x + bar_width) - px_offset
                
                # Draw Tick (No Outline, Above Line)
                painter.setPen(QPen(Qt.GlobalColor.black, 2)) # Use Black or White? Usually White on Black map?
                # User said "do not use individual outline".
                # The Bar is White with Black Outline.
                # If I draw White tick, it matches.
                # If background is light, it vanishes.
                # If background is dark (map), White is good.
                # I'll use White (thickness 2).
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawLine(tick_x, bar_y, tick_x, bar_y - 6) # Upwards (Above line)
                
                # Draw Label (Number only)
                is_whole = isinstance(km, int) or (isinstance(km, float) and km.is_integer())
                label = f"{int(km)}" if is_whole else f"{km}"
                if km == 0: label = "0"
                
                tw = fm.horizontalAdvance(label)
                # Double draw text
                painter.setPen(QPen(Qt.GlobalColor.black))
                painter.drawText(int(tick_x - tw/2 + 1), int(bar_y - 8), label) # Above tick
                painter.setPen(QPen(Qt.GlobalColor.white))
                painter.drawText(int(tick_x - tw/2), int(bar_y - 9), label)

            # "km" Label at the Right
            label = "km"
            tw = fm.horizontalAdvance(label)
            label_x = int(bar_x + bar_width + 8) 
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(label_x + 1, int(bar_y - 8), label)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(label_x, int(bar_y - 9), label)

            # --- Nautical Miles (NM) Scale ---
            # ruler at ~25px below KM
            nm_bar_y = bar_y + 25 
            
            # Extend to 10 NM fixed?
            # 10 NM = 18.52 km.
            # Convert 10 NM to pixels.
            px_10nm = round(10 * 1.852 * pixels_per_km)
            
            # NM Bar starts at "0" (Same Right point as KM) and extends Left.
            # Right point: bar_x + bar_width
            # Left point: (bar_x + bar_width) - px_10nm
            nm_bar_x_start = (bar_x + bar_width) - px_10nm
            
            # Draw Base Line (NM) - Outline + White
            painter.setPen(QPen(Qt.GlobalColor.black, 4))
            painter.drawLine(nm_bar_x_start, nm_bar_y, bar_x + bar_width, nm_bar_y)
            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(nm_bar_x_start, nm_bar_y, bar_x + bar_width, nm_bar_y)
            
            # NM Ticks: 0, 1, 2, 5, 10
            nm_ticks = [0, 1, 2, 5, 10]
            
            for nm in nm_ticks:
                # Always draw up to 10? Yes.
                px_offset = round(nm * 1.852 * pixels_per_km)
                tick_x = (bar_x + bar_width) - px_offset
                
                # Draw Tick (Upwards? Above line)
                painter.setPen(QPen(Qt.GlobalColor.white, 2))
                painter.drawLine(tick_x, nm_bar_y, tick_x, nm_bar_y - 6) 
                
                # Label (Above ticks)
                label = f"{int(nm)}"
                tw = fm.horizontalAdvance(label)
                
                painter.setPen(QPen(Qt.GlobalColor.black))
                painter.drawText(int(tick_x - tw/2 + 1), int(nm_bar_y - 8), label) # Moved Up
                painter.setPen(QPen(Qt.GlobalColor.white))
                painter.drawText(int(tick_x - tw/2), int(nm_bar_y - 9), label)

            # "NM" Label at Right (Above line)
            label = "NM"
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(label_x + 1, int(nm_bar_y - 8), label) # Moved Up
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(label_x, int(nm_bar_y - 9), label)

            # --- Special "1 Grid" Label (Above everything) ---
            grid_km = (map_size_m / 8) / 1000
            
            # Map Size Label (Below NM scale line)
            # Move further down to be clearly "outside" the map image
            
            map_label_y = nm_bar_y + 35 
            
            # Grid Size Label (Above Map Size)
            grid_label_y = map_label_y - 12
            
            # Draw Grid Size - Flush Right
            grid_nm = grid_km * 0.539957
            label = f"{grid_km:.2f} km = {grid_nm:.2f} NM"
            tw = fm.horizontalAdvance(label)
            
            painter.setFont(QFont("Arial", 7, QFont.Weight.Bold)) 
            
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(int(bar_x + bar_width - tw + 1), int(grid_label_y + 1), label)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(int(bar_x + bar_width - tw), int(grid_label_y), label)
            
            # Draw "Map: ..." 
            map_km = map_size_m / 1000
            map_nm = map_km * 0.539957
            label = f"Map: {int(map_km)}km/{int(map_nm)}NM"
            tw = fm.horizontalAdvance(label)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(int(bar_x + bar_width - tw + 1), int(map_label_y + 1), label)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(int(bar_x + bar_width - tw), int(map_label_y), label)

            # --- Draw SPAA Radius Circles (4.5km) ---
            if hasattr(self, 'map_ground_units') and self.map_ground_units:
                # Cluster SPAA units
                spaa_clusters = []
                cluster_threshold = 0.05  # Normalized distance threshold
                
                for unit in self.map_ground_units:
                    icon = (unit.get('icon') or '').lower()
                    # Check if unit is SPAA
                    if 'aa' in icon or 'spaa' in icon or 'sam' in icon:
                        unit_x, unit_y = unit.get('x', 0), unit.get('y', 0)
                        added = False
                        
                        # Try to add to existing cluster
                        for cluster in spaa_clusters:
                            dist = ((unit_x - cluster['x'])**2 + (unit_y - cluster['y'])**2)**0.5
                            if dist < cluster_threshold:
                                # Update cluster centroid
                                n = cluster['count']
                                cluster['x'] = (cluster['x'] * n + unit_x) / (n + 1)
                                cluster['y'] = (cluster['y'] * n + unit_y) / (n + 1)
                                cluster['count'] += 1
                                added = True
                                break
                        
                        if not added:
                            spaa_clusters.append({
                                'x': unit_x,
                                'y': unit_y,
                                'count': 1,
                                'color': unit.get('color', '#FF0000')
                            })
                
                # Draw 4.5km radius circle for each SPAA cluster
                for cluster in spaa_clusters:
                    # Skip if cluster is near an airfield (airfields already have 12km circle)
                    is_near_airfield = False
                    if hasattr(self, 'airfields') and self.airfields:
                        for af in self.airfields:
                            af_x, af_y = af.get('x', 0), af.get('y', 0)
                            dist = ((cluster['x'] - af_x)**2 + (cluster['y'] - af_y)**2)**0.5
                            if dist < 0.08:  # About 5km in normalized coords
                                is_near_airfield = True
                                break
                    
                    if is_near_airfield:
                        continue
                    
                    cx = MAP_OFFSET_X + (cluster['x'] * MAP_WIDTH)
                    cy = MAP_OFFSET_Y + (cluster['y'] * MAP_HEIGHT)
                    
                    # 4.5km radius in pixels
                    radius_normalized = 4500 / map_size_m
                    radius_pixels = radius_normalized * MAP_WIDTH
                    
                    # Determine color based on unit color (friendly vs hostile)
                    color_str = str(cluster.get('color', '#FF0000'))
                    is_friendly = '#043' in color_str or '#174D' in color_str or '4,63,255' in color_str
                    circle_color = QColor(126, 226, 255, 150) if is_friendly else QColor(255, 126, 126, 150)
                    
                    # Draw dashed circle
                    painter.save()
                    painter.translate(cx, cy)
                    pen = QPen(circle_color, 3, Qt.PenStyle.DashLine)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(int(-radius_pixels), int(-radius_pixels),
                                        int(radius_pixels * 2), int(radius_pixels * 2))
                    painter.restore()

            # --- Draw Local POIs ---
            if self.pois:
                for poi in self.pois:
                    raw_x, raw_y = poi['x'], poi['y']
                    x = MAP_OFFSET_X + (raw_x * MAP_WIDTH)
                    y = MAP_OFFSET_Y + (raw_y * MAP_HEIGHT)
                    
                    painter.save()
                    painter.translate(x, y)
                    
                    # Use our own config color
                    my_color = QColor(CONFIG.get('color', '#FFCC11'))
                    painter.setPen(QPen(my_color, 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    
                    radius = 15
                    arc_angle = 60
                    # Draw reticle
                    painter.drawArc(-radius, -radius, radius*2, radius*2, -30 * 16, arc_angle * 16)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 60 * 16, arc_angle * 16)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 150 * 16, arc_angle * 16)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 240 * 16, arc_angle * 16)
                    
                    # Label
                    painter.setPen(QPen(Qt.GlobalColor.white))
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    painter.drawText(-15, -20, CONFIG.get('callsign', 'Me'))
                    painter.restore()

            # --- Draw Shared POIs ---
            if self.shared_pois:
                # Cleanup expired POIs (older than 20s or owner offline)
                current_time = time.time()
                expired_pids = []

        # (SAM Logic Moved OUTSIDE the 'if self.show_marker' block)

            # --- Shared POIs Logic Continues ---
            for pid, poi in self.shared_pois.items():
                for pid, poi in self.shared_pois.items():
                    # Check direct timeout
                    if current_time - poi.get('last_seen', 0) > 20:
                        expired_pids.append(pid)
                        continue
                    
                    # Check owner connectivity
                    player = self.players.get(pid)
                    if not player or (current_time - player.get('last_seen', 0) > 30):
                        expired_pids.append(pid)

                for pid in expired_pids:
                    del self.shared_pois[pid]
                    
                for pid, poi in self.shared_pois.items():
                    raw_x, raw_y = poi['x'], poi['y']
                    
                    # Map to screen coordinates
                    x = MAP_OFFSET_X + (raw_x * MAP_WIDTH)
                    y = MAP_OFFSET_Y + (raw_y * MAP_HEIGHT)
                    
                    painter.save()
                    painter.translate(x, y)
                    
                    # Use player's color for the POI marker
                    poi_color = poi.get('player_color', QColor(255, 255, 255))
                    
                    painter.setPen(QPen(poi_color, 2))  # 2px border thickness
                    painter.setBrush(Qt.BrushStyle.NoBrush)  # Hollow
                    
                    # Draw four corner arcs (targeting reticle style)
                    radius = 15  # Radius of the circle
                    arc_angle = 60  # Degrees for each arc (60 degrees = 1/6 of circle)
                    
                    # Qt uses 1/16th degree units, and 0 degrees is at 3 o'clock position
                    # Top-right corner (starts at -30 degrees from 3 o'clock)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, -30 * 16, arc_angle * 16)
                    
                    # Bottom-right corner (starts at 60 degrees from 3 o'clock)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 60 * 16, arc_angle * 16)
                    
                    # Bottom-left corner (starts at 150 degrees from 3 o'clock)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 150 * 16, arc_angle * 16)
                    
                    # Top-left corner (starts at 240 degrees from 3 o'clock)
                    painter.drawArc(-radius, -radius, radius*2, radius*2, 240 * 16, arc_angle * 16)
                    
                    # Draw label with player's callsign
                    callsign = poi.get('callsign', 'Unknown')
                    label_text = f"{callsign}"
                    painter.setPen(QPen(Qt.GlobalColor.white))
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    painter.drawText(-30, -20, label_text)
                    
                    painter.restore()

            # --- Draw Ground Units (Convoys/Tanks) ---
            # DISABLED on Overlay per user request (Web Map only)
            # if self.map_ground_units:
            #    pass 




        # --- TEAM CHAT BOX (Bottom Left) ---
        # Only show when Map Overlay is visible (M pressed)
        if self.show_marker and self.team_chat_messages:
            chat_x = 10
            chat_y = self.height() - 20  # Start from bottom, move up
            line_height = 16
            max_messages = 10
            fade_duration = 30.0  # Seconds before message fades out
            
            current_time = time.time()
            
            # Get last N messages
            visible_messages = self.team_chat_messages[-max_messages:]
            
            painter.setFont(QFont("Arial", 9))
            
            for i, msg in enumerate(reversed(visible_messages)):
                msg_time = msg.get('time', current_time)
                age = current_time - msg_time
                
                # Skip messages older than fade_duration
                if age > fade_duration:
                    continue
                
                # Calculate alpha (fade out in last 5 seconds)
                if age > fade_duration - 5:
                    alpha = int(255 * (fade_duration - age) / 5)
                else:
                    alpha = 255
                
                sender = msg.get('sender', 'Unknown')
                text = msg.get('message', '')
                is_local = msg.get('local', False)
                
                # Choose color
                if is_local:
                    # Use our own color for local messages
                    sender_color = QColor(CONFIG.get('color', '#FFCC11'))
                else:
                    # White for network messages
                    sender_color = QColor(255, 255, 255)
                
                sender_color.setAlpha(alpha)
                text_color = QColor(220, 220, 220)
                text_color.setAlpha(alpha)
                
                # Draw sender name
                painter.setPen(QPen(sender_color))
                painter.drawText(chat_x, chat_y - (i * line_height), f"{sender}: ")
                
                # Calculate sender name width
                metrics = painter.fontMetrics()
                sender_width = metrics.horizontalAdvance(f"{sender}: ")
                
                # Draw message text
                painter.setPen(QPen(text_color))
                painter.drawText(chat_x + sender_width, chat_y - (i * line_height), text)

        # --- DEBUG OVERLAY ---
        if DEBUG_MODE and self.show_marker:
            # Draw red box around map area
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(
                int(MAP_OFFSET_X), 
                int(MAP_OFFSET_Y), 
                int(MAP_WIDTH), 
                int(MAP_HEIGHT)
            )
            
            # Removed center crosshair as requested

        # --- DRAW JDAM OVERLAY (Always on top, unconditional) ---
        self.draw_tti(painter)
        
        # if self.bomb_tracker.get_active_bombs():
        #      self.draw_graph(painter)

        # --- SAM / AAA THREAT WARNING (Unconditional) ---
        threat_type = None # None, "SAM", "AAA"
        
        if hasattr(self, 'map_ground_units') and '_local' in self.players:
            local_p = self.players['_local']
            local_x, local_y = local_p['x'], local_p['y']
            
            # Calculate Meters per Unit
            map_size_m = float(CONFIG.get('map_size_meters', 65000))
            if self.map_max and self.map_min:
                width_m = self.map_max[0] - self.map_min[0]
                height_m = self.map_max[1] - self.map_min[1]
                map_size_m = max(width_m, height_m)
            
            # Check 1: Enemy Airfield (SAM - 12km)
            # 12km in normalized coords
            sam_radius_norm = 12000 / map_size_m
            if self.airfields:
                for af in self.airfields:
                     # Check if enemy?
                     # Robust Color Check (QColor object to Hex String)
                     raw_color = af.get('color')
                     if isinstance(raw_color, QColor):
                         color_str = raw_color.name() # Returns #RRGGBB
                     else:
                         color_str = str(raw_color)

                     # Expanded Friendly Check (Blue variations + original specific codes)
                     is_friendly = (
                         '#043' in color_str or 
                         '#174D' in color_str or 
                         '4,63,255' in color_str or
                         color_str.lower().startswith('#00') or
                         color_str.lower().startswith('#4c') or
                         color_str.lower().startswith('#55')
                     )
                     
                     # Hardcode Blue channel check if QColor?
                     if isinstance(raw_color, QColor):
                         if raw_color.blue() > 150 and raw_color.red() < 100:
                             is_friendly = True
                     
                     if not is_friendly:
                         dist = math.hypot(af['x'] - local_x, af['y'] - local_y)
                         if dist < sam_radius_norm:
                             threat_type = "SAM"
                             break
            
            
            # Check 2: Enemy SPAA (AAA - 4.5km) - Overrides SAM if present (Imminent Threat)
            # 4.5km in normalized coords
            aaa_radius_norm = 4500 / map_size_m
            
            if self.map_ground_units:
                for unit in self.map_ground_units:
                    icon = (unit.get('icon') or '').lower()
                    if 'aa' in icon or 'spaa' in icon or 'sam' in icon:
                             # Check Color (Enemy Only)
                             color_str = str(unit.get('color', '#FF0000'))
                             is_friendly = '#043' in color_str or '#174D' in color_str or '4,63,255' in color_str
                             
                             u_x, u_y = unit.get('x', 0), unit.get('y', 0)
                             dist = math.hypot(u_x - local_x, u_y - local_y)
                             
                             if not is_friendly:
                                 if dist < aaa_radius_norm:
                                     threat_type = "AAA"
                                     break
        
        if threat_type:
            # Play VWS warning
            if hasattr(self, 'vws'):
                self.vws.play_warning(threat_type)

            # Flash effect (Sync with VWS Interval)
            # Default to 1Hz if VWS not present
            interval = 1.0
            if hasattr(self, 'vws'):
                interval = self.vws.interval
            
            # 50% Duty Cycle
            if (time.time() % interval) < (interval / 2):
                font_size = 28
                painter.setFont(QFont("Arial", font_size, QFont.Weight.Bold))
                
                warn_text = threat_type # "SAM" or "AAA"
                fm = QFontMetrics(painter.font())
                tw = fm.horizontalAdvance(warn_text)
                th = fm.height()
                
                # Bottom Left Position
                # 100px from Left, 200px from Bottom
                x = 100
                y = self.height() - 200
                
                # Draw Background Box
                padding = 10
                box_rect = QRectF(x - padding, y - th + (padding/2), tw + (padding*2), th + padding)
                
                painter.setBrush(QBrush(QColor(0, 0, 0, 180))) # Semi-transparent Black
                painter.setPen(QPen(QColor(255, 0, 0), 2)) # Red Border
                painter.drawRoundedRect(box_rect, 5, 5)
                
                # Draw Text
                painter.setPen(QPen(QColor(255, 0, 0))) # Red Text
                painter.drawText(x, y, warn_text)

    def draw_formation_panel(self, painter, cx, top_y, others):
        """Draws a list of nearby players under the compass"""
        if not self.players: return
        
        # Filter for remote players
        remote_players = []
        
        local_p = self.players.get('_local')
        if not local_p: return

        for pid, p in self.players.items():
            if pid == '_local': continue
            
            # Calculate Data
            # Distance
            raw_dx = p['x'] - local_p['x']
            raw_dy = p['y'] - local_p['y']
            
            # Scale to meters
            world_w = 65000 
            if self.map_max and self.map_min:
                 world_w = self.map_max[0] - self.map_min[0]
            
            dist_m = math.hypot(raw_dx * world_w, raw_dy * world_w)
            
            # Heading
            p_hdg = 0
            if abs(p.get('dx',0)) > 0.0001 or abs(p.get('dy',0)) > 0.0001:
                 p_hdg = math.degrees(math.atan2(p.get('dy',0), p.get('dx',0))) + 90
                 if p_hdg < 0: p_hdg += 360
                 
            remote_players.append({
                'callsign': p.get('callsign', 'Unknown'),
                'vehicle': p.get('vehicle', '-'), # 1. Extract Vehicle
                'dist': dist_m,
                'hdg': p_hdg,
                'alt': p.get('alt', 0),
                'spd': p.get('spd', 0),
                'color': p.get('color', Qt.GlobalColor.white)
            })
            
        # Sort by distance
        remote_players.sort(key=lambda x: x['dist'])
        
        if not remote_players: return

        # Draw List
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        line_h = 20
        # Updated Columns: Pilot, Type, Dist, Hdg, Alt, Spd
        col_widths = [90, 80, 50, 40, 40, 40] 
        total_w = sum(col_widths)
        
        y = top_y + 20
        x = cx - (total_w/2)
        
        # Background
        bg_rect = QRectF(x - 5, y - 5, total_w + 10, ((len(remote_players)+1) * line_h) + 10)
        painter.setBrush(QBrush(QColor(0, 0, 0, 200))) # Darker background
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.drawRect(bg_rect)
        
        # Header text
        header_labels = ["PILOT", "TYPE", "DST", "HDG", "ALT", "SPD"]
        cur_x = x
        for i, label in enumerate(header_labels):
            w = col_widths[i]
            painter.setPen(QPen(Qt.GlobalColor.gray))
            align_flag = Qt.AlignmentFlag.AlignLeft # Left align all titles
            rect = QRectF(cur_x + 2, y, w - 2, line_h) # Add 2px Left Padding
            painter.drawText(rect, align_flag | Qt.AlignmentFlag.AlignVCenter, label)
            cur_x += w
            
        y += line_h
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawLine(int(x), int(y), int(x+total_w), int(y)) # Header underline
        
        is_kts = CONFIG.get('unit_is_kts', True)
        
        for p in remote_players:
            # Format Data
            dist_unit = CONFIG.get('distance_unit', 'km').lower()
            if dist_unit == 'nm':
                if p['dist'] > 185.2: # Show 0.1nm precision above 0.1nm range
                     d_str = f"{p['dist']/1852:.1f}nm"
                else: 
                     d_str = f"{p['dist']/1852:.2f}nm" # More precision for close formation
            else:
                if p['dist'] > 1000: d_str = f"{p['dist']/1000:.1f}k"
                else: d_str = f"{p['dist']:.0f}m"
            
            spd_val = p['spd']
            if is_kts: spd_val *= 0.539957
            
            row_data = [
                p['callsign'],
                p['vehicle'], # Type
                d_str,
                f"{int(p['hdg']):03d}",
                f"{p['alt']/1000:.1f}",
                f"{int(spd_val)}"
            ]
            
            cur_x = x
            # Draw Row
            for i, text in enumerate(row_data):
                w = col_widths[i]
                
                # Color logic
                painter.setPen(QPen(Qt.GlobalColor.white))
                if i == 0: # Pilot Name
                    painter.setPen(QPen(p['color']))
                # No special color for Type yet?
                
                # Alignment
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                if i <= 1: # Pilot and Type Left Aligned
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                
                rect = QRectF(cur_x + 2, y, w - 4, line_h)
                
                # Clip text
                elided_text = painter.fontMetrics().elidedText(str(text), Qt.TextElideMode.ElideRight, int(w-4))
                painter.drawText(rect, align, elided_text)
                
                cur_x += w
            y += line_h       # Draw Vertical Lines
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        cur_x = x
        top_y_line = top_y + 20
        bottom_y_line = y
        for w in col_widths[:-1]: # Don't draw last line? or do?
            cur_x += w
            painter.drawLine(int(cur_x), int(top_y_line), int(cur_x), int(bottom_y_line))





    def toggle_console(self):
        self.show_console = not self.show_console
        print(f"[UI] Console Output: {self.show_console}")
        self.update()

    def update_physics(self):
        """Update physics simulations (Off-load from paintEvent)"""
        # Calculate Pre-Drop TTI
        dist_m = self.get_target_distance()
        if dist_m:
            try:
                sim = self.bomb_tracker.simulator
                sos = sim.get_sound_speed(self.current_altitude)
                mach = (self.current_speed / 3.6) / sos
                
                # Heavy Calculation
                tti, _, _ = sim.run(self.current_altitude, mach, dist_m)
                mode = sim.detect_flight_mode(self.current_altitude, mach, dist_m)
                
                # Format Result
                error_margin = tti * 0.05
                self.cached_predrop_text = f"[{mode}]: {tti:.0f}s (± {error_margin:.1f}s)"
                self.cached_predrop_color = QColor(0, 255, 255) # Cyan
                self.cached_predrop_mode = mode
            except Exception as e:
                # print(f"[PHYS] Error: {e}")
                self.cached_predrop_text = "ERR"
                self.cached_predrop_color = QColor(255, 0, 0)
        else:
            self.cached_predrop_text = None

    def get_target_distance(self):
        """Logic to determine current target distance in meters"""
        wp = None
        if hasattr(self, 'pois') and self.pois:
            wp = self.pois[-1] 
        elif hasattr(self, 'map_objectives') and self.map_objectives:
            wp = self.map_objectives[-1] 
        elif hasattr(self, 'user_pois') and self.user_pois:
            wp = self.user_pois[-1] 
        elif self.planning_waypoints and self.map_bounds:
            wp = self.planning_waypoints[-1] 
            
        if wp:
            local_p = self.players.get('_local')
            if local_p:
                dx = wp['x'] - local_p['x']
                dy = wp['y'] - local_p['y']
                dist_norm = math.hypot(dx, dy)
                
                map_size_m = float(CONFIG.get('map_size_meters', 65000))
                if self.map_max and self.map_min:
                    width_m = self.map_max[0] - self.map_min[0]
                    height_m = self.map_max[1] - self.map_min[1]
                    map_size_m = max(width_m, height_m)
                    
                return dist_norm * map_size_m
        return None

    def on_bomb_release(self):
        # Determine Target Distance
        target_dist_m = self.get_target_distance()
        if target_dist_m is None:
             target_dist_m = 15000.0  # Default fallback
        
        # Determine current telemetry
        altitude = self.current_altitude
        speed_tas = self.current_speed
        pitch = self.current_pitch
        
        # Record and simulate
        self.bomb_tracker.add_bomb(altitude, speed_tas, pitch, 0, target_dist_m)
        self.update()

    def draw_tti(self, painter):
        if not getattr(self, 'show_gbu_timers', True):
            return
            
        active_bombs = self.bomb_tracker.get_active_bombs()
        
        # Mode Shorthands
        shorthands = {
            'STEEP_DIVE': 'S',
            'MAX_RANGE': 'M',
            'LOW_ENERGY': 'L',
            'STANDARD': 'D'
        }

        num_bombs = len(active_bombs)
        
        # Layout Logic: 8 Bombs per column
        # Col 0: Pre-drop + Bombs 0-7
        # Col 1: Bombs 8-15
        # ...
        bombs_per_col = 8
        cols = math.ceil(num_bombs / bombs_per_col)
        if cols < 1: cols = 1
        
        # Dimensions
        col_width = 270 if cols == 1 else 250 # Wider for single column
        w = (col_width * cols) + 10
        
        # Calculate height
        # Max rows = 1 (Header) + 8 (Bombs) = 9
        max_rows = bombs_per_col + 1
        num_visual_rows = num_bombs + 1 if cols == 1 else max_rows
        
        h = 10 + (num_visual_rows * 25)
        x = self.width() - w - 50 # Constant margin
        y = 280
        
        # Background Box
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(0, 255, 0), 1))
        painter.drawRoundedRect(x, y, w, h, 5, 5)
        
        # List
        painter.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        
        # 0. Draw PRE-DROP Line (Cached)
        if self.cached_predrop_text:
            painter.setPen(self.cached_predrop_color)
            painter.drawText(x + 10, y + 20, self.cached_predrop_text)
        else:
            painter.setPen(QColor(150, 150, 150))
            painter.drawText(x + 10, y + 20, "NO TARGET")

        # 1. Draw Active Bombs
        for i, b in enumerate(active_bombs):
            # i is 0-indexed bomb counter
            col = i // bombs_per_col
            row = (i % bombs_per_col) + 1 # +1 to skip header row
            
            mode_raw = b.get('mode', 'N/A')
            mode_short = shorthands.get(mode_raw, mode_raw[:1])
            
            # Simplified ID for compact view
            bomb_id = str(b.get('id', i+1))
            
            if b['remaining'] <= 0:
                text = f"{bomb_id} [X]: IMPACT"
                color = QColor(255, 50, 50)
            else:
                error_margin = b['total_tti'] * 0.05
                text = f"{bomb_id} [{mode_short}]: T-{b['remaining']:.0f}s (± {error_margin:.1f}s)"
                color = QColor(50, 255, 50)
                
            draw_x = x + 10 + (col * col_width)
            draw_y = y + 20 + (row * 25)
            
            painter.setPen(color)
            painter.drawText(draw_x, draw_y, text)
            
    def draw_graph(self, painter):
        """Draws the Altitude vs Distance graph for the active bomb"""
        active_bombs = self.bomb_tracker.bombs # Access directly for history
        if not active_bombs: return
        
        bomb = active_bombs[0]
        history = bomb.get('history', [])
        if not history: return
        
        # Dimensions
        g_w = 400
        g_h = 150
        # Move to Left Side to avoid Compass (Right)
        g_x = 20 
        g_y = 100 # Below Status Text
        
        # Background
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(g_x, g_y, g_w, g_h)
        
        # Find Max values for scaling
        max_dist = 1
        max_alt = 1
        
        # History format: (time, dist_x, alt_y, velocity)
        # x starts at 0, target is at 'dist'
        target_dist = bomb['telem']['dist']
        launch_alt = bomb['telem']['alt']
        
        max_dist = target_dist * 1.1 # 10% margin
        max_alt = launch_alt * 1.1
        
        # Draw Axis Labels
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(g_x + 5, g_y + 15, f"{int(max_alt)}m") # Top Left (Y Axis)
        painter.drawText(g_x + g_w - 40, g_y + g_h - 5, f"{int(max_dist/1000)}km") # Bottom Right (X Axis)
        
        # Draw Trajectory with Phase Colors (Segments)
        # History format: (time, dist_x, alt_y, velocity, phase, gamma, alpha)
        
        phase_colors = {
            "RELEASE": QColor(255, 255, 255),
            "BALLISTIC": QColor(200, 200, 200), # Gray
            "LOFT": QColor(0, 255, 255),        # Cyan
            "GLIDE": QColor(0, 255, 0),         # Green
            "GUIDANCE": QColor(255, 0, 255)     # Magenta
        }
        
        # Origin (Start of graph)
        # Screen Y = (g_y + g_h) - (h / max_alt) * g_h
        
        prev_pt = None
        for i in range(len(history)):
            pt_data = history[i]
            t, dist_x, alt_y, v = pt_data[0], pt_data[1], pt_data[2], pt_data[3]
            
            # Map to Screen
            if max_dist == 0: continue
            sx = g_x + (dist_x / max_dist) * g_w
            sy = (g_y + g_h) - (alt_y / max_alt) * g_h
            current_pt = QPointF(sx, sy)
            
            if prev_pt:
                color = QColor(255, 255, 0) # Default
                if len(pt_data) > 4:
                    phase = pt_data[4]
                    color = phase_colors.get(phase, color)
                
                painter.setPen(QPen(color, 2))
                painter.drawLine(prev_pt, current_pt)
            
            prev_pt = current_pt
            
        # Draw "Live" Bomb Position
        elapsed = time.time() - bomb['release_time']
        
        # Find closest history point
        closest_pt = None
        for pt in history:
            if pt[0] >= elapsed:
                closest_pt = pt
                break
        
        # If simulation ended, stick to last point
        if not closest_pt and history:
            closest_pt = history[-1]
            
        if closest_pt:
            t, dist_x, alt_y, v = closest_pt[0], closest_pt[1], closest_pt[2], closest_pt[3]
            sx = g_x + (dist_x / max_dist) * g_w
            sy = (g_y + g_h) - (alt_y / max_alt) * g_h
            
            # Draw Bomb Icon
            painter.setBrush(QColor(255, 50, 50))
            painter.drawEllipse(QPointF(sx-3, sy-3), 6, 6)
            
            # Draw Velocity Vector & Attitude if available
            if len(closest_pt) > 6:
                phase = closest_pt[4]
                gamma = closest_pt[5] # Radians
                alpha = closest_pt[6] # Radians
                pitch = gamma + alpha
                
                # Velocity Vector (Cyan)
                vx_len = 25 * math.cos(-gamma) 
                vy_len = 25 * math.sin(-gamma)
                painter.setPen(QPen(QColor(0, 255, 255), 1)) 
                painter.drawLine(int(sx), int(sy), int(sx + vx_len), int(sy + vy_len))
                
                # Body Axis (Salmon/Red)
                bx_len = 20 * math.cos(-pitch)
                by_len = 20 * math.sin(-pitch)
                painter.setPen(QPen(QColor(255, 100, 100), 2)) 
                painter.drawLine(int(sx), int(sy), int(sx + bx_len), int(sy + by_len))
                
                # Info Text
                painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(sx) + 10, int(sy) - 15, f"T-{closest_pt[0]:.1f}s | {phase}")
                painter.setFont(QFont("Consolas", 8))
                painter.drawText(int(sx) + 10, int(sy) - 2, f"M{v/340:.2f} | AoA: {math.degrees(alpha):.1f}°")
                painter.drawText(int(sx) + 10, int(sy) + 10, f"Alt: {alt_y:.0f}m")
            else:
                 painter.setPen(QColor(255, 255, 255))
                 painter.drawText(int(sx) + 10, int(sy), f"T+{t:.1f}s")

    def draw_attitude_diagram(self, painter, bomb):
        """Draws a detailed attitude indicator for the bomb"""
        history = bomb.get('history', [])
        if not history: return

        # Dimensions & Position (Bottom Right)
        w = 200
        h = 200
        x = self.width() - w - 20
        y = self.height() - h - 20
        
        # Background
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawRect(x, y, w, h)
        
        # Center
        cx = x + w / 2
        cy = y + h / 2
        
        # Get Current Telemetry from History
        elapsed = time.time() - bomb['release_time']
        closest_pt = None
        for pt in history:
            if pt[0] >= elapsed:
                closest_pt = pt
                break
        if not closest_pt and history: closest_pt = history[-1]
        
        if not closest_pt: return
        
        # Data: t, dist_x, alt_y, v, phase, gamma, alpha
        # Handling potential missing data if history format changed mid-run
        if len(closest_pt) > 6:
            t = closest_pt[0]
            v = closest_pt[3]
            phase = closest_pt[4]
            gamma = closest_pt[5] # Radians (Flight Path Angle)
            alpha = closest_pt[6] # Radians (Angle of Attack)
            pitch = gamma + alpha # Pitch Attitude
            
            # --- Visuals ---
            
            painter.save()
            painter.translate(cx, cy)
            
            # Draw Horizon Line (White)
            painter.setPen(QPen(QColor(100, 100, 100), 1, Qt.PenStyle.DashLine))
            painter.drawLine(-90, 0, 90, 0) # Horizon
            
            # Rotate to Bomb Pitch
            pitch_deg = math.degrees(pitch)
            painter.rotate(-pitch_deg) # Negative because screen Y is down
            
            # Draw Bomb Body
            painter.setPen(QPen(QColor(255, 255, 255), 3))
            painter.drawLine(-40, 0, 40, 0) # Fuselage
            # Fins
            painter.drawLine(-40, 0, -50, -10)
            painter.drawLine(-40, 0, -50, 10)
            
            # Draw Velocity Vector relative to Body
            # V vector is at -alpha relative to body
            alpha_deg = math.degrees(alpha)
            painter.rotate(alpha_deg) 
            
            painter.setPen(QPen(QColor(0, 255, 255), 2)) # Cyan
            painter.drawLine(0, 0, 60, 0) # Velocity Vector
            painter.drawText(65, 5, "V")
            
            painter.restore()
            
            # 2. Text Data
            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))
            
            # Phase
            painter.drawText(x + 10, y + 20, f"PHASE: {phase}")
            
            # Telemetry
            painter.setFont(QFont("Consolas", 9))
            painter.drawText(x + 10, y + 40, f"TIME: {t:.1f}s")
            painter.drawText(x + 10, y + 55, f"MACH: {v/340:.2f}")
            painter.drawText(x + 10, y + 70, f"AoA : {math.degrees(alpha):.1f}°")
            painter.drawText(x + 10, y + 85, f"PITCH: {pitch_deg:.1f}°")
            
            # 3. G-Load Bar (AoA)
            bar_w = 15
            bar_h = 80
            bx = x + w - 25
            by = y + 40
            
            painter.setPen(QColor(100, 100, 100))
            painter.drawRect(bx, by, bar_w, bar_h)
            
            # Fill relative to max AoA (22 deg)
            fill_h = (max(0, math.degrees(alpha)) / 22.0) * bar_h
            if fill_h > bar_h: fill_h = bar_h
            
            c = QColor(0, 255, 0)
            if math.degrees(alpha) > 10: c = QColor(255, 255, 0)
            if math.degrees(alpha) > 18: c = QColor(255, 0, 0)
            
            painter.setBrush(c)
            painter.drawRect(bx, by + bar_h - int(fill_h), bar_w, int(fill_h))
            painter.drawText(bx-5, by + bar_h + 15, "AoA")

    def draw_console(self, painter):
        # Draw a semi-transparent background box at MID RIGHT
        w = 400
        h = 250
        x = self.width() - w - 20
        y = 300 
        
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(x, y, w, h)
        
        # Draw Logs
        logs = self.bomb_tracker.get_logs()
        font = QFont("Consolas", 10)
        painter.setFont(font)
        painter.setPen(QColor(200, 200, 200))
        
        line_h = 15
        cur_y = y + 20
        
        for log in logs[-15:]: # Show last ~15 lines to fit
            painter.drawText(x + 10, cur_y, log)
            cur_y += line_h

def print_welcome():
    welcome = """\r
LINK 18\r
\r
[INFO] Starting overlay application...\r
[INFO] Callsign: {callsign}\r
[INFO] Calibrate map: Hold M + Press N\r
[INFO] Show overlay: Press {key}\r
[INFO] Network: {ip}:{port}\r
"""
    print(welcome.format(
        callsign=CONFIG.get('callsign', 'Unknown'),
        key=CONFIG.get('activation_key', 'm').upper(),
        ip=CONFIG.get('broadcast_ip', 'N/A'),
        port=CONFIG.get('udp_port', 50050)
    ))

class ControllerWindow(QWidget):
    def __init__(self, overlay_window):
        super().__init__()
        self.overlay = overlay_window
        self.setup_ui()
        
    def setup_ui(self):
        self.setWindowTitle("Link18 Tactical Controller")
        self.setGeometry(100, 100, 350, 200)
        
        layout = QVBoxLayout()
        
        title = QLabel("Link18 Tactical Overlay")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = QFont("Arial", 12, QFont.Weight.Bold)
        title.setFont(font)
        layout.addWidget(title)
        
        # Add map URL info
        map_url = QLabel("Tactical Web Map:\nhttp://localhost:8000")
        map_url.setAlignment(Qt.AlignmentFlag.AlignCenter)
        map_url.setStyleSheet("color: #043FFF; font-weight: bold;")
        layout.addWidget(map_url)

        # Added Map Overlay Toggle
        from PyQt6.QtWidgets import QCheckBox
        self.overlay_toggle = QCheckBox("Enable Map Overlay (Screen)")
        self.overlay_toggle.setChecked(CONFIG.get('default_map_visible', True))
        self.overlay_toggle.setStyleSheet("font-weight: bold; margin: 10px; color: black;")
        self.overlay_toggle.stateChanged.connect(self.toggle_overlay)
        layout.addWidget(self.overlay_toggle, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Formation Mode Toggle
        self.formation_toggle = QCheckBox("Enable Formation Mode")
        # Default to False or whatever the overlay has. 
        # But wait, overlay defaults to False. Let's assume False.
        self.formation_toggle.setChecked(False) 
        self.formation_toggle.setStyleSheet("font-weight: bold; margin: 10px; color: black;")
        self.formation_toggle.stateChanged.connect(self.toggle_formation)
        layout.addWidget(self.formation_toggle, 0, Qt.AlignmentFlag.AlignCenter)
        
        # GBU Timers Toggle
        self.gbu_toggle = QCheckBox("Enable GBU Timers (BETA)")
        self.gbu_toggle.setChecked(True)
        self.gbu_toggle.setStyleSheet("font-weight: bold; margin: 10px; color: black;")
        self.gbu_toggle.stateChanged.connect(self.toggle_gbu)
        layout.addWidget(self.gbu_toggle, 0, Qt.AlignmentFlag.AlignCenter)
        
        shutdown_btn = QPushButton("TERMINATE LINK18")
        shutdown_btn.setStyleSheet("background-color: #ff4444; color: white; padding: 10px; font-weight: bold; border-radius: 4px;")
        shutdown_btn.clicked.connect(self.close)
        layout.addWidget(shutdown_btn)
        
        self.setLayout(layout)
        
    def toggle_overlay(self, state):
        enabled = (state == 2) # Qt.CheckState.Checked
        self.overlay.set_overlay_enabled(enabled)
        print(f"[CONTROLLER] Overlay {'ENABLED' if enabled else 'DISABLED'}")

    def toggle_formation(self, state):
        enabled = (state == 2)
        self.overlay.show_formation_mode = enabled
        print(f"[CONTROLLER] Formation Mode {'ENABLED' if enabled else 'DISABLED'}")

    def toggle_gbu(self, state):
        enabled = (state == 2)
        self.overlay.show_gbu_timers = enabled
        print(f"[CONTROLLER] GBU Timers {'ENABLED' if enabled else 'DISABLED'}")
        
    def closeEvent(self, event):
        # Close the overlay when controller is closed
        self.overlay.close()
        event.accept()

def main():
    try:
        # Display welcome screen
        print_welcome()
        
        # Disable High DPI scaling to ensure 1:1 pixel mapping with game
        import os
        os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"

        app = QApplication(sys.argv)
        
        # Create Overlay (Hidden/Transparent)
        overlay = OverlayWindow()
        
        # Create Controller (Visible Window)
        controller = ControllerWindow(overlay)
        controller.show()
        
        # Ensure overlay is initialized (it handles its own visibility via keys, 
        # but needs to be 'shown' to receive global events/painting if not fully hidden)
        overlay.show() 
        
        # Setup global key monitor
        activation_key = CONFIG.get('activation_key', 'm')
        monitor = KeyMonitor(activation_key)
        monitor.show_signal.connect(overlay.set_marker_visible)
        monitor.hide_signal.connect(overlay.set_marker_hidden)
        # monitor.debug_signal.connect(overlay.toggle_debug) # Removed
        monitor.broadcast_airfields_signal.connect(overlay.broadcast_airfields)  # Connect B key to broadcast
        monitor.calibrate_signal.connect(overlay.trigger_calibration)  # Connect M+N to calibration
        monitor.bomb_release_signal.connect(overlay.on_bomb_release) # Connect Spacebar
        monitor.toggle_console_signal.connect(overlay.toggle_console) # Connect J key
        
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        traceback.print_exc()
        input("Critical Error! Press Enter to close...")

if __name__ == "__main__":
    main()                               