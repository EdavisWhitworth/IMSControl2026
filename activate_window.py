#!/usr/bin/env python3
"""Bring the IMS Control window to the foreground using ctypes."""

import ctypes
import time

# Windows API constants
SW_RESTORE = 9
WM_ACTIVATEAPP = 0x001C

try:
    # Load user32.dll
    user32 = ctypes.windll.user32
    
    # Find the window
    hwnd = user32.FindWindowW(None, "IMS Control")
    
    if hwnd:
        print(f"Found IMS Control window (handle: {hwnd})")
        
        # Check if minimized and restore if needed
        if user32.IsIconic(hwnd):
            print("Window is minimized, restoring...")
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.5)
        
        # Bring to foreground
        print("Bringing window to foreground...")
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        
        # Also try to show the window
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        
        print("✓ Successfully activated IMS Control window!")
        print("  The application window should now be visible on your screen.")
    else:
        print("✗ IMS Control window not found")
        print("  The application may not be running or the window may have been closed.")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
