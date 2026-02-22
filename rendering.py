"""
Link18 Rendering Mixin
Contains paintEvent, draw_compass_rose, and draw_formation_panel methods.
Mixed into OverlayWindow via multiple inheritance.
"""
import math
import time

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QFontMetrics,
    QPolygonF, QPainterPath
)

from config import CONFIG, DEBUG_MODE


class RenderingMixin:
    """Mixin class providing all painting/drawing logic for the overlay."""

    def draw_compass_rose(self, painter, x, y, radius, heading_rad, others=None, local_player=None):
        if others is None:
            others = []

        # Clip drawing to the Compass Circle to contain Waypoint Lines
        painter.save()
        clip_path = QPainterPath()
        clip_path.addEllipse(QPointF(x, y), radius, radius)
        painter.setClipPath(clip_path)

        heading_deg = math.degrees(heading_rad)

        # Draw Planning Lines (Bottom Layer)
        if self.planning_waypoints and local_player and self.map_min and self.map_max:
            p_x = local_player.get('x', 0)
            p_y = local_player.get('y', 0)

            m_min = self.map_min
            m_max = self.map_max

            world_w = m_max[0] - m_min[0]
            world_h = m_max[1] - m_min[1]

            disp_range_m = 50000
            scale = radius / disp_range_m

            painter.setPen(QPen(QColor('#00FFFF'), 2))

            pts_screen = []

            for wp in self.planning_waypoints:
                dx_norm = wp['x'] - p_x
                dy_norm = wp['y'] - p_y

                dx_m = dx_norm * world_w
                dy_m = dy_norm * world_h

                bearing_rad_wp = math.atan2(dy_m, dx_m)
                bearing_deg_wp = math.degrees(bearing_rad_wp)
                screen_angle_deg = bearing_deg_wp - heading_deg - 90
                screen_angle = math.radians(screen_angle_deg)

                dist_m = math.hypot(dx_m, dy_m)
                r_px = dist_m * scale

                sx = x + math.cos(screen_angle) * r_px
                sy = y + math.sin(screen_angle) * r_px

                pts_screen.append(QPointF(sx, sy))

            if len(pts_screen) > 1:
                path = QPainterPath()
                path.moveTo(pts_screen[0])
                for i in range(1, len(pts_screen)):
                    path.lineTo(pts_screen[i])
                painter.drawPath(path)

            painter.setBrush(QColor('#00FFFF'))
            painter.setPen(Qt.PenStyle.NoPen)
            for pt in pts_screen:
                painter.drawEllipse(pt, 3, 3)

        painter.restore()  # End Clipping

        heading_deg = math.degrees(heading_rad)

        # PRE-CALCULATE TICKS
        ticks = []
        for i in range(0, 360, 15):
            screen_angle_deg = (i - 90) - heading_deg - 90
            rad = math.radians(screen_angle_deg)

            is_cardinal = (i % 90 == 0)
            is_inter = (i % 45 == 0)

            if is_cardinal:
                tick_len = 10
                tick_width = 3.0
                outline_inc = 2.5
                color = QColor(255, 255, 255, 255)
                label_text = ""
                if i == 0: label_text = "N"
                elif i == 90: label_text = "E"
                elif i == 180: label_text = "S"
                elif i == 270: label_text = "W"

            elif is_inter:
                tick_len = 8
                tick_width = 2.5
                outline_inc = 2.5
                color = QColor(255, 255, 255, 230)
                label_text = ""
                if i == 45: label_text = "NE"
                elif i == 135: label_text = "SE"
                elif i == 225: label_text = "SW"
                elif i == 315: label_text = "NW"

            else:
                tick_len = 5
                tick_width = 1.5
                outline_inc = 1.5
                color = QColor(255, 255, 255, 150)
                label_text = ""

            p1_x = x + math.cos(rad) * (radius - tick_len)
            p1_y = y + math.sin(rad) * (radius - tick_len)
            p2_x = x + math.cos(rad) * (radius + tick_len)
            p2_y = y + math.sin(rad) * (radius + tick_len)

            ticks.append({
                'p1': QPointF(p1_x, p1_y),
                'p2': QPointF(p2_x, p2_y),
                'width': tick_width,
                'outline_w': tick_width + outline_inc,
                'color': color,
                'label': label_text,
                'rad': rad
            })

        # Add POI Ticks
        for item in others:
            if item.get('type') == 'poi':
                bearing = item.get('bearing', 0)
                color = item.get('color', QColor(255, 255, 0))

                bearing_deg_item = math.degrees(bearing)
                screen_angle_deg = bearing_deg_item - heading_deg - 90
                rad = math.radians(screen_angle_deg)

                tick_len = 10
                tick_width = 3.0
                outline_inc = 2.5

                p1_x = x + math.cos(rad) * (radius - tick_len)
                p1_y = y + math.sin(rad) * (radius - tick_len)
                p2_x = x + math.cos(rad) * (radius + tick_len)
                p2_y = y + math.sin(rad) * (radius + tick_len)

                ticks.append({
                    'p1': QPointF(p1_x, p1_y),
                    'p2': QPointF(p2_x, p2_y),
                    'width': tick_width,
                    'outline_w': tick_width + outline_inc,
                    'color': color,
                    'label': "",
                    'rad': rad
                })

        # PASS 1: BLACK OUTLINE
        painter.setBrush(Qt.BrushStyle.NoBrush)

        painter.setPen(QPen(QColor(0, 0, 0, 255), 4.5))
        painter.drawEllipse(QPointF(x, y), radius, radius)

        for t in ticks:
            pen = QPen(QColor(0, 0, 0, 255), t['outline_w'])
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(t['p1'], t['p2'])

        # PASS 2: WHITE FILL
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2.5))
        painter.drawEllipse(QPointF(x, y), radius, radius)

        for t in ticks:
            pen = QPen(t['color'], t['width'])
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawLine(t['p1'], t['p2'])

        # LABELS
        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        fm = painter.fontMetrics()

        for t in ticks:
            if t['label']:
                r_text = radius - 25
                tx = x + math.cos(t['rad']) * r_text
                ty = y + math.sin(t['rad']) * r_text

                is_card = (len(t['label']) == 1)
                font_size = 12 if is_card else 10
                painter.setFont(QFont("Consolas", font_size, QFont.Weight.Bold))
                fm = painter.fontMetrics()
                tw = fm.horizontalAdvance(t['label'])
                th = fm.height()

                painter.setPen(QPen(QColor(0, 0, 0), 3))
                painter.drawText(int(tx - tw / 2), int(ty + th / 4), t['label'])

                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(tx - tw / 2), int(ty + th / 4), t['label'])

        # Draw Others (Players) - Triangles
        for item in others:
            if item.get('type') == 'poi':
                continue

            bearing = item.get('bearing', 0)
            color = item.get('color', QColor(255, 255, 255))
            label_text = item.get('label', '')

            bearing_deg_item = math.degrees(bearing)
            screen_angle_deg = bearing_deg_item - heading_deg - 90
            item_rad = math.radians(screen_angle_deg)

            ix = x + math.cos(item_rad) * radius
            iy = y + math.sin(item_rad) * radius

            painter.save()
            painter.translate(ix, iy)
            painter.rotate(screen_angle_deg + 180)

            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.setBrush(QBrush(color))
            path = QPainterPath()
            path.moveTo(0, -6)
            path.lineTo(0, 6)
            path.lineTo(14, 0)
            path.closeSubpath()
            painter.drawPath(path)

            painter.restore()

            if label_text:
                lx = x + math.cos(item_rad) * (radius + 20)
                ly = y + math.sin(item_rad) * (radius + 20)
                painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                text_w = fm.horizontalAdvance(label_text)
                painter.setPen(QPen(QColor(0, 0, 0), 2))
                painter.drawText(int(lx - text_w / 2), int(ly), label_text)
                painter.setPen(QColor(255, 255, 255))
                painter.drawText(int(lx - text_w / 2), int(ly), label_text)

        # Draw Fixed Heading Marker
        heading_val = int((heading_deg + 90) % 360)
        heading_str = f"{heading_val:03d}"

        painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        hw = fm.horizontalAdvance(heading_str)

        text_y_hdg = y - radius - 25
        painter.setPen(QPen(QColor(0, 0, 0), 3))
        painter.drawText(int(x - hw / 2), int(text_y_hdg), heading_str)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(int(x - hw / 2), int(text_y_hdg), heading_str)

        # Fixed Triangle at Top
        tip_x = x
        tip_y = y - radius - 5
        base_y = tip_y - 12

        path = QPainterPath()
        path.moveTo(tip_x, tip_y)
        path.lineTo(tip_x - 6, base_y)
        path.lineTo(tip_x + 6, base_y)
        path.closeSubpath()

        config_color = QColor(CONFIG.get('color', '#FFFF00'))
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(config_color)
        painter.drawPath(path)

        # Center Player Arrow (Fixed Up)
        painter.setBrush(QBrush(config_color))
        s = 1.5

        path = QPainterPath()
        path.moveTo(x, y - 10 * s)
        path.lineTo(x - 6 * s, y + 8 * s)
        path.lineTo(x, y + 4 * s)
        path.lineTo(x + 6 * s, y + 8 * s)
        path.closeSubpath()

        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.drawPath(path)

        painter.setBrush(Qt.BrushStyle.NoBrush)

    def draw_formation_panel(self, painter, cx, top_y, others):
        """Draws a list of nearby players under the compass"""
        if not self.players:
            return

        remote_players = []
        local_p = self.players.get('_local')
        if not local_p:
            return

        for pid, p in self.players.items():
            if pid == '_local':
                continue

            raw_dx = p['x'] - local_p['x']
            raw_dy = p['y'] - local_p['y']

            world_w = 65000
            if self.map_max and self.map_min:
                world_w = self.map_max[0] - self.map_min[0]

            dist_m = math.hypot(raw_dx * world_w, raw_dy * world_w)

            p_hdg = 0
            if abs(p.get('dx', 0)) > 0.0001 or abs(p.get('dy', 0)) > 0.0001:
                p_hdg = math.degrees(math.atan2(p.get('dy', 0), p.get('dx', 0))) + 90
                if p_hdg < 0:
                    p_hdg += 360

            remote_players.append({
                'callsign': p.get('callsign', 'Unknown'),
                'vehicle': p.get('vehicle', '-'),
                'dist': dist_m,
                'hdg': p_hdg,
                'alt': p.get('alt', 0),
                'spd': p.get('spd', 0),
                'color': p.get('color', Qt.GlobalColor.white)
            })

        remote_players.sort(key=lambda rp: rp['dist'])

        if not remote_players:
            return

        painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        line_h = 20
        col_widths = [90, 80, 50, 40, 40, 40]
        total_w = sum(col_widths)

        y_pos = top_y + 20
        x_pos = cx - (total_w / 2)

        bg_rect = QRectF(x_pos - 5, y_pos - 5, total_w + 10, ((len(remote_players) + 1) * line_h) + 10)
        painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
        painter.setPen(QPen(Qt.GlobalColor.white, 1))
        painter.drawRect(bg_rect)

        header_labels = ["PILOT", "TYPE", "DST", "HDG", "ALT", "SPD"]
        cur_x = x_pos
        for i, label in enumerate(header_labels):
            w = col_widths[i]
            painter.setPen(QPen(Qt.GlobalColor.gray))
            align_flag = Qt.AlignmentFlag.AlignLeft
            rect = QRectF(cur_x + 2, y_pos, w - 2, line_h)
            painter.drawText(rect, align_flag | Qt.AlignmentFlag.AlignVCenter, label)
            cur_x += w

        y_pos += line_h
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawLine(int(x_pos), int(y_pos), int(x_pos + total_w), int(y_pos))

        is_kts = CONFIG.get('unit_is_kts', True)

        for p in remote_players:
            dist_unit = CONFIG.get('distance_unit', 'km').lower()
            if dist_unit == 'nm':
                if p['dist'] > 185.2:
                    d_str = f"{p['dist'] / 1852:.1f}nm"
                else:
                    d_str = f"{p['dist'] / 1852:.2f}nm"
            else:
                if p['dist'] > 1000:
                    d_str = f"{p['dist'] / 1000:.1f}k"
                else:
                    d_str = f"{p['dist']:.0f}m"

            spd_val = p['spd']
            if is_kts:
                spd_val *= 0.539957

            row_data = [
                p['callsign'],
                p['vehicle'],
                d_str,
                f"{int(p['hdg']):03d}",
                f"{p['alt'] / 1000:.1f}",
                f"{int(spd_val)}"
            ]

            cur_x = x_pos
            for i, text in enumerate(row_data):
                w = col_widths[i]

                painter.setPen(QPen(Qt.GlobalColor.white))
                if i == 0:
                    painter.setPen(QPen(p['color']))

                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                if i <= 1:
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

                rect = QRectF(cur_x + 2, y_pos, w - 4, line_h)

                elided_text = painter.fontMetrics().elidedText(str(text), Qt.TextElideMode.ElideRight, int(w - 4))
                painter.drawText(rect, align, elided_text)

                cur_x += w
            y_pos += line_h

        # Draw Vertical Lines
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        cur_x = x_pos
        top_y_line = top_y + 20
        bottom_y_line = y_pos
        for w in col_widths[:-1]:
            cur_x += w
            painter.drawLine(int(cur_x), int(top_y_line), int(cur_x), int(bottom_y_line))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # --- TIMER DISPLAY (Top Right - Always Visible) ---
        if self.spawn_time is not None:
            self.flight_time = time.time() - self.spawn_time

        screen_width = self.width()
        right_margin = 2
        top_margin = 13
        line_height = 15

        self.marker_scale = min(CONFIG.get('map_width', 834) / self.baseline_width, CONFIG.get('map_height', 834) / self.baseline_height)

        total_seconds = self.flight_time
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        time_str = f"T+{hours:02d}:{minutes:02d}:{seconds:02d}"

        interval = CONFIG.get('timer_interval', 15)
        next_mark = ((minutes // interval) + 1) * interval
        if next_mark >= 60:
            next_mark = 0

        current_seconds_in_hour = minutes * 60 + seconds
        target_seconds_in_hour = next_mark * 60

        if target_seconds_in_hour <= current_seconds_in_hour:
            target_seconds_in_hour += 3600

        time_to_next = target_seconds_in_hour - current_seconds_in_hour

        countdown_hours = int(time_to_next // 3600)
        countdown_minutes = int((time_to_next % 3600) // 60)
        countdown_seconds = int(time_to_next % 60)
        countdown_str = f"T-{countdown_hours:02d}:{countdown_minutes:02d}:{countdown_seconds:02d}"

        font_timer = QFont('Courier New', 11, QFont.Weight.Bold)
        metrics_timer = QFontMetrics(font_timer)

        text_width_plus = metrics_timer.horizontalAdvance(time_str)
        text_width_minus = metrics_timer.horizontalAdvance(countdown_str)

        max_width = max(text_width_plus, text_width_minus)

        timer_x = screen_width - max_width - right_margin

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setFont(font_timer)
        painter.drawText(timer_x, top_margin + 1, time_str)

        painter.setPen(QPen(QColor(200, 200, 200), 2))
        painter.setFont(font_timer)
        painter.drawText(timer_x, top_margin + line_height + 1, countdown_str)

        # Mode Check: HUD vs Full Map
        if not self.show_marker:
            # HUD Mode: Only Compass Top Right
            if getattr(self, 'show_compass', True) and '_local' in self.players:
                p = self.players['_local']
                dx = p.get('dx', 0)
                dy = p.get('dy', 0)
                heading_rad = 0
                if abs(dx) > 0.001 or abs(dy) > 0.001:
                    heading_rad = math.atan2(dy, dx)

                others = []

                for pid, other_p in self.players.items():
                    if pid == '_local':
                        continue
                    o_dx = other_p.get('x', 0) - p.get('x', 0)
                    o_dy = other_p.get('y', 0) - p.get('y', 0)
                    if abs(o_dx) > 0.0001 or abs(o_dy) > 0.0001:
                        bearing = math.atan2(o_dy, o_dx)
                        others.append({
                            'type': 'player',
                            'bearing': bearing,
                            'color': other_p.get('color', QColor(255, 255, 255)),
                            'label': ''
                        })

                if hasattr(self, 'pois'):
                    for poi in self.pois:
                        p_dx = poi.get('x', 0) - p.get('x', 0)
                        p_dy = poi.get('y', 0) - p.get('y', 0)
                        if abs(p_dx) > 0.0001 or abs(p_dy) > 0.0001:
                            p_bearing = math.atan2(p_dy, p_dx)
                            others.append({
                                'type': 'poi',
                                'bearing': p_bearing,
                                'color': QColor(CONFIG.get('color', '#FFFF00'))
                            })

                if hasattr(self, 'shared_pois'):
                    for pid, poi in self.shared_pois.items():
                        p_dx = poi.get('x', 0) - p.get('x', 0)
                        p_dy = poi.get('y', 0) - p.get('y', 0)
                        if abs(p_dx) > 0.0001 or abs(p_dy) > 0.0001:
                            p_bearing = math.atan2(p_dy, p_dx)
                            use_color = poi.get('player_color', poi.get('color', Qt.GlobalColor.yellow))
                            others.append({
                                'type': 'poi',
                                'bearing': p_bearing,
                                'color': use_color
                            })

                rx = self.width() - 133
                ry = 150

                self.draw_compass_rose(painter, rx, ry, 102.5, heading_rad, others, local_player=p)

                # --- HEADING & TARGET TEXT ---
                heading_deg = math.degrees(heading_rad) % 360

                target_bearing = None
                target_dist = None

                if self.planning_waypoints:
                    wp = self.planning_waypoints[0]
                    dx_t = wp['x'] - p.get('x', 0)
                    dy_t = wp['y'] - p.get('y', 0)
                    if abs(dx_t) > 0.0001 or abs(dy_t) > 0.0001:
                        target_bearing = math.degrees(math.atan2(dy_t, dx_t)) % 360
                        map_size_m = float(CONFIG.get('map_size_meters', 65000))
                        if hasattr(self, 'map_bounds') and self.map_bounds:
                            map_min = self.map_bounds.get('map_min', [0, 0])
                            map_max = self.map_bounds.get('map_max', [map_size_m, map_size_m])
                            map_size_m = max(map_max[0] - map_min[0], map_max[1] - map_min[1])
                        dist_norm = math.hypot(dx_t, dy_t)
                        target_dist = (dist_norm * map_size_m) / 1000.0

                painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
                metrics = QFontMetrics(painter.font())
                text_y = ry + 125

                if target_bearing is not None:
                    tgt_str = f"TGT: {int(target_bearing):03d}"
                    painter.setPen(QPen(Qt.GlobalColor.cyan))
                    painter.drawText(rx - 40, text_y + 15, tgt_str)

                    diff = (target_bearing - heading_deg + 180) % 360 - 180
                    direction = "R" if diff > 0 else "L"
                    if abs(diff) < 2:
                        direction = ""
                    delta_str = f"{direction} {abs(int(diff))}"

                    dist_str = f"{target_dist:.1f}km"
                    painter.drawText(rx + 35, text_y + 15, dist_str)

                if getattr(self, 'show_formation_mode', False):
                    table_center_x = self.width() - 20 - 178
                    self.draw_formation_panel(painter, table_center_x, ry + 120, others)

        # --- Full Map Mode ---
        painter.setPen(QPen(Qt.GlobalColor.green if self.status_text.startswith("8111: OK") else Qt.GlobalColor.red))
        painter.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        painter.drawText(2, 13, self.status_text)

        if self.calibration_status:
            status_color = Qt.GlobalColor.yellow if "Calibrating" in self.calibration_status else (
                Qt.GlobalColor.green if "OK" in self.calibration_status else Qt.GlobalColor.red
            )
            painter.setPen(QPen(status_color))
            painter.drawText(2, 26, f"{self.calibration_status}")

        # Draw Player List
        if self.show_marker:
            self._draw_player_list(painter, screen_width, right_margin)

        if self.show_marker and self.map_min and self.overlay_enabled:
            self._draw_map_content(painter, screen_width, right_margin)

        # --- DEBUG OVERLAY ---
        if DEBUG_MODE and self.show_marker:
            painter.setPen(QPen(QColor(255, 0, 0), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(CONFIG.get('map_offset_x', 0)), int(CONFIG.get('map_offset_y', 0)), int(CONFIG.get('map_width', 800)), int(CONFIG.get('map_height', 800)))

        # --- DRAW JDAM OVERLAY ---
        self.draw_tti(painter)

        # --- SAM / AAA THREAT WARNING ---
        self._draw_threat_warning(painter)

    def _draw_player_list(self, painter, screen_width, right_margin):
        """Draw the player list on the right side of the screen."""
        list_y = 55

        header_text = "Active Aircraft:"
        font_header = QFont('Arial', 10, QFont.Weight.Bold)
        metrics_header = QFontMetrics(font_header)
        header_width = metrics_header.horizontalAdvance(header_text)

        header_x = screen_width - header_width - right_margin

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setFont(font_header)
        painter.drawText(header_x, list_y, header_text)

        y_offset = 20
        font_player = QFont('Arial', 9)
        metrics_player = QFontMetrics(font_player)

        sorted_pids = sorted(self.players.keys(), key=lambda pid: 0 if pid == '_local' else 1)

        for pid in sorted_pids:
            p = self.players[pid]
            callsign = p.get('callsign', pid)
            if pid == '_local':
                callsign = f"{callsign} (You)"

            color = p.get('color', Qt.GlobalColor.white)

            text_width = metrics_player.horizontalAdvance(callsign)
            text_x = screen_width - text_width - right_margin
            indicator_x = text_x - 15

            painter.setBrush(QBrush(color))
            painter.setPen(QPen(color, 2))
            painter.drawEllipse(indicator_x, list_y + y_offset - 8, 8, 8)

            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setFont(font_player)
            painter.drawText(text_x, list_y + y_offset, callsign)

            y_offset += 20

    def _draw_map_content(self, painter, screen_width, right_margin):
        """Draw all map-mode content: airfields, players, POIs, scale bars, etc."""
        # --- Draw Airfields (Runway Rectangles) ---
        if self.airfields:
            for af in self.airfields:
                ax = CONFIG.get('map_offset_x', 0) + (af['x'] * CONFIG.get('map_width', 800))
                ay = CONFIG.get('map_offset_y', 0) + (af['y'] * CONFIG.get('map_height', 800))

                painter.save()
                painter.translate(ax, ay)
                painter.rotate(af['angle'])

                rect_w = 30 * self.marker_scale
                if 'len' in af and af['len'] > 0:
                    rect_w = (af['len'] * CONFIG.get('map_width', 800)) * 1.0
                    rect_w = max(rect_w, 15 * self.marker_scale)

                rect_h = 6 * self.marker_scale

                painter.setPen(QPen(Qt.GlobalColor.black, 1))
                af_color = af.get('color', Qt.GlobalColor.white)
                painter.setBrush(QBrush(af_color))
                painter.drawRect(QRectF(-rect_w / 2, -rect_h / 2, rect_w, rect_h))

                painter.restore()

        # Sort: Local first, then others
        sorted_pids = sorted(self.players.keys(), key=lambda pid: 0 if pid == '_local' else 1)

        for pid in sorted_pids:
            player = self.players[pid]

            # --- Draw Contrail ---
            if 'trail' in player and len(player['trail']) > 1:
                trail_points = []
                for pt in player['trail']:
                    if pt.get('x') is None or pt.get('y') is None:
                        continue
                    tx = CONFIG.get('map_offset_x', 0) + (pt['x'] * CONFIG.get('map_width', 800))
                    ty = CONFIG.get('map_offset_y', 0) + (pt['y'] * CONFIG.get('map_height', 800))
                    trail_points.append(QPointF(tx, ty))

                if len(trail_points) >= 2:
                    head_pt = QPointF(CONFIG.get('map_offset_x', 0) + (player['x'] * CONFIG.get('map_width', 800)),
                                     CONFIG.get('map_offset_y', 0) + (player['y'] * CONFIG.get('map_height', 800)))
                    exclusion_radius = 8 * self.marker_scale

                    cut_index = -1
                    for i in range(len(trail_points) - 1, -1, -1):
                        pt_i = trail_points[i]
                        dx_i = pt_i.x() - head_pt.x()
                        dy_i = pt_i.y() - head_pt.y()
                        dist_i = math.hypot(dx_i, dy_i)
                        if dist_i > exclusion_radius:
                            cut_index = i
                            v_x = pt_i.x() - head_pt.x()
                            v_y = pt_i.y() - head_pt.y()
                            factor = exclusion_radius / dist_i
                            start_x = head_pt.x() + v_x * factor
                            start_y = head_pt.y() + v_y * factor
                            trimmed_points = trail_points[:i + 1]
                            trimmed_points.append(QPointF(start_x, start_y))
                            break

                    if cut_index != -1:
                        trail_points = trimmed_points
                    else:
                        trail_points = []

                if len(trail_points) > 1:
                    trail_color = QColor(player['color'])
                    trail_color.setAlpha(150)
                    painter.setPen(QPen(trail_color, 2))
                    painter.drawPolyline(trail_points)

            raw_x, raw_y = player['x'], player['y']

            if not (0.0 <= raw_x <= 1.0 and 0.0 <= raw_y <= 1.0):
                continue

            if abs(raw_x) < 0.001 and abs(raw_y) < 0.001:
                continue

            x = CONFIG.get('map_offset_x', 0) + (raw_x * CONFIG.get('map_width', 800))
            y = CONFIG.get('map_offset_y', 0) + (raw_y * CONFIG.get('map_height', 800))


            # --- Draw Arrow ---
            painter.save()
            painter.translate(x, y)

            rotation = 0.0
            dx, dy = player['dx'], player['dy']
            if abs(dx) > 0.001 or abs(dy) > 0.001:
                rotation = math.degrees(math.atan2(dy, dx))

            painter.rotate(rotation)

            color = player.get('color', QColor(0, 0, 255, 200))
            painter.setPen(QPen(color, 2))
            painter.setBrush(QBrush(color))

            # Draw Callsign Text
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8))
            painter.save()
            painter.rotate(-rotation)
            painter.drawText(-20, -15, player.get('callsign', 'Unknown'))
            painter.restore()

            painter.setPen(QPen(color, 2))

            scale = self.marker_scale
            arrow_polygon = QPolygonF([
                QPointF(14 * scale, 0),
                QPointF(-5 * scale, -7 * scale),
                QPointF(-5 * scale, 7 * scale)
            ])

            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPolygon(arrow_polygon)

            spd = player.get('spd', 0)
            if spd > 10:
                vector_len = spd * 0.03 * scale
                painter.drawLine(QPointF(14 * scale, 0), QPointF(14 * scale + vector_len, 0))

            # Draw Altitude and Speed Text
            painter.save()
            painter.rotate(-rotation)

            alt_m = player.get('alt', 0)
            alt_km = alt_m / 1000.0
            spd_kmh = player.get('spd', 0)

            is_kts = CONFIG.get('unit_is_kts', True)
            if is_kts:
                spd_display = spd_kmh * 0.539957
            else:
                spd_display = spd_kmh

            stats_text = f"{int(spd_display)} {alt_km:.1f}"

            painter.setPen(QPen(Qt.GlobalColor.white))
            font_stats = QFont("Arial", 8)
            painter.setFont(font_stats)

            metrics = QFontMetrics(font_stats)
            text_width = metrics.horizontalAdvance(stats_text)
            painter.drawText(-text_width // 2, 30, stats_text)

            painter.restore()
            painter.restore()

        # --- Draw Airfield Labels & Features ---
        self._draw_airfield_labels(painter)

        # --- Draw Scale Bars ---
        self._draw_scale_bars(painter)

        # --- Draw SPAA Radius Circles ---
        self._draw_spaa_circles(painter)

        # --- Draw Local POIs ---
        self._draw_local_pois(painter)

        # --- Draw Shared POIs ---
        self._draw_shared_pois(painter)

    def _draw_airfield_labels(self, painter):
        """Draw airfield labels, 12km circles, and debug info."""
        if not self.airfields:
            return

        map_size_m = float(CONFIG.get('map_size_meters', 65000))

        for idx, airfield in enumerate(self.airfields):
            raw_x, raw_y = airfield['x'], airfield['y']
            if raw_x is None or raw_y is None:
                continue
            if abs(raw_x) < 0.01 and abs(raw_y) < 0.01:
                continue

            x = CONFIG.get('map_offset_x', 0) + (raw_x * CONFIG.get('map_width', 800))
            y = CONFIG.get('map_offset_y', 0) + (raw_y * CONFIG.get('map_height', 800))

            painter.save()
            painter.translate(x, y)
            angle = airfield.get('angle', 0)
            painter.rotate(angle)

            c = airfield.get('color', QColor(100, 100, 255))

            runway_len = 20 * self.marker_scale
            if airfield.get('len') and airfield['len'] > 0.001:
                runway_len = (airfield['len'] * CONFIG.get('map_width', 800)) * 0.5
                runway_len = max(runway_len, 10 * self.marker_scale)

            painter.setPen(QPen(c, 6))
            painter.drawLine(int(-runway_len / 2), 0, int(runway_len / 2), 0)

            # 12km radius circle for long runways
            runway_meters = (airfield.get('len', 0) * map_size_m)
            if runway_meters > 3000:
                radius_normalized = 12000 / map_size_m
                radius_pixels = radius_normalized * CONFIG.get('map_width', 800)

                painter.rotate(-angle)
                circle_pen = QPen(c, 4, Qt.PenStyle.DashLine)
                circle_pen.setColor(QColor(c.red(), c.green(), c.blue(), 100))
                painter.setPen(circle_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(int(-radius_pixels), int(-radius_pixels),
                                    int(radius_pixels * 2), int(radius_pixels * 2))
                painter.rotate(angle)

            af_label = f"AF{airfield.get('id', idx + 1)}"
            if airfield.get('is_cv'):
                af_label = f"CV{airfield.get('id', idx + 1)}"

            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.rotate(-angle)

            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            painter.drawText(-15, -20, af_label)

            painter.restore()

        if self.show_debug:
            painter.setPen(QPen(Qt.GlobalColor.green, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(int(CONFIG.get('map_offset_x', 0)), int(CONFIG.get('map_offset_y', 0)), int(CONFIG.get('map_width', 800)), int(CONFIG.get('map_height', 800)))

            painter.setPen(QPen(Qt.GlobalColor.green))
            painter.setFont(QFont("Arial", 10))

            trail_info = ""
            if '_local' in self.players:
                t_len = len(self.players['_local'].get('trail', []))
                trail_info = f" | Trail: {t_len}"

            painter.drawText(int(CONFIG.get('map_offset_x', 0)), int(CONFIG.get('map_offset_y', 0)) - 5,
                             f"Map: {CONFIG.get('map_width', 800)}x{CONFIG.get('map_height', 800)} ({CONFIG.get('map_offset_x', 0)},{CONFIG.get('map_offset_y', 0)}){trail_info}")

    def _draw_scale_bars(self, painter):
        """Draw KM and NM scale bars at bottom right of map."""
        map_size_m = float(CONFIG.get('map_size_meters', 65000))

        if hasattr(self, 'map_bounds') and self.map_bounds:
            map_min = self.map_bounds.get('map_min', [0, 0])
            map_max = self.map_bounds.get('map_max', [map_size_m, map_size_m])
            map_size_m = max(map_max[0] - map_min[0], map_max[1] - map_min[1])

        grid_cells = 8
        grid_cell_m = map_size_m / grid_cells
        grid_cell_km = grid_cell_m / 1000

        map_right_edge = CONFIG.get('map_offset_x', 0) + CONFIG.get('map_width', 800)

        max_km = 10
        if map_size_m < 12000: max_km = 5
        if map_size_m < 6000: max_km = 2

        pixels_per_km = CONFIG.get('map_width', 800) / (map_size_m / 1000)

        bar_width = round(max_km * pixels_per_km)
        bar_x = int(map_right_edge - bar_width)
        bar_y = int(CONFIG.get('map_offset_y', 0) + CONFIG.get('map_height', 800) - 35)

        # KM Base Line
        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawLine(bar_x, bar_y, bar_x + bar_width, bar_y)
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawLine(bar_x, bar_y, bar_x + bar_width, bar_y)

        tick_marks = [0, 1, 5, 10]
        if max_km < 10:
            tick_marks = [0, 1, 2, 5] if max_km >= 5 else [0, 0.5, 1, 2]

        painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
        fm = QFontMetrics(painter.font())

        for km in tick_marks:
            if km > max_km: continue
            px_offset = round(km * pixels_per_km)
            tick_x = (bar_x + bar_width) - px_offset

            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(tick_x, bar_y, tick_x, bar_y - 6)

            is_whole = isinstance(km, int) or (isinstance(km, float) and km.is_integer())
            label = f"{int(km)}" if is_whole else f"{km}"
            if km == 0: label = "0"

            tw = fm.horizontalAdvance(label)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(int(tick_x - tw / 2 + 1), int(bar_y - 8), label)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(int(tick_x - tw / 2), int(bar_y - 9), label)

        label = "km"
        tw = fm.horizontalAdvance(label)
        label_x = int(bar_x + bar_width + 8)
        painter.setPen(QPen(Qt.GlobalColor.black))
        painter.drawText(label_x + 1, int(bar_y - 8), label)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(label_x, int(bar_y - 9), label)

        # NM Scale
        nm_bar_y = bar_y + 25
        px_10nm = round(10 * 1.852 * pixels_per_km)
        nm_bar_x_start = (bar_x + bar_width) - px_10nm

        painter.setPen(QPen(Qt.GlobalColor.black, 4))
        painter.drawLine(nm_bar_x_start, nm_bar_y, bar_x + bar_width, nm_bar_y)
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawLine(nm_bar_x_start, nm_bar_y, bar_x + bar_width, nm_bar_y)

        nm_ticks = [0, 1, 2, 5, 10]
        for nm in nm_ticks:
            px_offset = round(nm * 1.852 * pixels_per_km)
            tick_x = (bar_x + bar_width) - px_offset

            painter.setPen(QPen(Qt.GlobalColor.white, 2))
            painter.drawLine(tick_x, nm_bar_y, tick_x, nm_bar_y - 6)

            label = f"{int(nm)}"
            tw = fm.horizontalAdvance(label)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(int(tick_x - tw / 2 + 1), int(nm_bar_y - 8), label)
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(int(tick_x - tw / 2), int(nm_bar_y - 9), label)

        label = "NM"
        painter.setPen(QPen(Qt.GlobalColor.black))
        painter.drawText(label_x + 1, int(nm_bar_y - 8), label)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(label_x, int(nm_bar_y - 9), label)

        # Grid & Map Size Labels
        grid_km = (map_size_m / 8) / 1000
        map_label_y = nm_bar_y + 35
        grid_label_y = map_label_y - 12

        grid_nm = grid_km * 0.539957
        label = f"{grid_km:.2f} km = {grid_nm:.2f} NM"
        tw = fm.horizontalAdvance(label)

        painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))

        painter.setPen(QPen(Qt.GlobalColor.black))
        painter.drawText(int(bar_x + bar_width - tw + 1), int(grid_label_y + 1), label)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(int(bar_x + bar_width - tw), int(grid_label_y), label)

        map_km = map_size_m / 1000
        map_nm = map_km * 0.539957
        label = f"Map: {int(map_km)}km/{int(map_nm)}NM"
        tw = fm.horizontalAdvance(label)
        painter.setPen(QPen(Qt.GlobalColor.black))
        painter.drawText(int(bar_x + bar_width - tw + 1), int(map_label_y + 1), label)
        painter.setPen(QPen(Qt.GlobalColor.white))
        painter.drawText(int(bar_x + bar_width - tw), int(map_label_y), label)

    def _draw_spaa_circles(self, painter):
        """Draw 4.5km radius circles around SPAA clusters."""
        if not hasattr(self, 'map_ground_units') or not self.map_ground_units:
            return

        map_size_m = float(CONFIG.get('map_size_meters', 65000))
        if hasattr(self, 'map_bounds') and self.map_bounds:
            map_min = self.map_bounds.get('map_min', [0, 0])
            map_max = self.map_bounds.get('map_max', [map_size_m, map_size_m])
            map_size_m = max(map_max[0] - map_min[0], map_max[1] - map_min[1])

        spaa_clusters = []
        cluster_threshold = 0.05

        for unit in self.map_ground_units:
            icon = (unit.get('icon') or '').lower()
            if 'aa' in icon or 'spaa' in icon or 'sam' in icon:
                unit_x, unit_y = unit.get('x', 0), unit.get('y', 0)
                added = False

                for cluster in spaa_clusters:
                    dist = ((unit_x - cluster['x']) ** 2 + (unit_y - cluster['y']) ** 2) ** 0.5
                    if dist < cluster_threshold:
                        n = cluster['count']
                        cluster['x'] = (cluster['x'] * n + unit_x) / (n + 1)
                        cluster['y'] = (cluster['y'] * n + unit_y) / (n + 1)
                        cluster['count'] += 1
                        added = True
                        break

                if not added:
                    spaa_clusters.append({
                        'x': unit_x, 'y': unit_y, 'count': 1,
                        'color': unit.get('color', '#FF0000')
                    })

        for cluster in spaa_clusters:
            is_near_airfield = False
            if hasattr(self, 'airfields') and self.airfields:
                for af in self.airfields:
                    af_x, af_y = af.get('x', 0), af.get('y', 0)
                    dist = ((cluster['x'] - af_x) ** 2 + (cluster['y'] - af_y) ** 2) ** 0.5
                    if dist < 0.08:
                        is_near_airfield = True
                        break

            if is_near_airfield:
                continue

            cx = CONFIG.get('map_offset_x', 0) + (cluster['x'] * CONFIG.get('map_width', 800))
            cy = CONFIG.get('map_offset_y', 0) + (cluster['y'] * CONFIG.get('map_height', 800))

            radius_normalized = 4500 / map_size_m
            radius_pixels = radius_normalized * CONFIG.get('map_width', 800)

            color_str = str(cluster.get('color', '#FF0000'))
            is_friendly = '#043' in color_str or '#174D' in color_str or '4,63,255' in color_str
            circle_color = QColor(126, 226, 255, 150) if is_friendly else QColor(255, 126, 126, 150)

            painter.save()
            painter.translate(cx, cy)
            pen = QPen(circle_color, 3, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(-radius_pixels), int(-radius_pixels),
                                int(radius_pixels * 2), int(radius_pixels * 2))
            painter.restore()

    def _draw_local_pois(self, painter):
        """Draw locally detected POIs."""
        if not self.pois:
            return

        for poi in self.pois:
            raw_x, raw_y = poi['x'], poi['y']
            x = CONFIG.get('map_offset_x', 0) + (raw_x * CONFIG.get('map_width', 800))
            y = CONFIG.get('map_offset_y', 0) + (raw_y * CONFIG.get('map_height', 800))

            painter.save()
            painter.translate(x, y)

            my_color = QColor(CONFIG.get('color', '#FFCC11'))
            painter.setPen(QPen(my_color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            radius = 15
            arc_angle = 60
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, -30 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 60 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 150 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 240 * 16, arc_angle * 16)

            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            painter.drawText(-15, -20, CONFIG.get('callsign', 'Me'))
            painter.restore()

    def _draw_shared_pois(self, painter):
        """Draw POIs shared by other players."""
        if not self.shared_pois:
            return

        current_time = time.time()
        expired_pids = []

        for pid, poi in list(self.shared_pois.items()):
            if current_time - poi.get('last_seen', 0) > 20:
                expired_pids.append(pid)
                continue
            player = self.players.get(pid)
            if not player or (current_time - player.get('last_seen', 0) > 30):
                expired_pids.append(pid)

        for pid in expired_pids:
            if pid in self.shared_pois:
                del self.shared_pois[pid]

        for pid, poi in self.shared_pois.items():
            raw_x, raw_y = poi['x'], poi['y']

            x = CONFIG.get('map_offset_x', 0) + (raw_x * CONFIG.get('map_width', 800))
            y = CONFIG.get('map_offset_y', 0) + (raw_y * CONFIG.get('map_height', 800))

            painter.save()
            painter.translate(x, y)

            poi_color = poi.get('player_color', QColor(255, 255, 255))

            painter.setPen(QPen(poi_color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)

            radius = 15
            arc_angle = 60

            painter.drawArc(-radius, -radius, radius * 2, radius * 2, -30 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 60 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 150 * 16, arc_angle * 16)
            painter.drawArc(-radius, -radius, radius * 2, radius * 2, 240 * 16, arc_angle * 16)

            callsign = poi.get('callsign', 'Unknown')
            label_text = f"{callsign}"
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
            painter.drawText(-30, -20, label_text)

            painter.restore()

    def _draw_threat_warning(self, painter):
        """Draw SAM/AAA threat warnings."""
        threat_type = None

        if hasattr(self, 'map_ground_units') and '_local' in self.players:
            local_p = self.players['_local']
            local_x, local_y = local_p['x'], local_p['y']

            map_size_m = float(CONFIG.get('map_size_meters', 65000))
            if self.map_max and self.map_min:
                width_m = self.map_max[0] - self.map_min[0]
                height_m = self.map_max[1] - self.map_min[1]
                map_size_m = max(width_m, height_m)

            # Check 1: Enemy Airfield (SAM - 12km)
            sam_radius_norm = 12000 / map_size_m
            if self.airfields:
                for af in self.airfields:
                    raw_color = af.get('color')
                    if isinstance(raw_color, QColor):
                        color_str = raw_color.name()
                    else:
                        color_str = str(raw_color)

                    is_friendly = (
                        '#043' in color_str or
                        '#174D' in color_str or
                        '4,63,255' in color_str or
                        color_str.lower().startswith('#00') or
                        color_str.lower().startswith('#4c') or
                        color_str.lower().startswith('#55')
                    )

                    if isinstance(raw_color, QColor):
                        if raw_color.blue() > 150 and raw_color.red() < 100:
                            is_friendly = True

                    if not is_friendly:
                        dist = math.hypot(af['x'] - local_x, af['y'] - local_y)
                        if dist < sam_radius_norm:
                            threat_type = "SAM"
                            break

            # Check 2: Enemy SPAA (AAA - 4.5km)
            aaa_radius_norm = 4500 / map_size_m

            if self.map_ground_units:
                for unit in self.map_ground_units:
                    icon = (unit.get('icon') or '').lower()
                    if 'aa' in icon or 'spaa' in icon or 'sam' in icon:
                        color_str = str(unit.get('color', '#FF0000'))
                        is_friendly = '#043' in color_str or '#174D' in color_str or '4,63,255' in color_str

                        u_x, u_y = unit.get('x', 0), unit.get('y', 0)
                        dist = math.hypot(u_x - local_x, u_y - local_y)

                        if not is_friendly:
                            if dist < aaa_radius_norm:
                                threat_type = "AAA"
                                break

        if threat_type:
            if hasattr(self, 'vws'):
                self.vws.play_warning(threat_type)

            interval = 1.0
            if hasattr(self, 'vws'):
                interval = self.vws.interval

            if (time.time() % interval) < (interval / 2):
                font_size = 28
                painter.setFont(QFont("Arial", font_size, QFont.Weight.Bold))

                warn_text = threat_type
                fm = QFontMetrics(painter.font())
                tw = fm.horizontalAdvance(warn_text)
                th = fm.height()

                warn_x = 100
                warn_y = self.height() - 200

                padding = 10
                box_rect = QRectF(warn_x - padding, warn_y - th + (padding / 2), tw + (padding * 2), th + padding)

                painter.setBrush(QBrush(QColor(0, 0, 0, 180)))
                painter.setPen(QPen(QColor(255, 0, 0), 2))
                painter.drawRoundedRect(box_rect, 5, 5)

                painter.setPen(QPen(QColor(255, 0, 0)))
                painter.drawText(warn_x, warn_y, warn_text)
