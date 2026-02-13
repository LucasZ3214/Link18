import http.server
import socketserver
import json
import time
from urllib.parse import urlparse, parse_qs

PORT = 8111

# Data provided by user (Now served on /hudmsg)
MOCK_HUD_DATA = [
    { "id": 3, "msg": "Byelka (F-16C) has delivered the first strike!", "sender": "", "enemy": False, "mode": "", "time": 253 },
    { "id": 4, "msg": "Byelka (F-16C) destroyed Gepard", "sender": "", "enemy": False, "mode": "", "time": 255 },
    { "id": 5, "msg": "Byelka (F-16C) destroyed Gepard", "sender": "", "enemy": False, "mode": "", "time": 257 },
    { "id": 6, "msg": "Byelka (F-16C) destroyed Gepard", "sender": "", "enemy": False, "mode": "", "time": 261 },
    { "id": 7, "msg": "Byelka (F-16C) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 267 },
    { "id": 8, "msg": "Byelka (F-16C) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 269 },
    { "id": 9, "msg": "Byelka (F-16C) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 270 },
    { "id": 10, "msg": "RyanFL (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 300 },
    { "id": 11, "msg": "RyanFL (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 303 },
    { "id": 12, "msg": "RyanFL (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 306 },
    { "id": 13, "msg": "RyanFL (F-2A) has achieved \"Triple strike!\"", "sender": "", "enemy": False, "mode": "", "time": 307 },
    { "id": 14, "msg": "RyanFL (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 308 },
    { "id": 15, "msg": "RyanFL (F-2A) has achieved \"Ground multi strike x4!\"", "sender": "", "enemy": False, "mode": "", "time": 309 },
    { "id": 16, "msg": "RyanFL (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 313 },
    { "id": 17, "msg": "RyanFL (F-2A) has achieved \"Ground multi strike x5!\"", "sender": "", "enemy": False, "mode": "", "time": 314 },
    { "id": 18, "msg": "RyanFL (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 322 },
    { "id": 19, "msg": "RyanFL (F-2A) has achieved \"Triple strike!\"", "sender": "", "enemy": False, "mode": "", "time": 323 },
    { "id": 20, "msg": "M-ASENS1O (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 372 },
    { "id": 21, "msg": "M-ASENS1O (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 372 },
    { "id": 22, "msg": "M-ASENS1O (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 373 },
    { "id": 23, "msg": "M-ASENS1O (F-2A) has achieved \"Ground multi strike x4!\"", "sender": "", "enemy": False, "mode": "", "time": 374 },
    { "id": 24, "msg": "M-ASENS1O (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 375 },
    { "id": 25, "msg": "M-ASENS1O (F-2A) has achieved \"Ground multi strike x5!\"", "sender": "", "enemy": False, "mode": "", "time": 375 },
    { "id": 26, "msg": "M-ASENS1O (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 377 },
    { "id": 27, "msg": "M-ASENS1O (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 377 },
    { "id": 28, "msg": "M-ASENS1O (F-2A) has achieved \"Ground multi strike x7!\"", "sender": "", "enemy": False, "mode": "", "time": 378 },
    { "id": 29, "msg": "M-ASENS1O (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 380 },
    { "id": 30, "msg": "M-ASENS1O (F-2A) has achieved \"Ground multi strike x8!\"", "sender": "", "enemy": False, "mode": "", "time": 381 },
    { "id": 31, "msg": "RyanFL (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 412 },
    { "id": 32, "msg": "風野あさぎ (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 425 },
    { "id": 33, "msg": "風野あさぎ (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 428 },
    { "id": 34, "msg": "風野あさぎ (F-2A) has achieved \"Triple strike!\"", "sender": "", "enemy": False, "mode": "", "time": 428 },
    { "id": 35, "msg": "風野あさぎ (F-2A) destroyed AMX-30 S DCA", "sender": "", "enemy": False, "mode": "", "time": 430 },
    { "id": 158, "msg": "風野あさぎ (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 863 },
    { "id": 160, "msg": "風野あさぎ (F-2A) destroyed ▄ItO 90M", "sender": "", "enemy": False, "mode": "", "time": 1428 }
]

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence logs
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        
        # User specified endpoint
        if parsed.path == "/hudmsg":
            print(f"[MOCK] Handling /hudmsg request")
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            
            # Wrap in standard structure
            response = {
                "events": [],
                "damage": MOCK_HUD_DATA
            }
            
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            return
            
        if parsed.path == "/gamechat":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps([]).encode('utf-8')) # Empty
            return

        # Mock other endpoints
        if parsed.path == "/map_obj.json":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps([]).encode('utf-8'))
            return
            
        if parsed.path == "/state":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({}).encode('utf-8'))
            return
            
        if parsed.path == "/indicators":
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({}).encode('utf-8'))
            return
            
        if parsed.path == "/map_info.json":
             self.send_response(200)
             self.send_header('Content-Type', 'application/json')
             self.end_headers()
             self.wfile.write(json.dumps({
                 "map_min": [0, 0],
                 "map_max": [65000, 65000],
                 "grid_size": [8125, 8125],
                 "grid_zero": [0, 0],
                 "grid_steps": [1000, 1000]
             }).encode('utf-8'))
             return

        self.send_response(404)
        self.end_headers()

def run():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"==================================================")
        print(f" MOCK War Thunder API Server running on Port {PORT}")
        print(f" Serving HUD MSG Data on /hudmsg")
        print(f"==================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    run()
