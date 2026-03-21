"""
Link18 Configuration Module
Loads config.json and provides shared constants used across all modules.
"""
import json
import os

# Version Tag
VERSION_TAG = "v1.8.1"

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
        "broadcast_ip": "255.255.255.255",
        "show_gbu_timers": False,
        "enable_velocity_vector": True
    }

# API & Polling Constants
API_URL = "http://127.0.0.1:8111/map_obj.json"
POLL_INTERVAL_MS = 40
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

# ==========================================
# VELOCITY VECTOR / FPM CONFIGURATION
# ==========================================
ENABLE_VELOCITY_VECTOR = CONFIG.get('enable_velocity_vector', True)
ZOOM_TOGGLE_KEY = CONFIG.get('zoom_key', 'z')
HUD_FOV_NORMAL = CONFIG.get('hud_fov_normal', 15.0)  # Pixels per degree
HUD_FOV_ZOOMED = CONFIG.get('hud_fov_zoomed', 30.0)  # Pixels per degree

ENABLE_JOYSTICK_ZOOM = CONFIG.get('enable_joystick_zoom', False)
JOYSTICK_ID = CONFIG.get('joystick_id', 0)
JOYSTICK_ZOOM_AXIS = CONFIG.get('joystick_zoom_axis', 2) # Typically a slider or throttle
JOYSTICK_ZOOM_INVERT = CONFIG.get('joystick_zoom_invert', False)
JOYSTICK_AXIS_DEADZONE = CONFIG.get('joystick_axis_deadzone', 0.05)
