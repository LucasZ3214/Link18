import math
import time

# === JDAM Simulation Physics Engine ===
# Refactored for ±1s Precision (v1.5.0)

# Physics Constants
# Physics Constants
BALLISTIC_DURATION = 2.5
LOFT_TIMEOUT = 10.0      # Reduced for better energy management
TTI_SCALE = 1.349        # Tuned v1.9

# Unified Aerodynamic Constants (Manual Tuned v1.9.5)
# Flattening envelope: Lower K (fix slow drift), Higher CD0 (fix fast float)
CD0_BASE = 0.036
K_INDUCED = 0.015
CL_ALPHA = 1.5
WING_AREA_MULT = 5.7262
MAX_FIN_AOA = 0.5 

# === WAVE DRAG MODEL ===
# Transonic drag rise parameters
MACH_CRITICAL = 1.289
MACH_PEAK = 1.6
DRAG_RISE_MAGNITUDE = 3.2

def get_mach_drag_mult(mach):
    """Calculates wave drag multiplier based on Mach number"""
    if mach < MACH_CRITICAL:
        return 1.0
    elif mach < MACH_PEAK:
        # Logistic or Sine/Cosine rise to peak
        # Normalized position in drag rise region
        ratio = (mach - MACH_CRITICAL) / (MACH_PEAK - MACH_CRITICAL)
        return 1.0 + DRAG_RISE_MAGNITUDE * math.sin(ratio * math.pi / 2)**2
    else:
        # Decay after peak? Or stay constant?
        # Simple model: constant after peak or slow decay
        return 1.0 + DRAG_RISE_MAGNITUDE

# Pitch Schedule (Control Policy)
# This determines the guidance target, but physics remains unified.
MACH_LOW = 0.6
MACH_HIGH = 0.95
PITCH_LOW = 11.49
PITCH_HIGH = 8.25
PITCH_DIVE = 15.68

# Phase Transitions
TERMINAL_LOS_THRESHOLD = -19.04
TERMINAL_DIST_THRESHOLD = 2000
LOFT_ELEVATION = 35.0
LOFT_GAIN = 0.5
G_LIMIT = 2.75
# Flight Mode Selection Logic (Guidance Only)
STEEP_DIVE_LOS = -19.04
MAX_RANGE_GLIDE = 13.23 # glide_thresh

# === MODE-SPECIFIC PHYSICS (Hybrid Architecture v3.0) ===
PHYSICS_PROFILES = {
    'STANDARD': {
        # Legacy v1.5 Model: Matching Lift/Drag of Old Model
        'CD0': 0.0157, 'K': 0.155, 'CL_ALPHA': 3.85, 
        'DRAG_MULT': 1.0, 'LIFT_MULT': 1.0, 
        'P_LOW': 6.0, 'P_HIGH': 13.0, 'TIME_SCALE': 1.03,
        'M_LOW': 0.6, 'M_HIGH': 0.8,  # v1.5 Values
        'MAX_AOA': 0.386, # v1.5 Limit (22 deg)
        'SOLVER': 'EULER', # Legacy Integration
        'LOFT_ELEV': 5.0, 'LOFT_GAIN': 0.85, # v1.5 Loft
        'TERM_LOS': -50.0 # v1.5 Terminal
    },
    'MAX_RANGE': {
        # Tuned v1.9.5: Low Drag, High Scale (1.35)
        'CD0': 0.036, 'K': 0.015, 'CL_ALPHA': 1.5, 
        'DRAG_MULT': 0.553, 'LIFT_MULT': 0.839,
        'P_LOW': 11.49, 'P_HIGH': 8.25, 'TIME_SCALE': 1.349,
        'M_LOW': 0.6, 'M_HIGH': 0.95, # v1.9 Values
        'MAX_AOA': 0.5,
        'SOLVER': 'RK4',
        'LOFT_ELEV': 35.0, 'LOFT_GAIN': 0.5, # v1.9 Loft
        'TERM_LOS': -19.04 # v1.9 Terminal
    },
    'STEEP_DIVE': {
        # Tuned v1.9.5: High Drag, High Scale (1.35)
        'CD0': 0.036, 'K': 0.015, 'CL_ALPHA': 1.5, 
        'DRAG_MULT': 4.471, 'LIFT_MULT': 0.868,
        'P_LOW': 11.49, 'P_HIGH': 8.25, 'TIME_SCALE': 1.05,
        'M_LOW': 0.6, 'M_HIGH': 0.95, # v1.9 Values 
        'MAX_AOA': 0.5,
        'SOLVER': 'RK4',
        'LOFT_ELEV': 35.0, 'LOFT_GAIN': 0.5, # v1.9 Loft
        'TERM_LOS': -19.04 # v1.9 Terminal
    }
}

