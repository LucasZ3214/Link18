"""
Link18 Triangulation Module
Multi-aircraft cooperative positioning via bearing-line intersection.

Given RWR bearing lines from multiple aircraft, computes a triangulated
position using least-squares intersection and provides a confidence score.
"""
import math


def triangulate(observers):
    """
    Compute target position from multiple bearing observations.

    Uses the weighted least-squares intersection of bearing lines.
    Each observer provides their position and a bearing to the target.

    Args:
        observers: list of dicts, each with:
            'x': float - observer X position (normalized 0-1)
            'y': float - observer Y position (normalized 0-1)
            'bearing_deg': float - absolute bearing to target (0=N, CW)

    Returns:
        dict with 'x', 'y' (estimated target position),
        'confidence' (0-1), 'num_observers' (int)
        or None if fewer than 2 observers
    """
    if len(observers) < 2:
        return None

    # Convert bearings to unit direction vectors
    # Bearing: 0°=N(+Y up), 90°=E(+X right)
    # In normalized coords: X=right, Y=down (screen convention)
    # So: dx = sin(bearing), dy = -cos(bearing)  [Y inverted]
    lines = []
    for obs in observers:
        bearing_rad = math.radians(obs['bearing_deg'])
        dx = math.sin(bearing_rad)
        dy = -math.cos(bearing_rad)
        lines.append({
            'ox': obs['x'],
            'oy': obs['y'],
            'dx': dx,
            'dy': dy,
            'bearing_deg': obs['bearing_deg']
        })

    # Least-squares intersection of N bearing lines
    # Each line: point P + t * D
    # We minimize sum of squared perpendicular distances to all lines
    #
    # For line i with origin O_i and direction D_i (unit vector):
    #   perpendicular distance of point X to line i:
    #     d_i = |(X - O_i) x D_i|
    #
    # Normal equation form: A^T A x = A^T b
    # Where each line contributes the constraint that X lies on it.
    #
    # Using the "perpendicular projection" formulation:
    #   n_i = perpendicular to D_i = (-dy, dx)
    #   n_i . (X - O_i) = 0
    #   => n_ix * X + n_iy * Y = n_ix * Ox + n_iy * Oy

    ata_00 = 0.0  # A^T A matrix (2x2)
    ata_01 = 0.0
    ata_11 = 0.0
    atb_0 = 0.0   # A^T b vector (2x1)
    atb_1 = 0.0

    for line in lines:
        # Normal to the bearing line
        nx = -line['dy']
        ny = line['dx']

        # Right-hand side
        rhs = nx * line['ox'] + ny * line['oy']

        # Accumulate normal equations
        ata_00 += nx * nx
        ata_01 += nx * ny
        ata_11 += ny * ny
        atb_0 += nx * rhs
        atb_1 += ny * rhs

    # Solve 2x2 system
    det = ata_00 * ata_11 - ata_01 * ata_01
    if abs(det) < 1e-12:
        # Lines are nearly parallel — can't triangulate
        return None

    inv_det = 1.0 / det
    x = (ata_11 * atb_0 - ata_01 * atb_1) * inv_det
    y = (ata_00 * atb_1 - ata_01 * atb_0) * inv_det

    # Compute confidence based on intersection geometry
    conf = confidence_score(lines, x, y)

    return {
        'x': x,
        'y': y,
        'confidence': conf,
        'num_observers': len(observers)
    }


def confidence_score(lines, target_x, target_y):
    """
    Compute confidence (0-1) based on:
    1. Intersection angle (perpendicular bearings = best)
    2. Residual error (how close lines actually intersect)
    """
    if len(lines) < 2:
        return 0.0

    # 1. Angle factor: best when bearing lines are perpendicular
    # Compute pairwise intersection angles
    max_angle = 0.0
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            # Angle between two direction vectors
            dot = lines[i]['dx'] * lines[j]['dx'] + lines[i]['dy'] * lines[j]['dy']
            dot = max(-1.0, min(1.0, dot))
            angle = math.acos(abs(dot))  # 0 = parallel, π/2 = perpendicular
            max_angle = max(max_angle, angle)

    # Normalize: 0° parallel = 0, 90° perpendicular = 1
    angle_factor = max_angle / (math.pi / 2)

    # 2. Residual factor: average perpendicular distance of solution to each line
    total_residual = 0.0
    for line in lines:
        # Vector from observer to target
        vx = target_x - line['ox']
        vy = target_y - line['oy']
        # Perpendicular distance = cross product magnitude
        cross = abs(vx * line['dy'] - vy * line['dx'])
        total_residual += cross

    avg_residual = total_residual / len(lines)
    # Map residual to 0-1 (residual of 0.05 in normalized coords ≈ bad)
    residual_factor = max(0.0, 1.0 - avg_residual / 0.05)

    # 3. Number of observers bonus
    obs_factor = min(1.0, len(lines) / 3.0)  # 3+ observers = full bonus

    # Combined score
    confidence = angle_factor * 0.5 + residual_factor * 0.3 + obs_factor * 0.2
    return max(0.0, min(1.0, confidence))


def match_bearings(local_threats, remote_bearings, threshold_deg=15.0):
    """
    Match local RWR detections with remote bearing reports that likely
    point at the same target.

    Args:
        local_threats: list of local threat dicts (with bearing_abs, x, y, player_x, player_y)
        remote_bearings: dict of {sender: {'x': float, 'y': float,
                         'bearings': [{'bearing_abs': float, 'label': str}]}}
        threshold_deg: max angular difference to consider a match

    Returns:
        list of matched groups, each is a list of observer dicts:
        [{'x': observer_x, 'y': observer_y, 'bearing_deg': abs_bearing, 'label': str}]
    """
    if not local_threats or not remote_bearings:
        return []

    groups = []

    for local in local_threats:
        if local.get('bearing_abs') is None:
            continue
        if local.get('player_x') is None:
            continue

        group = [{
            'x': local['player_x'],
            'y': local['player_y'],
            'bearing_deg': local['bearing_abs'],
            'label': local.get('label', 'UNK'),
            'source': 'local'
        }]

        # Check each remote player's bearings
        for sender, remote in remote_bearings.items():
            remote_x = remote.get('x')
            remote_y = remote.get('y')
            if remote_x is None or remote_y is None:
                continue

            for rb in remote.get('bearings', []):
                remote_bearing = rb.get('bearing_abs')
                if remote_bearing is None:
                    continue

                # Check if this remote bearing could point at the same target
                # Compare: does the remote bearing from the remote position
                # point roughly toward the same area as our local bearing?

                # Compute what bearing the remote should see if looking at our estimated target
                dx = local['x'] - remote_x
                dy = local['y'] - remote_y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 0.001:
                    continue  # Same position, can't triangulate

                expected_bearing = math.degrees(math.atan2(dx, -dy)) % 360
                angular_diff = abs(remote_bearing - expected_bearing)
                if angular_diff > 180:
                    angular_diff = 360 - angular_diff

                if angular_diff < threshold_deg:
                    group.append({
                        'x': remote_x,
                        'y': remote_y,
                        'bearing_deg': remote_bearing,
                        'label': rb.get('label', 'UNK'),
                        'source': sender
                    })

        if len(group) >= 2:
            groups.append(group)

    return groups
