# Link18 Developer Documentation

## Project Structure

```
Link18/
├── main.py              # Core overlay + network logic 
├── jdamertti.py         # Standalone JDAM physics simulator
├── vws.py               # Voice Warning System (audio alerts)
├── web_server.py        # Flask server for web map API
├── auto_calibrate_new.py# Map calibration logic (CV-based)
├── create_release.py    # Release automation script
├── sounds/              # VWS audio files
│   ├── vws_sam.wav      # SAM warning audio
│   ├── vws_aaa.wav      # AAA warning audio
│   └── welcome/         # Random startup greetings
├── web/
│   └── dashboard.html   # Web map UI (Canvas-based)
├── config.json          # User configuration
├── vehicles.json        # Vehicle name translation map
├── Link18.spec          # PyInstaller build spec
└── requirements.txt     # Python dependencies
```

### JDAM Simulation Architecture (`jdamertti.py`)

The GBU-62/JDAM-ER simulation is now a self-contained module:
- **Physics**: Implements 3-DOF kinematics with drag/lift modulation.
- **Modes**:
    - **Steep Dive**: High-drag/high-AOA mode for short-range drops.
    - **Max Range**: Glide-optimization mode for long-distance strikes.
    - **Standard**: Balanced profile.
- **Integration**: `main.py` instantiates `BombTracker` which manages multiple `GBU62_Simulator` instances.
- **Tuning**: All physics constants (Drag, Lift, Pitch Schedules) are defined at the top of `jdamertti.py`.


### Architecture Overview

```
┌─────────────────┐     UDP Broadcast      ┌─────────────────┐
│   Link18 App    │◄─────────────────────► │  Other Players  │
│   (main.py)     │      Port 50050        │                 │
└────────┬────────┘                        └─────────────────┘
         │
         │ HTTP API (localhost:8111)
         ▼
┌─────────────────┐
│  War Thunder    │  ← Game provides telemetry
│  (Game Client)  │
└─────────────────┘
         │
         │ HTTP API (localhost:8000)
         ▼
┌─────────────────┐
│   Web Map       │  ← Browser-based tactical view
│ (dashboard.html)│
└─────────────────┘
```

### Key Classes (main.py)

| Class | Purpose |
|-------|---------|
| `OverlayWindow` | Main transparent overlay, handles painting, telemetry processing, network |
| `TelemetryFetcher` | Background thread for HTTP polling (prevents audio stutter) |
| `NetworkReceiver` | UDP listener thread for incoming packets |
| `KeyMonitor` | Keyboard listener. Handles 'M' (Show) and 'M+N' (Calibrate) |
| `ControllerWindow` | Small control panel window |

### Voice Warning System (`vws.py`)

The VWS module provides audio alerts for threats:
- **SoundManager**: Manages loading/playing `.wav` files and synthesized tones.
- **Synthesized Fallback**: When `enable_vws` is `false`, generates sine-wave tones.
- **Normalization**: Optional loudness normalization to -0.2dB headroom.
- **Startup Tone**: Procedurally generated ascending fourths chime.

### Data Flow

1. **Telemetry Fetch**: `TelemetryFetcher` (background thread) polls WT API every 100ms.
2. **Data Processing**: `on_telemetry_data()` processes fetched data on main thread (non-blocking).
3. **Map Sync**: Map bounds updated from `map_info.json` (fetched by background thread).
4. **Physics**: `update_physics()` runs JDAM simulations at 10Hz on a separate timer.
5. **Network TX**: `broadcast_packet()` sends position/airfields via UDP.
6. **Network RX**: `update_network_data()` handles incoming packets.
7. **Rendering**: `paintEvent()` draws overlay using cached data. `web_server.py` serves API to browser.
8. **Audio**: `SoundManager` plays warnings via `QSoundEffect` (low-latency, event-loop driven).

### Web Map Server (`web_server.py`)

The web map is a standalone Flask application that runs in a separate thread.

- **Architecture**:
    - **Flask App**: Serves `dashboard.html` and static assets.
    - **API Endpoint**: `/api/data` returns the current game state as JSON.
    - **Shared Data**: `main.py` updates a `shared_data` dictionary which the Flask server reads from in a background thread.
- **Planning Mode**: Users can click to place waypoints. These are sent via POST to `/api/waypoints`, picked up by `main.py`, and rendered on the overlay.
- **Compass Rose**: An SVG-based overlay in the browser that mimics the in-game compass, toggled via the toolbar.
 This ensures the web server never blocks the main overlay loop.

- **Key Functions**:
    - `update_shared_data(data)`: Called by `main.py` to push new telemetry.
    - `get_data()`: Route handler for `/api/data`.

### Web API Commands (`POST /api/command`)

The web client sends commands to the Python backend via JSON POST requests.

| Command Type | Action | Description |
|--------------|--------|-------------|
| `planning_update` | N/A | Updates the list of waypoints drawn on the map. |
| `set_formation` | `set_formation` | Toggles the formation status flag. |

These commands are placed in a queue (`SHARED_DATA['commands']`) and processed by `main.py` in the main thread loop (`process_web_commands`).

### Map Calibration (`auto_calibrate_new.py`)

