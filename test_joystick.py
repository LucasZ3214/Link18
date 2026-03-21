"""
Link18 Joystick Test Utility
Run this script standalone to discover your joystick ID and axis mappings.
It will print out available joysticks and stream their axis values.
"""
import os
import sys
import time

# Hide pygame support prompt
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

def print_axis_levels(joystick):
    num_axes = joystick.get_numaxes()
    out = ""
    for i in range(num_axes):
         val = joystick.get_axis(i)
         out += f"Axis {i}: {val:7.3f} | "
    return out

def main():
    pygame.display.init()
    pygame.joystick.init()
    
    count = pygame.joystick.get_count()
    if count == 0:
        print("No joysticks found.")
        sys.exit(0)
        
    print(f"Found {count} joystick(s):")
    joysticks = []
    for i in range(count):
        j = pygame.joystick.Joystick(i)
        j.init()
        joysticks.append(j)
        print(f"  [{i}] {j.get_name()} (Axes: {j.get_numaxes()}, Buttons: {j.get_numbuttons()})")
        
    print("\nSelect Joystick ID to test (default 0): ", end="")
    try:
        choice = input()
        choice_id = int(choice) if choice.strip() else 0
    except ValueError:
        choice_id = 0
        
    if choice_id < 0 or choice_id >= count:
        print("Invalid ID.")
        sys.exit(1)
        
    test_joy = pygame.joystick.Joystick(choice_id)
    test_joy.init()
    print(f"\nTesting: {test_joy.get_name()}")
    print("Move your axes (throttle/slider) to identify its ID. Press Ctrl+C to stop.\n")
    
    try:
        while True:
            pygame.event.pump()
            vals = print_axis_levels(test_joy)
            # Use carriage return to overwrite the line
            sys.stdout.write('\r' + vals)
            sys.stdout.flush()
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nTest stopped.")
    finally:
        pygame.joystick.quit()
        pygame.quit()

if __name__ == "__main__":
    main()
