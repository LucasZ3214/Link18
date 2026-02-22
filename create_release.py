import zipfile
import os
import shutil
import json
import subprocess
from config import VERSION_TAG

def build_executable():
    print("Building Executable with PyInstaller...")
    
    cmd = ["pyinstaller", "--onefile", "--noconsole", "--name", "Link18", "main.py"]
    
    if os.path.exists("icon.ico"):
        cmd.append("--icon=icon.ico")
        
    try:
        subprocess.run(cmd, check=True)
        print("  Build successful.")
        return True
    except subprocess.CalledProcessError:
        print("  [ERROR] Build failed!")
        return False
    except FileNotFoundError:
        import sys
        # fallback for venv
        pyinstaller_path = os.path.join(os.path.dirname(sys.executable), "pyinstaller.exe")
        if os.path.exists(pyinstaller_path):
             cmd[0] = pyinstaller_path
             try:
                subprocess.run(cmd, check=True)
                print("  Build successful (using venv path).")
                return True
             except:
                 print("  [ERROR] Build failed even with full path!")
                 return False
        print("  [ERROR] PyInstaller not found. Is it installed?")
        return False

def create_release():
    release_name = f"Link18_{VERSION_TAG}.zip"
    
    # 0. Build
    if not build_executable():
        return

    # 1. Create Sanitized Config
    print("Preparing sanitized config...")
    try:
        with open("config.json", "r") as f:
            data = json.load(f)
            
        # Modifying for template
        data['callsign'] = "YOUR_CALLSIGN_HERE"
        data['color'] = "#00FF00"  # Default Green
        data['distance_unit'] = "km"  # Default to Kilometers
        
        with open("config_release_temp.json", "w") as f:
            json.dump(data, f, indent=4)
            
        print("  Config sanitized (Callsign/Color reset).")
        
    except Exception as e:
        print(f"Error preparing config: {e}")
        return

    exe_path = "dist/Link18.exe"
    if not os.path.exists(exe_path):
        print(f"  [ERROR] {exe_path} not found after build!")
        return

    files_to_include = [
        (exe_path, "Link18.exe"),
        ("config_release_temp.json", "config.json"),
        ("README.md", "README.md"),
        ("vehicles.json", "vehicles.json")
    ]
    
    print(f"Creating {release_name}...")
    
    try:
        with zipfile.ZipFile(release_name, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add files
            for source, arcname in files_to_include:
                if os.path.exists(source):
                    print(f"  Adding {source} as {arcname}")
                    zipf.write(source, arcname)
                else:
                    print(f"  [WARNING] Missing file: {source}")
            
            # Add web folder recursively
            if os.path.exists("web"):
                print("  Adding web/ directory...")
                for root, dirs, files in os.walk("web"):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)
            
            # Add sounds folder (exclude welcome/ user sounds)
            if os.path.exists("sounds"):
                print("  Adding sounds/ directory...")
                for root, dirs, files in os.walk("sounds"):
                    # Skip user welcome sounds
                    if "welcome" in root:
                        continue
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, ".")
                        zipf.write(file_path, arcname)
                    
        print(f"\nSuccess! Share '{release_name}' with your squad.")
        print("Note: The zip contains a template config.json.")
        
    except Exception as e:
        print(f"Error creating zip: {e}")
    finally:
        # Cleanup temp file
        if os.path.exists("config_release_temp.json"):
            os.remove("config_release_temp.json")

if __name__ == "__main__":
    create_release()
