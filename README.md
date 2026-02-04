# Link18 v1.3.1 - Tactical Overlay for War Thunder

**Link18** is a transparent tactical overlay and web-based map for War Thunder that enables real-time squad coordination via shared markers, flight timers, and NATO-standard unit symbology.

---

## Quick Start

1. Run `Link18.exe`
2. Switch to War Thunder (Borderless Window mode)
3. Hold **M** to show overlay
4. Open `http://localhost:8000` for the web map

---

## Features

| Feature | Description |
|---------|-------------|
| **Tactical Map** | Real-time overlay with NATO APP-6 symbology |
| **Web Map** | Browser-based map at `localhost:8000` with zoom/pan |
| **Shared Intel** | Airfields, CVs, and POIs sync between squad members |
| **Flight Timers** | T+ mission timer, T- coordinator countdown |
| **Auto-Calibration** | Press **M+N** to automatically align overlay with map (Computer Vision) |
| **Real Names** | Vehicle IDs converted to real names (e.g. "f_16c" -> "F-16C Block 50") |
| **Compass Rose** | toggleable on-screen compass with heading and bearing indicators |
| **Dynamic ETA** | Time-enroute calculation to waypoints based on current or manual speed |
| **Waypoint Mode** | Draw flight paths on the Web Map that sync to the in-game overlay |
| **Convoy Info** | Hover details for ground columns (composition, count) |
| **Smart Declutter** | Overlapping icons auto-hide, SAMs prioritized |

---

## Web Map

The **Link18 Web Map** is accessible at `http://localhost:8000`. It is designed for:
- **Second Monitors**: Keep a full tactical view open while flying.
- **Tablets/Phones**: Access the map from any device on your LAN (e.g., `http://192.168.1.X:8000`).
- **Squad Leaders**: Coordinate movements with a zoomable, pannable strategic view.

**Capabilities:**
- **Real-time Sync**: Updates instantly with the overlay.
- **Tactical Grid**: Displays the in-game map grid with coordinates.
- **Shared Intel**: Shows all squad airfields and POIs.

### Web Map Toolbar
The top-left toolbar provides quick access to:
- **Compass Rose**: Toggles the on-screen compass overlay.
- **POI/ETA**: Toggles distance and time-to-target labels. Click to open **Speed Override** panel.
- **Planning Mode**: (Pencil Icon) Draw waypoints for squad coordination.
- **Formation Mode**: (Arrows Icon) Syncs formation status with the squad.
- **Convoy Info**: (Truck Icon) Displays detailed composition of ground columns.

### Web Settings
Click the **Settings** button (bottom right) to:
- Change **Distance Units** (KM / NM).
- Adjust **Marker Size** (0.5x - 3.0x).
- Toggle **Grid Debug** mode.


## Configuration (`config.json`)


```json
{
    "callsign": "YourCallsign",
    "color": "#FFCC11",
    "udp_port": 50050,
    "broadcast_ip": "10.30.194.255",
    "map_offset_x": 723,
    "map_offset_y": 199,
    "map_width": 818,
    "map_height": 818,
    "activation_key": "m",
    "enable_map_overlay": true,
    "timer_interval": 15,
    "unit_is_kts": true,
    "trail_duration": 180,
    "enable_web_map": true,
    "disable_lan_broadcast": false,
    "web_marker_scale": 2.3,
    "debug_mode": false
}
```

| Key | Type | Description |
|-----|------|-------------|
| `callsign` | string | Your display name |
| `color` | hex | Your marker color |
| `udp_port` | int | Network port (default: 50050) |
| `broadcast_ip` | string | LAN/VPN broadcast address (must end in `.255`) |
| `map_offset_x/y` | int | **(New)** Manual overlay alignment offset (pixels) |
| `map_width/height` | int | **(New)** Manual overlay size (pixels) |
| `activation_key` | string | Key to hold for overlay |
| `timer_interval` | int | T- countdown interval (minutes) |
| `unit_is_kts` | bool | `true`=Knots, `false`=km/h |
| `trail_duration` | int | Flight path history (seconds) |
| `disable_lan_broadcast` | bool | **(New)** If `true`, only receives data (silent mode) |
| `web_marker_scale` | float | Icon size on web map |

---

## Network Setup

**For LAN/Virtual LAN (ZeroTier, Hamachi):**

1. Ensure all squad members use the **same `broadcast_ip`**
2. Format: If your IP is `10.147.19.42`, use `10.147.19.255`
3. Allow **UDP port 50050** through firewall

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Overlay not showing | Use Borderless Window mode |
| Players not visible | Check firewall, verify `broadcast_ip` |
| Phantom airfield | Restart app (stale data expires in 60s) |
| Grid labels wrong | Refresh browser |

---

## For Developers

Detailed technical documentation, including project structure, architecture, and network protocols, can be found in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

---

## Symbology Reference

| Symbol | Meaning |
|--------|---------|
| Blue Rectangle | Friendly Ground |
| Red Diamond | Hostile Ground |
| Dome icon | Air Defense / SAM |
| Triangle icon | Anti-Tank / ATGM |
| Capsule icon | Heavy Armor |
| Dots above icon | Unit strength (•=1, •••=Platoon, \|=Company) |

---

## License

MIT License - See LICENSE file for details.