The overlay requires precise alignment with the in-game map. We use OpenCV to automate this.

- **Trigger**: Hold **M** (activation key) and press **N**.
- **Logic**:
    1. **Screenshot**: Captures the screen.
    2. **Template Matching**: Uses `cv2.matchTemplate` to find the map grid on screen.
    3. **Math**: Calculates the exact `x, y` pixel offset and `width, height` of the map.
    4. **Apply**: Updates `CONFIG` dynamically without restarting.

### Network Protocol (UDP JSON)

**Player Position:**
```json
{"type": "player", "id": "192.168.1.5", "sender": "Callsign", "x": 0.5, "y": 0.3, "dx": 0.01, "dy": -0.005, "vehicle": "f_16c", ...}
```

**Airfield:**
```json
{"type": "airfield", "id": "AF1", "x": 0.2, "y": 0.4, "angle": 90, "len": 2500, "is_cv": false}
```

**POI:**
```json
{"type": "point_of_interest", "id": "POI1", "x": 0.6, "y": 0.7, "owner": "Callsign"}
```

**Team Chat:**
```json
{"type": "team_chat", "sender": "Pilot1", "message": "Attack D point!", "timestamp": 1234567890}
```

### Build Commands

We use a Python script to automate the release process, which builds the executable and packages it with necessary assets and a sanitized config.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Build and Package Release
python create_release.py
```

**`create_release.py` performs the following:**
1. Sanitizes `config.json` (removes personal callsign/colors).
2. Runs `PyInstaller` (if needed, otherwise looks for `dist/Link18.exe`).
3. Zips `Link18.exe`, `web/`, `sounds/`, `README.md`, and the sanitized config into `Link18_v1.6.0.zip`.

### Release Process Standards

We follow **[Semantic Versioning 2.0.0](https://semver.org/)**.

**1. Version Naming Convention**
Use the format: `Link18 vMAJOR.MINOR.PATCH` (e.g., `Link18 v1.3.0`).
*   **MAJOR**: Breaking changes (e.g., Network protocol incompatible with older clients, Config file structure changes).
*   **MINOR**: New features (backward compatible) (e.g., New vehicles, Web Map features).
*   **PATCH**: Bug fixes (backward compatible).

*   Do NOT use "Tactical Overlay" or other suffixes.
*   The Zip file should follow: `Link18_vX.Y.Z.zip`.

**2. Description Format**
Keep the release description basic. Specifically list **New Features** added in this version.

*Example:*
> **Link18 v1.3.0**
>
> **New Features:**
> *   Added Web Map Toolbar (Compass, Planning Mode).
> *   Added Auto-Calibration (M+N).
> *   Added Real Name vehicle translation.
>
> **Link18 v1.6.0**
>
> **New Features:**
> *   **System Tray Integration**: Controller now minimizes to tray to save screen space.
> *   **Controller Improvements**: Settings UI, Online Player List with Status, reordered layout.
> *   **Web Server Stability**: Fixes for Safari connection hangs and map proxy timeouts.

---

## LLM Agent Deep Dive


### Coordinate Systems

**CRITICAL**: All map coordinates use **normalized (0-1) range**, NOT pixels or meters.

| System | Range | Used In |
|--------|-------|---------|
| Normalized | `0.0` to `1.0` | Network packets, `self.airfields`, `self.players` |
| Screen Pixels | `0` to `1920/1080` | `paintEvent()` overlay rendering |
| World Meters | `-50000` to `50000` | War Thunder API raw data (converted immediately) |

### Vehicle Name Translation
Raw vehicle IDs (e.g., `f_16c_block_50`) are translated to human-readable names using `vehicles.json`.
- `main.py` loads this JSON on startup.
- If a translation isn't found, it falls back to the raw ID.

### State Management

**Key Instance Variables (OverlayWindow):**

| Variable | Type | Lifetime | Description |
|----------|------|----------|-------------|
| `self.players` | `dict` | Persistent | All players. Key: IP. |
| `self.airfields` | `list` | Per-update | Rebuilt every cycle from WT API. |
| `self.shared_airfields` | `dict` | 60s timeout | Network-received AFs. |
| `self.shared_pois` | `dict` | Persistent | Points of interest. |

**State Reset Points:**
- `self.airfields` → Rebuilt every frame.
- `self.shared_airfields` → Cleared if sender silent > 60s.
- `self.players['_local']` → Deleted if WT API returns error (hangar/closed).

### War Thunder API Endpoints (Localhost:8111)

| Endpoint | Data | Usage |
|----------|------|-------|
| `/map_obj.json` | Airfields, Units | Polled 100ms |
| `/map_info.json` | Map Bounds | Polled on map change |
| `/indicators` | Speed, Alt, Type | Polled 100ms |
| `/state` | Fuel, Ammo | Polled 100ms |
| `/gamechat` | Chat Msgs | Polled 2000ms |

### Network Packet Handling

**Self-Echo Prevention:**
To prevent "Ghost Players" (seeing yourself as another plane), packets are ignored if:
1. Sender IP matches `self.local_ips`.
2. `sender` field matches `callsign` in `config.json`.
