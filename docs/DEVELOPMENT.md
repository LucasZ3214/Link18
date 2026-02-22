# Link18 Developer Documentation

## Project Structure

```
Link18/
├── main.py              # Entry point: Initializes app, tray, and server threads
├── overlay.py           # Core Logic: Central class combining all mixins/states
├── config.py / .json    # Configuration: Dynamic settings and fallback values
├── rendering.py         # Drawing: RenderingMixin for map and HUD elements
├── gbu_hud.py           # Simulation: GbuHudMixin for bomb tracking display
├── network.py           # Connectivity: TelemetryFetcher and UDP networking
├── web_server.py        # Dashboard: Standalone server for web map API
├── jdamertti.py         # Physics: GBU-62 simulation engine
├── ui.py                # UI Components: Custom widgets and trays
├── key_monitor.py       # Input: Global keyboard shortcuts
├── vws.py               # Audio: Voice Warning System alerts
├── auto_calibrate_new.py# Calibration: OpenCV-based map alignment
├── vehicles.json        # Translation: Vehicle ID to real name map
├── Link18.spec          # Build: PyInstaller specification
└── requirements.txt     # Deps: Python dependencies
```

### JDAM Simulation Architecture (`jdamertti.py`)

The GBU-62/JDAM-ER simulation is a self-contained engine:
- **Physics**: Implements 3-DOF kinematics with drag/lift modulation.
- **Modes**:
    - **Steep Dive**: High-drag/high-AOA mode for short-range drops.
    - **Max Range**: Glide-optimization mode for long-distance strikes.
    - **Standard**: Balanced profile.
- **Integration**: `overlay.py` instantiates `BombTracker` (from `jdamertti.py`) which manages multiple `GBU62_Simulator` instances.
- **Tuning**: All physics constants are defined at the top of `jdamertti.py`.


### Architecture Overview

```
┌─────────────────┐     UDP Broadcast      ┌─────────────────┐
│  Overlay Core   │◄─────────────────────► │  Other Players  │
│  (overlay.py)   │      Port 50050        │                 │
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

### Key Classes and Mixins

The application uses a Mixin-based architecture to separate concerns while maintaining a single cohesive `OverlayWindow`.

| Module | Class/Mixin | Purpose |
|--------|-------------|---------|
| `overlay.py` | `OverlayWindow` | Central orchestrator. Manages state, life-cycle, and coordination. |
| `rendering.py` | `RenderingMixin` | Specialized UI drawing (Map, Players, Scale, POIs). |
| `gbu_hud.py` | `GbuHudMixin` | Specialized UI drawing for bomb simulations. |
| `network.py` | `TelemetryFetcher` | Background thread for WT HTTP polling. |
| `network.py` | `NetworkReceiver` | UDP listener thread for squad coordination data. |
| `key_monitor.py` | `KeyMonitor` | Global keyboard listener for shortcuts. |
| `ui.py` | `TrayController` | System tray integration and application management. |

### Voice Warning System (`vws.py`)

The VWS module provides audio alerts for threats:
- **SoundManager**: Manages loading/playing `.wav` files and synthesized tones.
- **Synthesized Fallback**: When `enable_vws` is `false`, generates sine-wave tones.
- **Normalization**: Optional loudness normalization to -0.2dB headroom.
- **Startup Tone**: Procedurally generated ascending fourths chime.

### Data Flow

1. **Initialization**: `main.py` loads config, starts the tray icon, and instantiates `OverlayWindow`.
2. **Telemetry Fetch**: `TelemetryFetcher` (background) polls WT API every 100ms.
3. **Data Processing**: `OverlayWindow.on_telemetry_data()` processes data, updates simulations, and syncs to `SHARED_DATA`.
4. **Map Sync**: Map bounds are updated dynamically on map change.
5. **Physics**: `GbuHudMixin.update_physics()` runs bomb simulations at 10Hz.
6. **Network TX**: `OverlayWindow` broadcasts position/airfields via UDP sockets.
7. **Network RX**: `NetworkReceiver` pushes data back to `OverlayWindow.update_network_data()`.
8. **Rendering**: `OverlayWindow.paintEvent()` delegates to mixin draw methods.
9. **Web Sync**: Web server reads from `SHARED_DATA` to update the dashboard.

### Web Map Server (`web_server.py`)

The web map is a standalone Flask application that runs in a separate thread.

- **Architecture**:
    - **Flask App**: Serves `dashboard.html` and static assets.
    - **API Endpoint**: `/api/data` returns the current game state as JSON.
    - **Shared Data**: `overlay.py` updates the `SHARED_DATA` dictionary (in `web_server.py`) which the server reads from.
- **Planning Mode**: Users can click to place waypoints. These are queued and processed by `overlay.py`.
- **Compass Rose**: An SVG-based overlay in the browser that mimics the in-game compass, toggled via the toolbar.
 This ensures the web server never blocks the main overlay loop.

- **Key Functions**:
    - `update_shared_data(data)`: Called by `overlay.py` to push new telemetry.
    - `get_data()`: Route handler for `/api/data`.

### Web API Commands (`POST /api/command`)

The web client sends commands to the Python backend via JSON POST requests.

| Command Type | Action | Description |
|--------------|--------|-------------|
| `planning_update` | N/A | Updates the list of waypoints drawn on the map. |
| `set_formation` | `set_formation` | Toggles the formation status flag. |

These commands are placed in a queue (`SHARED_DATA['commands']`) and processed by `overlay.py` in its primary interval loop (`process_web_commands`).

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
- `overlay.py` loads this JSON on startup.
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
| `/hudmsg` | Destruction Events | Polled ~40ms (Main Thread) |

### Network Packet Handling

**Self-Echo Prevention:**
To prevent "Ghost Players" (seeing yourself as another plane), packets are ignored if:
1. Sender IP matches `self.local_ips`.
2. `sender` field matches `callsign` in `config.json`.