class GBU62_Simulator:
    """Precision GBU-62/JDAM-ER Simulator"""
    def __init__(self, dt=0.05):
        self.mass = 289.72
        self.caliber = 0.273
        self.area = math.pi * (self.caliber / 2)**2
        self.g = 9.81
        self.dt = dt
        self.current_physics = PHYSICS_PROFILES['STANDARD'] # Default
        
    def get_air_density(self, altitude):
        if altitude < 0: return 1.225
        return 1.225 * math.exp(-altitude / 8500.0)
    
    def get_sound_speed(self, altitude):
        temp = 288.15 - 0.0065 * altitude
        if temp < 216.65: temp = 216.65
        return math.sqrt(1.4 * 287.05 * temp)
    
    def detect_flight_mode(self, alt, mach, dist):
        """Determine which guidance logic to use"""
        los_deg = math.degrees(math.atan2(-alt, dist))
        glide_ratio = dist / alt if alt > 0 else 999
        
        if los_deg < STEEP_DIVE_LOS:
            return "STEEP_DIVE"
        if glide_ratio > MAX_RANGE_GLIDE:
            return "MAX_RANGE"
        return "STANDARD"
    
        # Forces resolved to Global Frame
        # Drag is opposite to velocity: (-cos, -sin)
        # Lift is perpendicular to velocity: (-sin, +cos) -> Standard lift vector rotation
        sin_g = math.sin(path_angle)
        cos_g = math.cos(path_angle)
        
        fx_drag = -drag * cos_g
        fy_drag = -drag * sin_g
        
        fx_lift = -lift * sin_g
        fy_lift = lift * cos_g
        
        # G-Limiter proxy (structural limit on lift force)
        # We limit the lift force magnitude directly? 
        # Or just let it ride. The legacy code limited a_norm.
        # Let's apply a G-limit to the Lift magnitude if needed, but for RK4 physics 
        # it's better to limit the Alpha input (which we did).
        
        fx = fx_drag + fx_lift
        fy = fy_drag + fy_lift - (self.mass * self.g)
        
        ax = fx / self.mass
        ay = fy / self.mass
        
        return [vx, vy, ax, ay]

    def compute_derivatives(self, state, target_aoa):
        """Compute time derivatives for RK4 solver"""
        x, y, vx, vy = state
        
        v = math.sqrt(vx**2 + vy**2)
        if v < 1.0: v = 1.0 # Prevent div/0
        
        path_angle = math.atan2(vy, vx)
        
        # Physics Environment
        rho = self.get_air_density(y)
        sos = self.get_sound_speed(y)
        mach = v / sos
        q = 0.5 * rho * v**2
        
        # Use Mode-Specific Physics
        params = getattr(self, 'current_physics', PHYSICS_PROFILES['STANDARD'])

        # Aerodynamics
        max_aoa = params.get('MAX_AOA', MAX_FIN_AOA)
        alpha = max(min(target_aoa, max_aoa), -max_aoa)
        
        mach_mult = get_mach_drag_mult(mach)
        
        cl = params['CL_ALPHA'] * alpha
        cd = (params['CD0'] * mach_mult) + params['K'] * (cl**2)
        
        # Drag/Lift Multipliers (Tuning Knobs)
        drag_mult = params.get('DRAG_MULT', 1.0)
        lift_mult = params.get('LIFT_MULT', 1.0)
        
        drag = q * self.area * WING_AREA_MULT * cd * drag_mult
        lift = q * self.area * WING_AREA_MULT * cl * lift_mult
        
        # Forces resolved to Global Frame
        # Drag is opposite to velocity: (-cos, -sin)
        # Lift is perpendicular to velocity: (-sin, +cos) -> Standard lift vector rotation
        sin_g = math.sin(path_angle)
        cos_g = math.cos(path_angle)
        
        fx_drag = -drag * cos_g
        fy_drag = -drag * sin_g
        
        fx_lift = -lift * sin_g
        fy_lift = lift * cos_g
        
        # G-Limiter proxy (structural limit on lift force)
        # We limit the lift force magnitude directly? 
        # Or just let it ride. The legacy code limited a_norm.
        # Let's apply a G-limit to the Lift magnitude if needed, but for RK4 physics 
        # it's better to limit the Alpha input (which we did).
        
        fx = fx_drag + fx_lift
        fy = fy_drag + fy_lift - (self.mass * self.g)
        
        ax = fx / self.mass
        ay = fy / self.mass
        
        return [vx, vy, ax, ay]

    def rk4_step(self, t, state, dt, target_aoa):
        """Runge-Kutta 4 integration step"""
        k1 = self.compute_derivatives(state, target_aoa)
        
        s2 = [s + k * 0.5 * dt for s, k in zip(state, k1)]
        k2 = self.compute_derivatives(s2, target_aoa)
        
        s3 = [s + k * 0.5 * dt for s, k in zip(state, k2)]
        k3 = self.compute_derivatives(s3, target_aoa)
        
        s4 = [s + k * dt for s, k in zip(state, k3)]
        k4 = self.compute_derivatives(s4, target_aoa)
        
        new_state = []
        for i in range(4):
            val = state[i] + (dt / 6.0) * (k1[i] + 2*k2[i] + 2*k3[i] + k4[i])
            new_state.append(val)
            
        return new_state

    def euler_step(self, t, state, dt, target_aoa):
        """Legacy Euler integration (v1.5) for matching flight characteristics"""
        x, y, vx, vy = state
        v = math.sqrt(vx**2 + vy**2)
        path_angle = math.atan2(vy, vx)
        
        # Physics Environment
        rho = self.get_air_density(y)
        sos = self.get_sound_speed(y)
        mach = v / sos
        q = 0.5 * rho * v**2
        
        if self.current_physics == PHYSICS_PROFILES['STANDARD']:
             # Force Legacy Parameters for Exact Replication of v1.5.0
             WA_MULT = 3.5
             CX0 = 0.0257
             CX_K = 1.075
             MAX_AOA = 0.386
             alpha = max(min(target_aoa, MAX_AOA), -MAX_AOA)
             
             # v1.5 Lift Model: cl = mult * 2pi * sin(a)
             cl = WA_MULT * (2 * math.pi) * math.sin(alpha)
             lift = q * self.area * cl
             
             # v1.5 Drag Model: cd = cx0 + (k * mult) * sin^2(a)
             cd_local = CX0 + (CX_K * WA_MULT) * (math.sin(alpha)**2)
             drag = q * (self.area * WA_MULT) * cd_local
        else:
             # Fallback to Profile logic if euler used elsewhere
             params = getattr(self, 'current_physics', PHYSICS_PROFILES['STANDARD'])
             max_aoa = params.get('MAX_AOA', MAX_FIN_AOA)
             alpha = max(min(target_aoa, max_aoa), -max_aoa)
             mach_mult = get_mach_drag_mult(mach)
             cl = params['CL_ALPHA'] * alpha
             cd = (params['CD0'] * mach_mult) + params['K'] * (cl**2)
             drag_mult = params.get('DRAG_MULT', 1.0)
             lift_mult = params.get('LIFT_MULT', 1.0)
             drag = q * self.area * WING_AREA_MULT * cd * drag_mult
             lift = q * self.area * WING_AREA_MULT * cl * lift_mult
        
        # Polar Euler Integration
        f_drag = -drag
        f_grav_tan = -self.mass * self.g * math.sin(path_angle)
        a_tan = (f_drag + f_grav_tan) / self.mass
        
        f_lift = lift
        f_grav_norm = -self.mass * self.g * math.cos(path_angle)
        a_norm = (f_lift + f_grav_norm) / self.mass
        max_accel = G_LIMIT * self.g
        a_norm = max(min(a_norm, max_accel), -max_accel)
        
        v_new = v + a_tan * dt
        if v_new < 10: v_new = 10
        omega = a_norm / v if v > 1 else 0
        path_angle_new = path_angle + omega * dt
        
        vx_new = v_new * math.cos(path_angle_new)
        vy_new = v_new * math.sin(path_angle_new)
        x_new = x + vx_new * dt
        y_new = y + vy_new * dt
        
        return [x_new, y_new, vx_new, vy_new]

    def run(self, launch_alt_m, launch_speed_mach, target_dist_m):
        # Initial State
        sos = self.get_sound_speed(launch_alt_m)
        v_total = launch_speed_mach * sos
        # State: [x, y, vx, vy]
        state = [0.0, launch_alt_m, v_total, 0.0]
        
        t = 0.0
        phase = "RELEASE"
        prev_los = None
        
        # Determine guidance mode
        mode = self.detect_flight_mode(launch_alt_m, launch_speed_mach, target_dist_m)
        skip_loft = (mode == "STEEP_DIVE")
        
        # apply physics profile
        if mode in PHYSICS_PROFILES:
            self.current_physics = PHYSICS_PROFILES[mode]
        else:
            self.current_physics = PHYSICS_PROFILES['STANDARD']

        # Extract Profile-Specific Control Parameters
        p_low = self.current_physics.get('P_LOW', PITCH_LOW)
        p_high = self.current_physics.get('P_HIGH', PITCH_HIGH)
        m_low = self.current_physics.get('M_LOW', MACH_LOW)
        m_high = self.current_physics.get('M_HIGH', MACH_HIGH)
        time_scale = self.current_physics.get('TIME_SCALE', TTI_SCALE)
        
        loft_elev = self.current_physics.get('LOFT_ELEV', LOFT_ELEVATION)
        loft_gain = self.current_physics.get('LOFT_GAIN', LOFT_GAIN)
        term_los = self.current_physics.get('TERM_LOS', TERMINAL_LOS_THRESHOLD)

        history = []
        
        while state[1] > 0 and t < 600:
            # Derived variables for guidance
            vx, vy = state[2], state[3]
            v = math.sqrt(vx**2 + vy**2)
            path_angle = math.atan2(vy, vx)
            path_angle_deg = math.degrees(path_angle)
            
            # Current Mach/Alt for lookup
            curr_sos = self.get_sound_speed(state[1])
            mach = v / curr_sos
            dist_to_go = target_dist_m - state[0]
            
            # --- GUIDANCE LOGIC (Updates Phase & Target AoA) ---
            target_aoa = 0.0
            
            if phase == "RELEASE":
                phase = "BALLISTIC"
            
            if phase == "BALLISTIC":
                target_aoa = 0.0
                if t >= BALLISTIC_DURATION:
                    phase = "GLIDE" if skip_loft else "LOFT"
            
            elif phase == "LOFT":
                error = loft_elev - path_angle_deg
                # Non-linear gain to prevent overshoot? Standard P-control
                accel_cmd = error * loft_gain * self.g
                
                # Inverse Dynamics to find required AoA for this accel
                rho = self.get_air_density(state[1])
                q = 0.5 * rho * v**2
                req_lift = self.mass * accel_cmd
                cl_needed = req_lift / (q * self.area * WING_AREA_MULT)
                target_aoa = cl_needed / CL_ALPHA
                
                if path_angle_deg > loft_elev or t > LOFT_TIMEOUT: 
                    phase = "GLIDE"
            
            elif phase == "GLIDE":
                if mode == "STEEP_DIVE":
                   target_pitch_deg = PITCH_DIVE
                elif mode == "MAX_RANGE":
                    target_pitch_deg = PITCH_HIGH if mach > MACH_HIGH else PITCH_LOW
                else:
                    if mach < m_low: target_pitch_deg = p_low
                    elif mach > m_high: target_pitch_deg = p_high
                    else:
                        ratio = (mach - m_low) / (m_high - m_low)
                        target_pitch_deg = p_low + ratio*(p_high - p_low)
                
                # Guidance output is Target PITCH, so AoA = Pitch - Gamma
                target_aoa = math.radians(target_pitch_deg) - path_angle
                
                # Transition to Terminal
                los_angle = math.atan2(-state[1], dist_to_go)
                if los_angle < math.radians(term_los) or dist_to_go < TERMINAL_DIST_THRESHOLD:
                    phase = "TERMINAL"
            
            elif phase == "TERMINAL":
                los_angle = math.atan2(-state[1], dist_to_go)
                if prev_los is None: prev_los = los_angle
                los_rate = (los_angle - prev_los) / self.dt
                prev_los = los_angle
                
                # Proportional Navigation (N=4)
                accel_cmd = 4.0 * v * los_rate 
                # Compensate for gravity to maintain pure PN? 
                # Or just demand lateral accel.
                # Lift must support gravity AND provide turn accel
                lift_needed = self.mass * (accel_cmd + self.g * math.cos(path_angle))
                
                rho = self.get_air_density(state[1])
                q = 0.5 * rho * v**2
                cl_needed = lift_needed / (q * self.area * WING_AREA_MULT)
                target_aoa = cl_needed / CL_ALPHA
            
            # --- INTEGRATION STEP ---
            # --- INTEGRATION STEP ---
            solver_type = self.current_physics.get('SOLVER', 'RK4')
            if solver_type == 'EULER':
                state = self.euler_step(t, state, self.dt, target_aoa)
            else:
                state = self.rk4_step(t, state, self.dt, target_aoa)
            t += self.dt
            
            if int(t/self.dt) % 10 == 0:
                 # Reconstruct alpha for logging
                 path_angle_curr = math.atan2(state[3], state[2])
                 # Use global constant or profile specific
                 params = getattr(self, 'current_physics', PHYSICS_PROFILES['STANDARD'])
                 max_aoa = params.get('MAX_AOA', MAX_FIN_AOA)
                 alpha = max(min(target_aoa, max_aoa), -max_aoa)
                 # Time, Dist, Alt, Speed, Phase, PathAngle, AoA
                 history.append((t, state[0], state[1], v, phase, path_angle_curr, alpha))
        
        return t * time_scale, state[0], history

