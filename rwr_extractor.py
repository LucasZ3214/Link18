"""
Link18 RWR Extractor Module
Screen-scrapes the in-game RWR display, detects threat contacts via OpenCV,
and infers their map coordinates using aircraft telemetry.
"""
import math
import json
import os
import time

try:
    import cv2
    import numpy as np
    from mss import mss
    RWR_AVAILABLE = True
except ImportError:
    RWR_AVAILABLE = False
    print("[RWR] OpenCV or mss not installed. RWR detection disabled.")
    print("[RWR] Install with: pip install opencv-python mss numpy")


# ─────────────────────────────────────────────
# RWR Database
# ─────────────────────────────────────────────

_rwr_db = None

def load_rwr_database():
    """Load the RWR database JSON file."""
    global _rwr_db
    try:
        db_path = os.path.join(os.path.dirname(__file__), 'rwr_database.json')
        if os.path.exists(db_path):
            with open(db_path, 'r', encoding='utf-8') as f:
                _rwr_db = json.load(f)
            print(f"[RWR] Database loaded: {len(_rwr_db.get('threat_labels', {}))} threat labels")
        else:
            print(f"[RWR] Database not found at {db_path}")
            _rwr_db = {}
    except Exception as e:
        print(f"[RWR] Error loading database: {e}")
        _rwr_db = {}
    return _rwr_db


def get_rwr_db():
    """Get the loaded RWR database (lazy load)."""
    global _rwr_db
    if _rwr_db is None:
        load_rwr_database()
    return _rwr_db


def get_display_max_range():
    """Get the RWR display outer ring range in meters."""
    db = get_rwr_db()
    return db.get('_meta', {}).get('rwr_display_max_range_m', 74000)


def get_display_min_range():
    """Get the RWR display inner ring range in meters (target min detection range)."""
    db = get_rwr_db()
    sensors = db.get('sensors', {})
    for sid, sensor in sensors.items():
        tr = sensor.get('targetRange', {})
        if 'min' in tr:
            return tr['min']
    return 9250.0


def get_threat_info(label):
    """Look up threat info by its RWR label string."""
    db = get_rwr_db()
    threats = db.get('threat_labels', {})
    # Exact match first
    if label in threats:
        return threats[label]
    # Case-insensitive match
    for key, val in threats.items():
        if key.upper() == label.upper():
            return val
    # Unknown
    return threats.get('UNK', {'max_range_m': 74000, 'type': 'UNK', 'description': 'Unknown'})


# ─────────────────────────────────────────────
# Screen Capture
# ─────────────────────────────────────────────

def capture_rwr_region(bbox):
    """
    Capture the RWR area of the screen.

    Args:
        bbox: tuple/list of (left, top, width, height) in screen pixels,
              or a string like "[25,408,230,230]" or "25,408,230,230"

    Returns:
        numpy array (BGR) or None on failure
    """
    if not RWR_AVAILABLE:
        return None

    try:
        # Parse string bbox if needed
        if isinstance(bbox, str):
            bbox = bbox.strip().strip('[]')
            bbox = [int(x.strip()) for x in bbox.split(',')]

        with mss() as sct:
            monitor = {
                "left": int(bbox[0]),
                "top": int(bbox[1]),
                "width": int(bbox[2]),
                "height": int(bbox[3])
            }
            screenshot = sct.grab(monitor)
            # Convert from BGRA to BGR
            img = np.array(screenshot)[:, :, :3].copy()
            return img
    except Exception as e:
        print(f"[RWR] Screen capture error: {e}")
        return None


# ─────────────────────────────────────────────
# Contact Detection (OpenCV)
# ─────────────────────────────────────────────

# Green color range for the RWR display (HSV)
# Tuned for the bright green used in War Thunder RWR UI
RWR_GREEN_LOW = (50, 80, 130)
RWR_GREEN_HIGH = (80, 255, 255)

# Minimum contour area to count as a valid contact (filters noise)
MIN_CONTOUR_AREA = 20
# Maximum contour area (filter out the RWR circle itself)
MAX_CONTOUR_AREA = 3000
# Max distance ratio - contacts beyond this are RWR circle border artifacts
MAX_DIST_RATIO = 0.92

# OCR confidence threshold (0-1, higher = stricter)
OCR_CONFIDENCE = 0.35

