import http.server
import socketserver
import threading
import json
import os
import time
import requests
import io
import socket
import hashlib

# Load config.json directly to avoid circular import
CONFIG = {}
def load_config():
    global CONFIG
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r') as f:
                CONFIG = json.load(f)
    except:
        pass
load_config()

# Configuration
PORT = 8000
DIRECTORY = "web"

# Shared Data Reference (Main thread updates this, Server reads it)
SHARED_DATA = {
    'players': {},
    'airfields': [],
    'pois': [],
    'map_info': {},
    'timer': {'flight_time': 0, 'spawn_time': None},
    'config': {}
}

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            # Serialize data safely
            try:
                # Create a serialized copy of players (converting datatypes if needed)
                players_safe = {}
                for pid, p in SHARED_DATA['players'].items():
                    players_safe[pid] = {
                        'x': p.get('x'),
                        'y': p.get('y'),
                        'dx': p.get('dx', 0),
                        'dy': p.get('dy', 0),
                        'callsign': p.get('callsign'),
                        'color': p.get('color').name() if hasattr(p.get('color'), 'name') else str(p.get('color')),
                        'trail': p.get('trail', []),
                        'alt': p.get('alt', 0),  # Altitude in meters
                        'spd': p.get('spd', 0),   # Speed in km/h
                        'vehicle': p.get('vehicle', '') # Vehicle Type
                    }
                
                airfields_safe = []
                for af in SHARED_DATA['airfields']:
                    airfields_safe.append({
                        'x': af.get('x'),
                        'y': af.get('y'),
                        'angle': af.get('angle'),
                        'len': af.get('len', 0), # Transmit runway length
                        'is_cv': af.get('is_cv', False),
                        'id': af.get('id', 0),  # Transmit ID for labeling
                        'color': af.get('color').name() if hasattr(af.get('color'), 'name') else str(af.get('color'))
                    })


                pois_safe = []
                for poi in SHARED_DATA['pois']:
                    pois_safe.append({
                        'x': poi.get('x'),
                        'y': poi.get('y'),
                        'icon': poi.get('icon'),
                        'color': poi.get('color').name() if hasattr(poi.get('color'), 'name') else str(poi.get('color')),
                        'owner': poi.get('owner', '')  # Callsign of who marked it
                    })


                response_data = {
                    'players': players_safe,
                    'airfields': airfields_safe,
                    'pois': pois_safe,
                    'objectives': SHARED_DATA.get('objectives', []), # Send bombing/defending points
                    'map_objectives': SHARED_DATA.get('map_objectives', []),  # Added Capture Zones & Objectives
                    'ground_units': SHARED_DATA.get('ground_units', []), # Ground units
                    'map_info': SHARED_DATA['map_info'],
                    'timer': SHARED_DATA['timer'],
                    'config': {
                        'unit_is_kts': CONFIG.get('unit_is_kts', True),  # Speed unit setting
                        'web_marker_scale': CONFIG.get('web_marker_scale', 2.3)  # Manual scaling factor
                    }
                }
                
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                print(f"API Error: {e}")
                self.wfile.write(b'{}')
            return

        elif self.path.startswith('/proxy/map.img'):
            # Proxy map image from War Thunder
            # Request higher resolution map (4096px)
            try:
                import urllib.request
                response = urllib.request.urlopen("http://localhost:8111/map.img?gen=1&size=4096", timeout=5)
                content = response.read()
                
                if len(content) > 0:
                    self.send_response(200)
                    self.send_header('Content-type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    print(f"[WEB] Map proxy: Got empty content")
                    self.send_error(404)
            except Exception as e:
                print(f"[WEB] Map proxy ERROR: {type(e).__name__}: {e}")
                self.send_error(502)
            return

        # Serve static files from 'web' directory
        # Adjust path to serve from 'web/' subdir
        if self.path == '/' or self.path == '':
            self.path = '/dashboard.html'
            
        return http.server.SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if self.path == '/api/command':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                command = json.loads(post_data.decode('utf-8'))
                
                # Append to shared commands queue for Main Thread to process
                if 'commands' not in SHARED_DATA:
                    SHARED_DATA['commands'] = []
                    
                SHARED_DATA['commands'].append(command)
                print(f"[WEB] Received command: {command}")
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            except Exception as e:
                print(f"[WEB] Command Error: {e}")
                self.send_error(400)
            return
            
        return super().do_GET() # Fallback

    def log_message(self, format, *args):
        # Silence access logs (e.g. "GET /api/data 200")
        return

    def translate_path(self, path):
        # Override to serve from specific directory
        path = http.server.SimpleHTTPRequestHandler.translate_path(self, path)
        relpath = os.path.relpath(path, os.getcwd())
        return os.path.join(os.getcwd(), DIRECTORY, relpath)

def run_server(shared_data_ref, port=8000):
    global SHARED_DATA
    SHARED_DATA = shared_data_ref
    
    # Ensure web directory exists
    if not os.path.exists(DIRECTORY):
        os.makedirs(DIRECTORY)
        
    # Standard handler doesn't support 'directory' arg in older python 3.6, 
    # but we can just chdir or use custom logic. 
    # Easier: Just use a custom handler that serves relative to DIRECTORY.
    
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=DIRECTORY, **kwargs)
        
        def do_GET(self):
            # API Override
            if self.path == '/api/data':
                DashboardHandler.do_GET(self)
                return
            if self.path.startswith('/proxy/map.img'):
                DashboardHandler.do_GET(self)
                return
            if self.path.startswith('/proxy/map.img'):
                DashboardHandler.do_GET(self)
                return
            super().do_GET()

        def do_POST(self):
            DashboardHandler.do_POST(self)
        
        def log_message(self, format, *args):
            # Silence logs
            return
            
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    
    try:
        httpd = socketserver.TCPServer(("", port), Handler)
        
        # Get all local IPs
        hostname = socket.gethostname()
        try:
            local_ips = socket.gethostbyname_ex(hostname)[2]
        except:
            local_ips = [socket.gethostbyname(hostname)]
            
        print(f"[WEB] Dashboard Server running on Port {port}")
        for ip in local_ips:
            print(f"      - http://{ip}:{port}")
            
        httpd.serve_forever()
    except Exception as e:
        print(f"[WEB] Server Error: {e}")

def start_background_server(shared_data, port=8000):
    t = threading.Thread(target=run_server, args=(shared_data, port), daemon=True)
    t.start()
