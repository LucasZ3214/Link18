"""
Link18 GBU HUD Mixin
Contains GBU/JDAM bomb tracking display methods.
Mixed into OverlayWindow via multiple inheritance.
"""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont, QFontMetrics

from config import CONFIG


class GbuHudMixin:
    """Mixin class providing GBU/JDAM HUD drawing logic."""

    def toggle_console(self):
        self.show_console = not self.show_console
        print(f"[UI] Console Output: {self.show_console}")
        self.update()

    def update_physics(self):
        """Update physics simulations (Off-load from paintEvent)"""
        if not getattr(self, 'show_gbu_timers', True):
            self.cached_predrop_text = None
            return
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
                self.cached_predrop_color = QColor(0, 255, 255)  # Cyan
                self.cached_predrop_mode = mode
            except Exception as e:
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
        if not getattr(self, 'show_gbu_timers', True):
            return
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

        bombs_per_col = 8
        cols = math.ceil(num_bombs / bombs_per_col)
        if cols < 1:
            cols = 1

        col_width = 270 if cols == 1 else 250
        w = (col_width * cols) + 10

        max_rows = bombs_per_col + 1
        num_visual_rows = num_bombs + 1 if cols == 1 else max_rows

        h = 10 + (num_visual_rows * 25)
        x = self.width() - w - 50
        y = 280

        # Background Box
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(0, 255, 0), 1))
        painter.drawRoundedRect(x, y, w, h, 5, 5)

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
            col = i // bombs_per_col
            row = (i % bombs_per_col) + 1

            mode_raw = b.get('mode', 'N/A')
            mode_short = shorthands.get(mode_raw, mode_raw[:1])

            bomb_id = str(b.get('id', i + 1))

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
        active_bombs = self.bomb_tracker.bombs
        if not active_bombs:
            return

        bomb = active_bombs[0]
        history = bomb.get('history', [])
        if not history:
            return

        g_w = 400
        g_h = 150
        g_x = 20
        g_y = 100

        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(g_x, g_y, g_w, g_h)

        target_dist = bomb['telem']['dist']
        launch_alt = bomb['telem']['alt']

        max_dist = target_dist * 1.1
        max_alt = launch_alt * 1.1

        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(g_x + 5, g_y + 15, f"{int(max_alt)}m")
        painter.drawText(g_x + g_w - 40, g_y + g_h - 5, f"{int(max_dist / 1000)}km")

        phase_colors = {
            "RELEASE": QColor(255, 255, 255),
            "BALLISTIC": QColor(200, 200, 200),
            "LOFT": QColor(0, 255, 255),
            "GLIDE": QColor(0, 255, 0),
            "GUIDANCE": QColor(255, 0, 255)
        }

        prev_pt = None
        for i in range(len(history)):
            pt_data = history[i]
            t, dist_x, alt_y, v = pt_data[0], pt_data[1], pt_data[2], pt_data[3]

            if max_dist == 0:
                continue
            sx = g_x + (dist_x / max_dist) * g_w
            sy = (g_y + g_h) - (alt_y / max_alt) * g_h
            current_pt = QPointF(sx, sy)

            if prev_pt:
                color = QColor(255, 255, 0)
                if len(pt_data) > 4:
                    phase = pt_data[4]
                    color = phase_colors.get(phase, color)

                painter.setPen(QPen(color, 2))
                painter.drawLine(prev_pt, current_pt)

            prev_pt = current_pt

        # Draw "Live" Bomb Position
        elapsed = time.time() - bomb['release_time']

        closest_pt = None
        for pt in history:
            if pt[0] >= elapsed:
                closest_pt = pt
                break

        if not closest_pt and history:
            closest_pt = history[-1]

        if closest_pt:
            t, dist_x, alt_y, v = closest_pt[0], closest_pt[1], closest_pt[2], closest_pt[3]
            sx = g_x + (dist_x / max_dist) * g_w
            sy = (g_y + g_h) - (alt_y / max_alt) * g_h

            painter.setBrush(QColor(255, 50, 50))
            painter.drawEllipse(QPointF(sx - 3, sy - 3), 6, 6)

            if len(closest_pt) > 6:
                phase = closest_pt[4]
                gamma = closest_pt[5]
                alpha = closest_pt[6]
                pitch = gamma + alpha

                vx_len = 25 * math.cos(-gamma)
                vy_len = 25 * math.sin(-gamma)
                painter.setPen(QPen(QColor(0, 255, 255), 1))
                painter.drawLine(int(sx), int(sy), int(sx + vx_len), int(sy + vy_len))

                bx_len = 20 * math.cos(-pitch)
                by_len = 20 * math.sin(-pitch)
                painter.setPen(QPen(QColor(255, 100, 100), 2))
                painter.drawLine(int(sx), int(sy), int(sx + bx_len), int(sy + by_len))

                painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(sx) + 10, int(sy) - 15, f"T-{closest_pt[0]:.1f}s | {phase}")
                painter.setFont(QFont("Consolas", 8))
                painter.drawText(int(sx) + 10, int(sy) - 2, f"M{v / 340:.2f} | AoA: {math.degrees(alpha):.1f}°")
                painter.drawText(int(sx) + 10, int(sy) + 10, f"Alt: {alt_y:.0f}m")
            else:
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(sx) + 10, int(sy), f"T+{t:.1f}s")

    def draw_attitude_diagram(self, painter, bomb):
        """Draws a detailed attitude indicator for the bomb"""
        history = bomb.get('history', [])
        if not history:
            return

        w = 200
        h = 200
        x = self.width() - w - 20
        y = self.height() - h - 20

        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawRect(x, y, w, h)

        cx = x + w / 2
        cy = y + h / 2

        elapsed = time.time() - bomb['release_time']
        closest_pt = None
        for pt in history:
            if pt[0] >= elapsed:
                closest_pt = pt
                break
        if not closest_pt and history:
            closest_pt = history[-1]

        if not closest_pt:
            return

        if len(closest_pt) > 6:
            t = closest_pt[0]
            v = closest_pt[3]
            phase = closest_pt[4]
            gamma = closest_pt[5]
            alpha = closest_pt[6]
            pitch = gamma + alpha

            painter.save()
            painter.translate(cx, cy)

            painter.setPen(QPen(QColor(100, 100, 100), 1, Qt.PenStyle.DashLine))
            painter.drawLine(-90, 0, 90, 0)

            pitch_deg = math.degrees(pitch)
            painter.rotate(-pitch_deg)

            painter.setPen(QPen(QColor(255, 255, 255), 3))
            painter.drawLine(-40, 0, 40, 0)
            painter.drawLine(-40, 0, -50, -10)
            painter.drawLine(-40, 0, -50, 10)

            alpha_deg = math.degrees(alpha)
            painter.rotate(alpha_deg)

            painter.setPen(QPen(QColor(0, 255, 255), 2))
            painter.drawLine(0, 0, 60, 0)
            painter.drawText(65, 5, "V")

            painter.restore()

            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255))

            painter.drawText(x + 10, y + 20, f"PHASE: {phase}")

            painter.setFont(QFont("Consolas", 9))
            painter.drawText(x + 10, y + 40, f"TIME: {t:.1f}s")
            painter.drawText(x + 10, y + 55, f"MACH: {v / 340:.2f}")
            painter.drawText(x + 10, y + 70, f"AoA : {math.degrees(alpha):.1f}°")
            painter.drawText(x + 10, y + 85, f"PITCH: {pitch_deg:.1f}°")

            bar_w = 15
            bar_h = 80
            bx = x + w - 25
            by = y + 40

            painter.setPen(QColor(100, 100, 100))
            painter.drawRect(bx, by, bar_w, bar_h)

            fill_h = (max(0, math.degrees(alpha)) / 22.0) * bar_h
            if fill_h > bar_h:
                fill_h = bar_h

            c = QColor(0, 255, 0)
            if math.degrees(alpha) > 10:
                c = QColor(255, 255, 0)
            if math.degrees(alpha) > 18:
                c = QColor(255, 0, 0)

            painter.setBrush(c)
            painter.drawRect(bx, by + bar_h - int(fill_h), bar_w, int(fill_h))
            painter.drawText(bx - 5, by + bar_h + 15, "AoA")

    def draw_console(self, painter):
        w = 400
        h = 250
        x = self.width() - w - 20
        y = 300

        painter.setBrush(QColor(0, 0, 0, 180))
        painter.setPen(QPen(QColor(255, 255, 255), 1))
        painter.drawRect(x, y, w, h)

        logs = self.bomb_tracker.get_logs()
        font = QFont("Consolas", 10)
        painter.setFont(font)
        painter.setPen(QColor(200, 200, 200))

        line_h = 15
        cur_y = y + 20

        for log in logs[-15:]:
            painter.drawText(x + 10, cur_y, log)
            cur_y += line_h