# Cached label templates for OCR
_label_templates = None
_char_templates = None
_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'rwr_templates')
_CHARS_DIR = os.path.join(_TEMPLATES_DIR, 'chars')


def _load_file_templates():
    """
    Load template images from rwr_templates/ directory.
    Filenames become labels: e.g. 'ADS.png' → label 'ADS'
    """
    templates = {}
    if not os.path.isdir(_TEMPLATES_DIR):
        return templates

    for fname in os.listdir(_TEMPLATES_DIR):
        if not fname.lower().endswith('.png'):
            continue
        label = os.path.splitext(fname)[0].upper()
        fpath = os.path.join(_TEMPLATES_DIR, fname)
        img = cv2.imread(fpath, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            # Threshold to binary
            _, binary = cv2.threshold(img, 100, 255, cv2.THRESH_BINARY)
            templates[label] = [binary]
            # Also add scaled versions for robustness
            for scale in [0.8, 1.2]:
                h, w = binary.shape
                sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
                resized = cv2.resize(binary, (sw, sh), interpolation=cv2.INTER_NEAREST)
                templates[label].append(resized)

    if templates:
        print(f"[RWR] Loaded {len(templates)} label template(s): {list(templates.keys())}")
    return templates


def _load_char_templates():
    """
    Load individual character templates from rwr_templates/chars/ directory.
    """
    templates = {}
    if not os.path.isdir(_CHARS_DIR):
        return templates

    for fname in os.listdir(_CHARS_DIR):
        if not fname.lower().endswith('.png'):
            continue
        char = os.path.splitext(fname)[0].upper()
        fpath = os.path.join(_CHARS_DIR, fname)
        img = cv2.imread(fpath, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            _, binary = cv2.threshold(img, 100, 255, cv2.THRESH_BINARY)
            templates[char] = [binary]
            # Add scales for robustness
            for scale in [0.85, 1.15]:
                h, w = binary.shape
                sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
                resized = cv2.resize(binary, (sw, sh), interpolation=cv2.INTER_NEAREST)
                templates[char].append(resized)

    if templates:
        print(f"[RWR] Loaded {len(templates)} character template(s): {sorted(list(templates.keys()))}")
    return templates


def _generate_templates():
    """
    Get OCR templates. Prefers file-based templates from rwr_templates/,
    falls back to cv2.putText-rendered templates.
    Now also loads character-level templates.
    """
    global _label_templates, _char_templates
    if _label_templates is None:
        _label_templates = _load_file_templates()
    if _char_templates is None:
        _char_templates = _load_char_templates()

    # Fall back to generated templates for missing labels (if not loaded from files)
    db = get_rwr_db()
    labels = list(db.get('threat_labels', {}).keys())
    if not labels:
        labels = ['AAA', 'S1', 'R1', '2S6', 'SA', 'AI', 'P', '11']

    for label in labels:
        if label == 'UNK' or label in _label_templates:
            continue
        templates = []
        for font_scale in [0.35, 0.4, 0.45, 0.5]:
            thickness = 1
            font = cv2.FONT_HERSHEY_SIMPLEX
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            pad = 4
            img = np.zeros((th + baseline + pad * 2, tw + pad * 2), dtype=np.uint8)
            cv2.putText(img, label, (pad, th + pad), font, font_scale, 255, thickness)
            templates.append(img)
        _label_templates[label] = templates

    return _label_templates


def reload_templates():
    """Force reload of templates (call after adding new template files)."""
    global _label_templates
    _label_templates = None
    return _generate_templates()


def _ocr_contact(mask, contact, image_center, image_radius, image=None):
    """
    Try to identify the label of a detected contact by template matching.
    Uses the raw green channel (Otsu thresholded) for more complete characters.
    """
    templates = _generate_templates()
    if not templates:
        return 'UNK'

    h, w = mask.shape[:2]

    # Estimate crop region around the contact
    crop_w = max(50, int(image_radius * 0.45))
    crop_h = max(25, int(image_radius * 0.22))

    x1 = max(0, contact['cx'] - crop_w // 2)
    y1 = max(0, contact['cy'] - crop_h // 2)
    x2 = min(w, x1 + crop_w)
    y2 = min(h, y1 + crop_h)

    # Prefer green channel with Otsu for complete characters
    if image is not None:
        green = image[y1:y2, x1:x2, 1]  # BGR green channel
        if green.shape[0] < 5 or green.shape[1] < 5:
            return 'UNK'
        _, crop = cv2.threshold(green, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        crop = mask[y1:y2, x1:x2]
        if crop.shape[0] < 5 or crop.shape[1] < 5:
            return 'UNK'

    best_label = 'UNK'
    best_score = OCR_CONFIDENCE

    # 1. Try whole-label matches (Fastest/Reliable for known labels)
    for label, tmpl_list in templates.items():
        for tmpl in tmpl_list:
            if tmpl.shape[0] > crop.shape[0] or tmpl.shape[1] > crop.shape[1]:
                continue
            try:
                result = cv2.matchTemplate(crop, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)
                if max_val > best_score:
                    best_score = max_val
                    best_label = label
            except:
                continue

    # 2. If no full label match, try character-by-character recognition
    if best_label == 'UNK' and _char_templates:
        best_label = _ocr_by_chars(crop)

    # Auto-save unknown contacts as template candidates
    if best_label == 'UNK' and crop is not None:
        _auto_save_template(crop)

    return best_label


def _ocr_by_chars(crop):
    """
    Perform OCR by segmenting the crop into individual characters and matching
    each against the character library.
    """
    if _char_templates is None:
        return 'UNK'

    # Find character blobs using contours
    contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Get bounding boxes and sort left-to-right
    boxes = []
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        if bw < 2 or bh < 2:
            continue
        # Filter artifacts (too thin or too small)
        if bw < 3 and bh < 5:
            continue
        boxes.append((x, y, bw, bh))

    if not boxes:
        return 'UNK'

    boxes.sort(key=lambda b: b[0])

    # Merge overlapping/close boxes
    merged = []
    for box in boxes:
        if merged and box[0] < merged[-1][0] + merged[-1][2] + 2:
            prev = merged[-1]
            x = min(prev[0], box[0])
            y = min(prev[1], box[1])
            x2 = max(prev[0] + prev[2], box[0] + box[2])
            y2 = max(prev[1] + prev[3], box[1] + box[3])
            merged[-1] = (x, y, x2 - x, y2 - y)
        else:
            merged.append(box)

    recognized = ""
    # Recognition threshold for individual characters might need to be lower
    char_threshold = OCR_CONFIDENCE * 0.82

    for x, y, bw, bh in merged:
        # Extract character blob
        char_blob = crop[y:y+bh, x:x+bw]

        best_char = '?'
        best_c_score = char_threshold

        # Standardize for comparison (pad/crop to 8x14 matching the library)
        # Reuse logic from build_char_lib for best results
        # 1. Pad/Scale char_blob to 8x14
        h, w = char_blob.shape
        scale = min(8.0/w, 14.0/h) if (w > 8 or h > 14) else 1.0
        if scale < 1.0:
            resized = cv2.resize(char_blob, (int(w*scale), int(h*scale)), interpolation=cv2.INTER_AREA)
        else:
            resized = char_blob
        
        rh, rw = resized.shape
        top, left = (14-rh)//2, (8-rw)//2
        processed_blob = cv2.copyMakeBorder(resized, top, 14-rh-top, left, 8-rw-left, cv2.BORDER_CONSTANT, value=0)

        for char, tmpls in _char_templates.items():
            for tmpl in tmpls:
                # Library images are 8x14
                try:
                    res = cv2.matchTemplate(processed_blob, tmpl, cv2.TM_CCOEFF_NORMED)
                    _, m_val, _, _ = cv2.minMaxLoc(res)
                    if m_val > best_c_score:
                        best_c_score = m_val
                        best_char = char
                except:
                    continue

        if best_char != '?':
            recognized += best_char
        else:
            # SAVE UNKNOWN CHARACTER BOLD BLOB
            # Only save if it has enough content to be a character (not just noise)
            if cv2.countNonZero(processed_blob) > 5:
                ts = int(time.time() * 1000) % 1000000
                unkn_path = os.path.join(_CHARS_DIR, f"unknown_{ts}.png")
                # Deduplication logic: check if we already saved a similar unknown
                already_saved = False
                for existing in os.listdir(_CHARS_DIR):
                    if existing.startswith("unknown_") and existing.endswith(".png"):
                        ex_img = cv2.imread(os.path.join(_CHARS_DIR, existing), cv2.IMREAD_GRAYSCALE)
                        if ex_img is not None and ex_img.shape == processed_blob.shape:
                            sim = cv2.matchTemplate(processed_blob, ex_img, cv2.TM_CCOEFF_NORMED)
                            if cv2.minMaxLoc(sim)[1] > 0.9:
                                already_saved = True
                                break
                if not already_saved:
                    cv2.imwrite(unkn_path, processed_blob)
                    print(f"[RWR] Unrecognized char saved: {unkn_path}")

    return recognized if len(recognized) >= 1 else 'UNK'


def _auto_save_template(crop):
    """Save an unrecognized contact crop for later labeling, with deduplication."""
    if not os.path.isdir(_TEMPLATES_DIR):
        os.makedirs(_TEMPLATES_DIR, exist_ok=True)

    # Skip if too little content (noise)
    nonzero = cv2.countNonZero(crop)
    total = crop.shape[0] * crop.shape[1]
    if total == 0 or nonzero / total < 0.10:
        return

    # Check if visually similar template already saved (dedup)
    for fname in os.listdir(_TEMPLATES_DIR):
        if not fname.lower().endswith('.png'):
            continue
        fpath = os.path.join(_TEMPLATES_DIR, fname)
        existing = cv2.imread(fpath, cv2.IMREAD_GRAYSCALE)
        if existing is None:
            continue
        # Resize to same shape for comparison
        if existing.shape != crop.shape:
            try:
                existing = cv2.resize(existing, (crop.shape[1], crop.shape[0]))
            except:
                continue
        try:
            result = cv2.matchTemplate(crop, existing, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(result)
            if max_val > 0.7:  # Already have a similar one
                return
        except:
            continue

    # Save with timestamp
    ts = int(time.time() * 1000) % 100000
    path = os.path.join(_TEMPLATES_DIR, f'new_{ts}.png')
    cv2.imwrite(path, crop)
    print(f"[RWR] New template saved: {path} (rename to correct label)")


def detect_rwr_contacts(image, center=None, radius=None):
    """
    Detect RWR contacts in the captured image.

    Args:
        image: BGR numpy array of the RWR region
        center: (cx, cy) pixel center of the RWR circle. Auto-detected if None.
        radius: pixel radius of the RWR circle. Auto-detected if None.

    Returns:
        list of dicts: [{'label': str, 'angle_deg': float, 'dist_ratio': float,
                         'cx': int, 'cy': int}]
        where angle_deg is clockwise from top (0° = nose/12 o'clock),
        dist_ratio is 0.0 (center) to 1.0 (outer ring)
    """
    if not RWR_AVAILABLE or image is None:
        return []

    h, w = image.shape[:2]

    # Auto-detect center as image center
    if center is None:
        center = (w // 2, h // 2)
    if radius is None:
        radius = min(w, h) // 2

    cx, cy = center

    # Convert to HSV and mask for green
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(RWR_GREEN_LOW), np.array(RWR_GREEN_HIGH))

    # Remove center crosshair / own-aircraft circle (larger exclusion zone)
    crosshair_r = max(33, int(radius * 0.32))
    cv2.circle(mask, (cx, cy), crosshair_r, 0, -1)

    # Remove outer ring border (the RWR circle itself and tick marks)
    # Create an annular mask: zero out everything outside 82% of radius
    outer_mask = np.zeros_like(mask)
    cv2.circle(outer_mask, (cx, cy), int(radius * MAX_DIST_RATIO), 255, -1)
    mask = cv2.bitwise_and(mask, outer_mask)

    # Morphological cleanup
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    contacts = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < MIN_CONTOUR_AREA or area > MAX_CONTOUR_AREA:
            continue

        # Compute centroid
        M = cv2.moments(contour)
        if M["m00"] == 0:
            continue
        cont_cx = int(M["m10"] / M["m00"])
        cont_cy = int(M["m01"] / M["m00"])

        # Distance from RWR center (pixels)
        dx = cont_cx - cx
        dy = cont_cy - cy
        pixel_dist = math.sqrt(dx * dx + dy * dy)

        # Skip if outside the usable area (border artifacts)
        if pixel_dist > radius * MAX_DIST_RATIO:
            continue

        # Skip if too close to the center (crosshair / own aircraft marker)
        if pixel_dist < radius * 0.05:
            continue

        # Distance ratio: 0 = center, 1 = outer ring
        dist_ratio = min(pixel_dist / radius, 1.0)

        # Angle: atan2 gives CCW from +X axis
        # We want CW from top (12 o'clock = 0°)
        # Screen coords: +Y is down, so:
        #   atan2(dx, -dy) gives CW angle from top
        angle_rad = math.atan2(dx, -dy)
        angle_deg = math.degrees(angle_rad) % 360

        contacts.append({
            'label': 'UNK',   # Will be refined by OCR or proximity grouping
            'angle_deg': angle_deg,
            'dist_ratio': dist_ratio,
            'cx': cont_cx,
            'cy': cont_cy,
            'area': area
        })

    # Sort contacts by area (largest first = most likely the label text blobs)
    contacts.sort(key=lambda c: c['area'], reverse=True)

    # Group nearby contacts (text characters of same label are close together)
    grouped = _group_nearby_contacts(contacts, radius)

    # OCR: identify labels for each grouped contact
    for contact in grouped:
        contact['label'] = _ocr_contact(mask, contact, (cx, cy), radius, image=image)

    return grouped


def _group_nearby_contacts(contacts, radius, group_radius_ratio=0.15):
    """
    Group nearby contours that likely belong to the same threat label.
    Returns one contact per group (using the centroid of the group).
    """
    if not contacts:
        return []

    group_dist = radius * group_radius_ratio
    groups = []
    used = [False] * len(contacts)

    for i, c in enumerate(contacts):
        if used[i]:
            continue

        group = [c]
        used[i] = True

        for j in range(i + 1, len(contacts)):
            if used[j]:
                continue
            dx = c['cx'] - contacts[j]['cx']
            dy = c['cy'] - contacts[j]['cy']
            if math.sqrt(dx * dx + dy * dy) < group_dist:
                group.append(contacts[j])
                used[j] = True

        # Compute group centroid
        avg_cx = sum(g['cx'] for g in group) / len(group)
        avg_cy = sum(g['cy'] for g in group) / len(group)
        total_area = sum(g['area'] for g in group)

        # Recalculate angle and distance from the group centroid
        center_x = contacts[0]['cx'] - contacts[0]['cx'] + (radius)  # We need actual center
        # Actually we need to recompute from the original center, not relative
        # The group members already have angle/dist computed from center

        # Use weighted average of angles (handle wraparound)
        sin_sum = sum(math.sin(math.radians(g['angle_deg'])) * g['area'] for g in group)
        cos_sum = sum(math.cos(math.radians(g['angle_deg'])) * g['area'] for g in group)
        avg_angle = math.degrees(math.atan2(sin_sum, cos_sum)) % 360

        avg_dist_ratio = sum(g['dist_ratio'] * g['area'] for g in group) / total_area

        groups.append({
            'label': 'UNK',
            'angle_deg': avg_angle,
            'dist_ratio': avg_dist_ratio,
            'cx': int(avg_cx),
            'cy': int(avg_cy),
            'area': total_area,
            'num_blobs': len(group)
        })

    return groups


# ─────────────────────────────────────────────
# Coordinate Inference
# ─────────────────────────────────────────────

def infer_map_position(contact, heading_deg, roll_deg, player_x, player_y,
                       map_min, map_max, max_range_m=None):
    """
    Convert an RWR contact's relative bearing and distance into absolute
    map coordinates (normalized 0-1 space used by War Thunder).

    Args:
        contact: dict with 'angle_deg' (CW from nose) and 'dist_ratio' (0-1)
        heading_deg: aircraft heading in degrees (0=N, CW)
        roll_deg: aircraft roll angle in degrees (positive = right wing down)
        player_x: player X in map coordinates (meters, from map_obj.json)
        player_y: player Y in map coordinates (meters, from map_obj.json)
        map_min: [min_x, min_y] from map_info.json
        map_max: [max_x, max_y] from map_info.json
        max_range_m: maximum display range in meters (defaults to DB value)

    Returns:
        dict with 'x', 'y' (normalized 0-1), 'bearing_abs', 'dist_m', 'label'
        or None on error
    """
    if map_min is None or map_max is None:
        return None
    if player_x is None or player_y is None:
        return None

    if max_range_m is None:
        max_range_m = get_display_max_range()

    try:
        # Note: War Thunder RWR display is horizon-stabilized.
        # It shows a top-down view — 12 o'clock = nose in horizontal plane.
        # Roll does NOT rotate the display, so no roll compensation needed.
        # The contact angle is already the correct bearing relative to the nose.
        corrected_angle = contact['angle_deg']

        # Convert to absolute bearing
        # heading_deg is the aircraft nose direction (true north CW)
        abs_bearing = (heading_deg + corrected_angle) % 360

        # Step 3: Estimate distance
        # Remap dist_ratio from the usable detection zone to actual range.
        # The center exclusion (~0.32r) maps to min_range (9250m),
        # the outer exclusion (~0.92r) maps to max_range (74000m).
        inner_ratio = 0.32  # matches crosshair_r / radius
        outer_ratio = MAX_DIST_RATIO  # 0.92
        min_range_m = get_display_min_range()

        effective_ratio = (contact['dist_ratio'] - inner_ratio) / (outer_ratio - inner_ratio)
        effective_ratio = max(0.0, min(1.0, effective_ratio))
        dist_m = min_range_m + effective_ratio * (max_range_m - min_range_m)

        # Step 4: Convert polar to Cartesian offset (meters)
        bearing_rad = math.radians(abs_bearing)

        # In War Thunder map coordinates:
        # X axis = East (positive)
        # Y axis = South (positive) — screen convention
        # So: dx = dist * sin(bearing), dy = dist * cos(bearing)
        # But Y is inverted (south = positive), so dy = -dist * cos(bearing)
        # Actually in WT map_obj.json, the coordinate system has:
        #   x increases left-to-right
        #   y increases top-to-bottom
        # And heading 0° = North = -Y direction
        dx_m = dist_m * math.sin(bearing_rad)
        dy_m = -dist_m * math.cos(bearing_rad)  # Negative because Y decreases going north

        # Step 5: Convert player position to meters, add offset
        world_w = map_max[0] - map_min[0]
        world_h = map_max[1] - map_min[1]

        if world_w <= 0 or world_h <= 0:
            return None

        # player_x, player_y are already in normalized coords (0-1) from map_obj.json
        # Convert to meters
        player_x_m = player_x * world_w + map_min[0]
        player_y_m = player_y * world_h + map_min[1]

        target_x_m = player_x_m + dx_m
        target_y_m = player_y_m + dy_m

        # Convert back to normalized
        target_x_norm = (target_x_m - map_min[0]) / world_w
        target_y_norm = (target_y_m - map_min[1]) / world_h

        return {
            'x': target_x_norm,
            'y': target_y_norm,
            'bearing_abs': abs_bearing,
            'dist_m': dist_m,
            'label': contact.get('label', 'UNK'),
            'type': get_threat_info(contact.get('label', 'UNK')).get('type', 'UNK'),
            'max_range_m': get_threat_info(contact.get('label', 'UNK')).get('max_range_m', max_range_m),
            'player_x': player_x,
            'player_y': player_y,
            'timestamp': time.time()
        }

    except Exception as e:
        print(f"[RWR] Inference error: {e}")
        return None


# ─────────────────────────────────────────────
# High-Level API (called by overlay.py)
# ─────────────────────────────────────────────

def scan_rwr(bbox, heading_deg, roll_deg, player_x, player_y, map_min, map_max):
    """
    Complete RWR scan pipeline: capture → detect → infer positions.

    Args:
        bbox: [x, y, w, h] screen region of the RWR display
        heading_deg: aircraft heading
        roll_deg: aircraft roll
        player_x, player_y: normalized player position (0-1)
        map_min, map_max: map bounds from map_info.json

    Returns:
        list of threat dicts with map coordinates
    """
    if not RWR_AVAILABLE:
        return []

    # Capture
    image = capture_rwr_region(bbox)
    if image is None:
        return []

    # Detect contacts
    contacts = detect_rwr_contacts(image)
    if not contacts:
        return []

    # Infer map positions
    threats = []
    for contact in contacts:
        pos = infer_map_position(
            contact, heading_deg, roll_deg,
            player_x, player_y,
            map_min, map_max
        )
        if pos is not None:
            threats.append(pos)

    return threats
