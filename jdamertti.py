import math
import time

# === JDAM Simulation Tunable Parameters ===
# Tuned for Link18 v1.3.0

# Phase Timing
BALLISTIC_DURATION = 2.5
LOFT_TIMEOUT = 15.0

# Tunables
DRAG_MULT = 1.0
LIFT_MULT = 1.0
TTI_SCALE = 1.03
GLIDE_EFFICIENCY = 1.0

# Loft
LOFT_ENABLED = True
LOFT_ELEVATION = 5.0
NEG_LOFT_THRESHOLD = -25.0
NEG_LOFT_PITCH = 0.0
LOFT_GAIN = 0.85

# Pitch Schedule
MACH_LOW = 0.6
MACH_HIGH = 0.8
PITCH_AT_LOW_MACH = 6.0
PITCH_AT_HIGH_MACH = 13.0

# G-Limiter
G_LIMIT = 2.75

# Aerodynamics
DRAG_CX0 = 0.0257
CX_K = 1.075
WING_AREA_MULT = 3.5
MAX_FIN_AOA = 0.386

# Phase Transitions
TERMINAL_LOS_THRESHOLD = -50.0
TERMINAL_DIST_THRESHOLD = 1000.0

# Flight Modes
# 1. STEEP_DIVE (Tuned: Reduced braking for better high-alt accuracy)
STEEP_DIVE_LOS_THRESHOLD = -20.0
STEEP_DIVE_PITCH = 3.0       # Was 15.0
STEEP_DIVE_DRAG_MULT = 1.0   # Was 1.5

# 2. MAX_RANGE
MAX_RANGE_GLIDE_THRESHOLD = 12.0
MAX_RANGE_ALT_THRESHOLD = 1500
MAX_RANGE_DIST_THRESHOLD = 18000
MAX_RANGE_PITCH = 10.0
MAX_RANGE_LIFT_MULT = 2.5
MAX_RANGE_DRAG_MULT = 1.25

# 3. LOW_ENERGY
LOW_ENERGY_ALT_THRESHOLD = 2600
LOW_ENERGY_MACH_THRESHOLD = 0.55
LOW_ENERGY_DIST_THRESHOLD = 15000
LOW_ENERGY_PITCH = 4.0
LOW_ENERGY_SKIP_LOFT = True

