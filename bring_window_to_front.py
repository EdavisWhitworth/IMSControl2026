#!/usr/bin/env python3
"""Bring the IMS Control window to the foreground."""

import sys
import time
import subprocess

try:
    import pygetwindow
    import pyautogui
except ImportError:
    print("Installing required packages...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pygetwindow", "pyautogui"])
    import pygetwindow
    import pyautogui

def bring_ims_control_to_front():
    """Find and activate the IMS Control window."""
    print("Looking for IMS Control window...")
    windows = pygetwindow.getWindowsWithTitle("IMS Control")
    
    if not windows:
        print("IMS Control window not found!")
        print("Available windows:")
        for w in pygetwindow.getAllWindows():
            if w.title:
                print(f"  - {w.title}")
        return False
    
    window = windows[0]
    print(f"Found IMS Control window: {window.title}")
    print(f"  Position: ({window.left}, {window.top})")
    print(f"  Size: {window.width}x{window.height}")
    
    try:
        print("Bringing window to front...")
        window.activate()
        time.sleep(0.5)
        
        # Also try to move it to the primary display
        if window.left < 0 or window.top < 0:
            print("Window is off-screen, moving to primary display...")
            window.moveTo(50, 50)
            window.resizeTo(1400, 800)
        
        print("✓ Window activated successfully!")
        return True
    except Exception as e:
        print(f"✗ Failed to activate window: {e}")
        return False

if __name__ == "__main__":
    success = bring_ims_control_to_front()
    sys.exit(0 if success else 1)
