import zipfile
import os
import shutil
import json

def create_release():
    release_name = "Link18_v1.3.zip"
    
    # 1. Create Sanitized Config
    print("Preparing sanitized config...")
    try:
        with open("config.json", "r") as f:
            data = json.load(f)
            
        # Modifying for template
        data['callsign'] = "YOUR_CALLSIGN_HERE"
        data['color'] = "#00FF00"  # Default Green
        data['distance_unit'] = "km"  # Default to Kilometers
        # Keep IP/Port/Key settings as requested
        
        with open("config_release_temp.json", "w") as f:
            json.dump(data, f, indent=4)
            
        print("  Config sanitized (Callsign/Color reset).")
        
    except Exception as e:
        print(f"Error preparing config: {e}")
        return

    exe_path = "dist/Link18.exe"
    if not os.path.exists(exe_path):
        if os.path.exists("Link18.exe"):
            exe_path = "Link18.exe"
            print("  Found Link18.exe in root directory.")
        else:
            print("  [ERROR] Link18.exe not found in dist/ or root!")
            return

    files_to_include = [
        (exe_path, "Link18.exe"),
        ("config_release_temp.json", "config.json"), # Rename in zip
        ("README.md", "README.md"),
        ("web/dashboard.html", "web/dashboard.html"),
        ("vehicles.json", "vehicles.json")
    ]
    
    print(f"Creating {release_name}...")
    
    try:
        with zipfile.ZipFile(release_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for source, arcname in files_to_include:
                if os.path.exists(source):
                    print(f"  Adding {source} as {arcname}")
                    zipf.write(source, arcname)
                else:
                    print(f"  [WARNING] Missing file: {source}")
                    
        print(f"\nSuccess! Share '{release_name}' with your squad.")
        print("Note: The zip contains a template config.json (IP/Port preserved).")
        
    except Exception as e:
        print(f"Error creating zip: {e}")
    finally:
        # Cleanup temp file
        if os.path.exists("config_release_temp.json"):
            os.remove("config_release_temp.json")

if __name__ == "__main__":
    create_release()
