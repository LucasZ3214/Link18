import mss
import mss.tools
import numpy as np
import cv2
import json
import time
from PIL import Image, ImageDraw

def auto_calibrate_map_v2(window=None):
    """
    Robust map calibration using line detection (v2).
    Scans for the specific grey border color of the War Thunder map.
    """
    
    print("[CALIBRATE] Starting v2 map calibration...")
    
    # 1. Capture Screen
    with mss.mss() as sct:
        monitor = sct.monitors[1] # Primary monitor
        screenshot = sct.grab(monitor)
        img = np.array(screenshot)
        
    # Convert BGRA to BGR for OpenCV
    img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    
    # 2. Convert to HSV
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    
    # 3. Define Map Border Color (Grey) in HSV
    # Target: War Thunder Border Grey #6A6D6F -> RGB(106, 109, 111) -> HSV(105, 11, 111)
    # We define a generous tolerance around this specific grey
    
    # Target V=111. Tolerance +/- 40 -> 71 to 151
    # Target S=11. Tolerance + 20 -> 0 to 31
    # H is ignored for grey (0-180)
    
    lower_grey = np.array([0, 0, 75])      # H, S, V (Min brightness 75)
    upper_grey = np.array([180, 40, 150])  # H, S, V (Max brightness 150, Low Saturation)
    
    print(f"[DEBUG] Color Target: S(0-40), V(75-150) (Assuming War Thunder Grey #6A6D6F)")
    
    # 4. Create Mask
    mask = cv2.inRange(hsv, lower_grey, upper_grey)
    
    # Morphological operations to close gaps in the border
    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # DEBUG: Save mask
    cv2.imwrite("debug_calibration_mask.png", mask)
    cv2.imwrite("debug_calibration_original.png", img_bgr)
    print("[DEBUG] Saved debug_calibration_mask.png and debug_calibration_original.png")
    
    # Setup annotation image
    debug_img = img_bgr.copy()
    
    # 5. Use OpenCV Contours to find the map box
    # This is much faster and more robust than manual pixel scanning
    print("[CALIBRATE] Finding contours...")
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # Collect all potential boxes (bounding rects)
    boxes = []
    min_fragment_size = 50 # Capture smaller fragments too
    
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w >= min_fragment_size and h >= min_fragment_size:
            boxes.append({'x': x, 'y': y, 'w': w, 'h': h, 'r': x+w, 'b': y+h})
            # Draw raw fragments in Yellow
            cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 255), 1)

    print(f"[CALIBRATE] Found {len(boxes)} initial fragments")
    
    # Merge Aligned Boxes Loop
    merged_occurred = True
    while merged_occurred:
        merged_occurred = False
        new_boxes = []
        used_indices = set()
        
        for i in range(len(boxes)):
            if i in used_indices: continue
            
            # Start with box i
            b_merged = boxes[i].copy()
            used_indices.add(i)
            
            # Try to merge with any other unused box
            # We restart internal loop if a merge happens to aggregate everything possible
            local_merge = True
            while local_merge:
                local_merge = False
                for j in range(len(boxes)):
                    if j in used_indices: continue
                    
                    b2 = boxes[j]
                    
                    # Alignment Tolerances
                    align_tol = 10 # Pixels (for edges)
                    gap_tol = 20   # Pixels (for gap between boxes)
                    
                    # Check Alignment & Proximity
                    
                    # Horizontal Relationship (Side-by-Side)
                    # Tops align OR Bottoms align
                    top_align = abs(b_merged['y'] - b2['y']) < align_tol
                    bot_align = abs(b_merged['b'] - b2['b']) < align_tol
                    # Close horizontally?
                    x_gap = max(0, b_merged['x'] - b2['r'], b2['x'] - b_merged['r'])
                    horz_close = x_gap < gap_tol
                    
                    # Vertical Relationship (Stacked)
                    # Lefts align OR Rights align
                    left_align = abs(b_merged['x'] - b2['x']) < align_tol
                    right_align = abs(b_merged['r'] - b2['r']) < align_tol
                    # Close vertically?
                    y_gap = max(0, b_merged['y'] - b2['b'], b2['y'] - b_merged['b'])
                    vert_close = y_gap < gap_tol
                    
                    # Intersection/Containment (Always merge)
                    intersects = (b_merged['x'] < b2['r'] and b_merged['r'] > b2['x'] and
                                  b_merged['y'] < b2['b'] and b_merged['b'] > b2['y'])
                    
                    should_merge = False
                    
                    # Case 1: Strictly Aligned Edges (User Request)
                    # If edges align and they are essentially "part of the same row/col"
                    if (top_align and bot_align and horz_close): should_merge = True
                    elif (left_align and right_align and vert_close): should_merge = True
                    
                    # Case 2: Corner pieces merging? 
                    # If we have a top bar and right bar, they don't 'align' per se but touch at a corner.
                    # Simple intersection/proximity check might cover this if mask is continuous enough.
                    # Or if we just trust intersection/gap without strict edge alignment for corner pieces?
                    # Let's check generally if they are close enough to be one object.
                    elif x_gap < gap_tol and y_gap < gap_tol: 
                        # This is broader: merges anything close. May be safer for broken frames.
                        should_merge = True
                        
                    if should_merge:
                        # MERGE
                        b_merged['x'] = min(b_merged['x'], b2['x'])
                        b_merged['y'] = min(b_merged['y'], b2['y'])
                        b_merged['r'] = max(b_merged['r'], b2['r'])
                        b_merged['b'] = max(b_merged['b'], b2['b'])
                        b_merged['w'] = b_merged['r'] - b_merged['x']
                        b_merged['h'] = b_merged['b'] - b_merged['y']
                        
                        used_indices.add(j)
                        local_merge = True # Keep checking against others with this new bigger box
                        merged_occurred = True
            
            new_boxes.append(b_merged)
            
        boxes = new_boxes
        if merged_occurred:
            print(f"[CALIBRATE] Merged round... count: {len(boxes)}")

    # Find best candidate
    found_box = False
    map_x, map_y, map_w, map_h = 0, 0, 0, 0
    min_map_size = 800 # User requested > 800px
    
    # Sort by size (area) to prioritize the big box
    boxes.sort(key=lambda b: b['w'] * b['h'], reverse=True)
    
    for b in boxes:
        # Draw merged boxes in Blue
        cv2.rectangle(debug_img, (b['x'], b['y']), (b['r'], b['b']), (255, 0, 0), 2)
        
        w, h = b['w'], b['h']
        
        # Check size constraints
        if w >= min_map_size and h >= min_map_size:
            # Check aspect ratio (Square-ish)
            aspect = float(w) / h
            if 0.85 <= aspect <= 1.15:
                # Valid Map!
                print(f"[CALIBRATE] Found Valid Map: {w}x{h} at ({b['x']},{b['y']})")
                
                # Enforce Square
                size = min(w, h)
                center_x = b['x'] + w // 2
                center_y = b['y'] + h // 2
                
                map_w = size
                map_h = size
                map_x = center_x - size // 2
                map_y = center_y - size // 2
                
                # Draw final result in Green
                cv2.rectangle(debug_img, (map_x, map_y), (map_x+map_w, map_y+map_h), (0, 255, 0), 3)
                
                found_box = True
                break
            else:
                print(f"[CALIBRATE] Rejecting large box (Bad Aspect): {w}x{h} R={aspect:.2f}")

    # Save annotated debug image
    cv2.imwrite("debug_calibration_annotated.png", debug_img)
    print(f"[DEBUG] Saved debug_calibration_annotated.png")
            
    if found_box:
        print(f"[CALIBRATE] Success! Map Area: {map_w}x{map_h} at ({map_x},{map_y})")
        
        # Update Config
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
        except:
            config = {}
            
        config['map_offset_x'] = int(map_x)
        config['map_offset_y'] = int(map_y)
        config['map_width'] = int(map_w)
        config['map_height'] = int(map_h)
        
        with open('config.json', 'w') as f:
            json.dump(config, f, indent=4)
            
        # Update Runtime Globals (New Architecture)
        try:
            import config
            config.CONFIG['map_offset_x'] = int(map_x)
            config.CONFIG['map_offset_y'] = int(map_y)
            config.CONFIG['map_width'] = int(map_w)
            config.CONFIG['map_height'] = int(map_h)
            # Update module level constants for any new imports
            config.MAP_OFFSET_X = int(map_x)
            config.MAP_OFFSET_Y = int(map_y)
            config.MAP_WIDTH = int(map_w)
            config.MAP_HEIGHT = int(map_h)
            print("[CALIBRATE] Updated config.CONFIG and config constants")
        except Exception as e:
            print(f"[CALIBRATE] Warning: Could not update config module: {e}")

        if window:
            # Trigger a repaint/update
            window.update()
            
        return True
    else:
        print(f"[CALIBRATE] Failed - No map border found > {min_map_size}px")
        if window:
            window.calibration_status = "Failed: No Border > 800px"
        return False
