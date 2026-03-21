"""
Link18 Hardware Input Module
Handles optional hardware devices (like Joysticks/Flight Sticks) to provide dynamic analog inputs.
Currently used for analog FOV zoom scaling for the Velocity Vector.
"""
import os
import ctypes
from config import *

# Hide pygame support prompt
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame


class JoystickManager:
    """
    Manages connection and polling of gamepads/flight sticks via Pygame.
    Can be used to extract an analog axis value (e.g., a throttle slider) to drive zoom.
    """
    def __init__(self):
        self.enabled = ENABLE_JOYSTICK_ZOOM
        self.joystick = None
        self.axis_id = JOYSTICK_ZOOM_AXIS
        self.joystick_id = JOYSTICK_ID
        self.invert = JOYSTICK_ZOOM_INVERT
        self.deadzone = JOYSTICK_AXIS_DEADZONE
        
        self.current_zoom_axis_value = 0.0 # From -1.0 to 1.0

        if self.enabled:
            # Need to ensure window doesn't steal focus constantly. Pygame is just used for input here.
            pygame.display.init()
            pygame.joystick.init()
            self._connect_joystick()

    def _connect_joystick(self):
        joystick_count = pygame.joystick.get_count()
        if joystick_count == 0:
            if DEBUG_MODE:
                print("[JoystickManager] Enabled, but no joysticks found.")
            return

        if self.joystick_id < joystick_count:
            try:
                self.joystick = pygame.joystick.Joystick(self.joystick_id)
                self.joystick.init()
                if DEBUG_MODE:
                    print(f"[JoystickManager] Connected: {self.joystick.get_name()}")
                    print(f"[JoystickManager] Axes: {self.joystick.get_numaxes()}")
            except Exception as e:
                print(f"[JoystickManager] Failed to init joystick {self.joystick_id}: {e}")
        else:
            print(f"[JoystickManager] Error: Joystick ID {self.joystick_id} is out of range. Max is {joystick_count - 1}.")

    def poll(self):
        """
        Pump events and poll the configured axis.
        Returns the raw float value between -1.0 and 1.0.
        """
        if not self.enabled or not self.joystick:
            return 0.0
            
        pygame.event.pump()
        
        try:
            num_axes = self.joystick.get_numaxes()
            if self.axis_id < num_axes:
                raw_val = self.joystick.get_axis(self.axis_id)
                
                # Apply deadzone
                if abs(raw_val) < self.deadzone:
                    raw_val = 0.0
                else:
                    # Rescale so past the deadzone it ramps smoothly from 0 to 1
                    sign = 1.0 if raw_val > 0 else -1.0
                    raw_val = sign * ((abs(raw_val) - self.deadzone) / (1.0 - self.deadzone))
                
                if self.invert:
                    raw_val = -raw_val
                    
                self.current_zoom_axis_value = raw_val
            
            return self.current_zoom_axis_value
        except Exception as e:
            if DEBUG_MODE:
                print(f"[JoystickManager] Poll error: {e}")
            return 0.0

    def get_zoom_interpolation_factor(self):
        """
        Converts the polled [-1.0, 1.0] axis value to a [0.0, 1.0] interpolation factor.
        -1.0 translates to 0.0 (Normal FOV)
        1.0 translates to 1.0 (Zoomed FOV)
        """
        if not self.enabled or not self.joystick:
            return None # Return None to indicate joystick is inactive/not overriding
            
        val = self.poll()
        # Map [-1.0, 1.0] to [0.0, 1.0]
        factor = (val + 1.0) / 2.0
        # Clamp just in case
        return max(0.0, min(1.0, factor))

    def cleanup(self):
        if self.enabled:
            if self.joystick:
                self.joystick.quit()
            pygame.joystick.quit()