class BombTracker:
    def __init__(self):
        self.bombs = []
        self.bomb_counter = 0
        self.log_messages = []
        self.simulator = GBU62_Simulator()

    def log(self, message):
        """Add message to internal log"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_messages.append(f"[{timestamp}] {message}")
        if len(self.log_messages) > 20:
            self.log_messages.pop(0)
        print(f"[JDAM] {message}")

    def add_bomb(self, altitude, speed_tas, pitch_deg, ground_speed=0, target_distance=None):
        """Record and simulate a bomb drop"""
        self.bomb_counter += 1
        
        sos = self.simulator.get_sound_speed(altitude)
        mach = (speed_tas / 3.6) / sos
        dist = target_distance if target_distance else 15000.0
        
        # Detect mode for logging
        mode = self.simulator.detect_flight_mode(altitude, mach, dist)
        
        self.log(f"DROP: {altitude:.0f}m | M{mach:.2f} | Mode: {mode}")
        self.log(f"DIST: {dist/1000:.1f}km")
        
        t_impact, x_final, history = self.simulator.run(altitude, mach, dist)
        
        now = time.time()
        bomb = {
            'id': self.bomb_counter,
            'release_time': now,
            'total_tti': t_impact,
            'impact_time': now + t_impact,
            'telem': {'alt': altitude, 'tas': speed_tas, 'pitch': pitch_deg, 'dist': dist},
            'history': history,
            'mode': mode,
            'label': f"GBU-{self.bomb_counter}"
        }
        self.bombs.append(bomb)
        self.log(f"RELEASED! TTI: {t_impact:.1f}s")

    def update(self):
        """Prune exploded bombs"""
        now = time.time()
        self.bombs = [b for b in self.bombs if now < b['impact_time'] + 5.0]

    def get_active_bombs(self):
        """Return list of bombs with updated remaining time"""
        outputs = []
        now = time.time()
        for b in self.bombs:
            remaining = b['impact_time'] - now
            status = "FLYING" if remaining > 0 else "IMPACT"
            outputs.append({
                'id': b['id'],
                'remaining': remaining,
                'status': status,
                'label': b['label'],
                'mode': b.get('mode', 'N/A'),
                'total_tti': b.get('total_tti', 0.0)
            })
        return outputs

    def get_logs(self):
        return self.log_messages