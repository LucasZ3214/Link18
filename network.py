"""
Link18 Network Module
Background threads for UDP reception and HTTP telemetry polling.
"""
import socket
import json
import time
import requests
from PyQt6.QtCore import pyqtSignal, QThread

from config import UDP_PORT, DEBUG_MODE


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