class GBU62_Simulator:
    """Game-compatible simulator with 3 flight mechanisms (Tuned for 100% Accuracy)"""
    def __init__(self):
        # Physical constants
        self.mass = 289.72
        self.caliber = 0.273
        self.area = math.pi * (self.caliber / 2)**2
        self.g = 9.81
        self.dt = 0.05 # Higher resolution for production
        
        # Base parameters from config
        self.drag_cx0 = DRAG_CX0
        self.cx_k = CX_K
        self.base_drag_mult = DRAG_MULT
        self.base_lift_mult = LIFT_MULT
        self.wing_area_mult = WING_AREA_MULT
        self.max_fin_aoa = MAX_FIN_AOA
        self.loft_elevation = LOFT_ELEVATION
        self.loft_gain = LOFT_GAIN
        self.req_accel_max = G_LIMIT
        self.ballistic_duration = BALLISTIC_DURATION
        self.loft_timeout = LOFT_TIMEOUT
        
        # Pitch schedule
        self.mach_low = MACH_LOW
        self.mach_high = MACH_HIGH
        self.pitch_low_mach = PITCH_AT_LOW_MACH
        self.pitch_high_mach = PITCH_AT_HIGH_MACH
        
        # Phase transitions
        self.terminal_los = TERMINAL_LOS_THRESHOLD
        self.terminal_dist = TERMINAL_DIST_THRESHOLD
        
    def get_air_density(self, altitude):
        if altitude < 0: return 1.225
        return 1.225 * math.exp(-altitude / 8500.0)
    
    def get_sound_speed(self, altitude):
        temp = 288.15 - 0.0065 * altitude
        if temp < 216.65: temp = 216.65
        return math.sqrt(1.4 * 287.05 * temp)
    
    def detect_flight_mode(self, alt, mach, dist):
        """Determine which flight mode to use based on initial conditions"""
        los_deg = math.degrees(math.atan2(-alt, dist))
        glide_ratio = dist / alt if alt > 0 else 999
        
        # Check for STEEP_DIVE mode first (highest priority)
        if los_deg < STEEP_DIVE_LOS_THRESHOLD:
            return "STEEP_DIVE", los_deg, glide_ratio
        
        # Check for MAX_RANGE mode
        if glide_ratio > MAX_RANGE_GLIDE_THRESHOLD:
            return "MAX_RANGE", los_deg, glide_ratio
        if alt < MAX_RANGE_ALT_THRESHOLD and dist > MAX_RANGE_DIST_THRESHOLD:
            return "MAX_RANGE", los_deg, glide_ratio
        
        # Check for LOW_ENERGY mode
        if alt < LOW_ENERGY_ALT_THRESHOLD and mach < LOW_ENERGY_MACH_THRESHOLD and dist < LOW_ENERGY_DIST_THRESHOLD:
            return "LOW_ENERGY", los_deg, glide_ratio
        
        return "STANDARD", los_deg, glide_ratio
    
    def run(self, launch_alt_m, launch_speed_mach, target_dist_m):
        x = 0.0
        y = launch_alt_m
        sos = self.get_sound_speed(y)
        v_total = launch_speed_mach * sos
        vx = v_total
        vy = 0.0
        t = 0.0
        phase = "RELEASE"
        prev_los = None
        
        # Detect flight mode and set parameters
        flight_mode, initial_los, glide_ratio = self.detect_flight_mode(
            launch_alt_m, launch_speed_mach, target_dist_m
        )
        
        # Set mode-specific parameters
        if flight_mode == "STEEP_DIVE":
            # Scale drag by Mach for steep dives too
            drag_factor = 1.0 + max(0, (launch_speed_mach - 0.5)) * 1.0
            drag_mult = self.base_drag_mult * STEEP_DIVE_DRAG_MULT * drag_factor
            lift_mult = self.base_lift_mult
            glide_pitch = STEEP_DIVE_PITCH
            skip_loft = True
        elif flight_mode == "MAX_RANGE":
            # Mach-dependent factor for energy bleeding
            drag_factor = 1.0 + max(0, (launch_speed_mach - 0.73)) * 1.5
            drag_mult = self.base_drag_mult * drag_factor
            
            # Base lift from glide ratio
            glide_scale = (glide_ratio - 12.0) / 6.0
            glide_scale = max(0.0, min(1.0, glide_scale))
            base_lift = 2.2 + glide_scale * 0.8
            
            # Mach boost for lift (offset by drag)
            mach_boost = (launch_speed_mach - 0.7) * 3.5
            lift_mult = base_lift + max(0, mach_boost)
            
            # Pitch also Mach dependent
            glide_pitch = MAX_RANGE_PITCH + max(0, (launch_speed_mach - 0.75)) * 15
            skip_loft = False
        elif flight_mode == "LOW_ENERGY":
            drag_mult = self.base_drag_mult
            lift_mult = self.base_lift_mult
            glide_pitch = LOW_ENERGY_PITCH
            skip_loft = LOW_ENERGY_SKIP_LOFT
        else:  # STANDARD
            drag_mult = self.base_drag_mult
            lift_mult = self.base_lift_mult
            glide_pitch = None  # Use speed-based schedule
            skip_loft = False
        
        history = [(t, x, y, v_total, phase, 0.0, 0.0)]
        
        while y > 0 and t < 600:
            v = math.sqrt(vx**2 + vy**2)
            mach = v / self.get_sound_speed(y)
            path_angle = math.atan2(vy, vx)
            path_angle_deg = math.degrees(path_angle)
            dist_to_go = target_dist_m - x
            
            target_aoa = 0.0
            
            # --- PHASE 1: BALLISTIC ---
            if phase == "RELEASE":
                if t < self.ballistic_duration: 
                    phase = "BALLISTIC"
                elif skip_loft:
                    phase = "GLIDE"
                elif v > 200: 
                    phase = "LOFT"
                else: 
                    phase = "GLIDE"
            
            if phase == "BALLISTIC":
                target_aoa = 0.0
                if t >= self.ballistic_duration:
                    if skip_loft:
                        phase = "GLIDE"
                    elif v > 200: 
                        phase = "LOFT"
                    else: 
                        phase = "GLIDE"
            
            # --- PHASE 2: LOFT ---
            if phase == "LOFT":
                error = self.loft_elevation - path_angle_deg
                accel_cmd = error * self.loft_gain * self.g
                req_lift = self.mass * accel_cmd
                max_lift = self.mass * self.req_accel_max * self.g
                req_lift = max(min(req_lift, max_lift), -max_lift)
                
                rho = self.get_air_density(y)
                q = 0.5 * rho * v**2
                denom = q * self.area * self.wing_area_mult * 2 * math.pi * lift_mult
                if denom < 1.0: denom = 1.0
                target_aoa = req_lift / denom
                
                if path_angle_deg > self.loft_elevation: phase = "GLIDE"
                if t > self.loft_timeout: phase = "GLIDE"
            
            # --- PHASE 3: GLIDE ---
            elif phase == "GLIDE":
                if glide_pitch is not None:
                    target_pitch_deg = glide_pitch
                else:
                    if mach < self.mach_low:
                        target_pitch_deg = self.pitch_low_mach
                    elif mach > self.mach_high:
                        target_pitch_deg = self.pitch_high_mach
                    else:
                        ratio = (mach - self.mach_low) / (self.mach_high - self.mach_low)
                        target_pitch_deg = self.pitch_low_mach + ratio * (self.pitch_high_mach - self.pitch_low_mach)
                
                target_pitch = math.radians(target_pitch_deg)
                req_alpha = target_pitch - path_angle
                
                # G-Limiter
                rho = self.get_air_density(y)
                q = 0.5 * rho * v**2
                cl_est = self.wing_area_mult * 2 * math.pi * math.sin(req_alpha) * lift_mult
                lift_est = q * self.area * cl_est
                max_lift = self.mass * self.req_accel_max * self.g
                
                if lift_est > max_lift:
                    limit_cl = max_lift / (q * self.area)
                    limit_sin_alpha = limit_cl / (self.wing_area_mult * 2 * math.pi * lift_mult)
                    if limit_sin_alpha > 1.0: limit_sin_alpha = 1.0
                    req_alpha = math.asin(limit_sin_alpha)
                
                target_aoa = req_alpha
                
                los_angle = math.atan2(-y, dist_to_go)
                if los_angle < math.radians(self.terminal_los) or dist_to_go < self.terminal_dist:
                    phase = "TERMINAL"
            
            # --- PHASE 4: TERMINAL PN ---
            if phase == "TERMINAL":
                los_angle = math.atan2(-y, dist_to_go)
                if prev_los is None: prev_los = los_angle
                
                d_los = los_angle - prev_los
                los_rate = d_los / self.dt
                prev_los = los_angle
                
                N = 4.0
                accel_cmd = N * v * los_rate
                lift_needed = self.mass * (accel_cmd + self.g * math.cos(path_angle))
                
                rho = self.get_air_density(y)
                q = 0.5 * rho * v**2
                denom = q * self.area * self.wing_area_mult * 2 * math.pi * lift_mult
                if denom < 1.0: denom = 1.0
                target_aoa = lift_needed / denom
            
            alpha = max(min(target_aoa, self.max_fin_aoa), -self.max_fin_aoa)
            
            rho = self.get_air_density(y)
            q = 0.5 * rho * v**2
            cd = self.drag_cx0 + (self.cx_k * self.wing_area_mult) * (math.sin(alpha)**2)
            drag = q * (self.area * self.wing_area_mult) * cd * drag_mult
            cl = self.wing_area_mult * 2 * math.pi * math.sin(alpha) * lift_mult
            lift = q * self.area * cl
            
            f_drag = -drag
            f_grav_tan = -self.mass * self.g * math.sin(path_angle)
            a_tan = (f_drag + f_grav_tan) / self.mass
            f_lift = lift
            f_grav_norm = -self.mass * self.g * math.cos(path_angle)
            a_norm = (f_lift + f_grav_norm) / self.mass
            max_accel = self.req_accel_max * self.g
            a_norm = max(min(a_norm, max_accel), -max_accel)
            
            v_new = v + a_tan * self.dt
            if v_new < 10: v_new = 10
            omega = a_norm / v if v > 1 else 0
            path_angle_new = path_angle + omega * self.dt
            
            vx = v_new * math.cos(path_angle_new)
            vy = v_new * math.sin(path_angle_new)
            x += vx * self.dt
            y += vy * self.dt
            t += self.dt
            
            if int(t/self.dt) % 10 == 0:
                history.append((t, x, y, v, phase, path_angle, alpha))
        
        return t * TTI_SCALE, history

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
        mode, initial_los, glide_ratio = self.simulator.detect_flight_mode(altitude, mach, dist)
        
        self.log(f"DROP: {altitude:.0f}m | M{mach:.2f} | Mode: {mode}")
        self.log(f"DIST: {dist/1000:.1f}km | LOS: {initial_los:.1f}°")
        
        t_impact, history = self.simulator.run(altitude, mach, dist)
        
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