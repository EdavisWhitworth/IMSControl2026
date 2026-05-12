#!/usr/bin/env python
"""Test script to diagnose GUI issues."""

import sys
import os
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))
os.environ["PYTHONPATH"] = str(src_path)

print("Testing PyQt5 imports...")
try:
    from PyQt5.QtWidgets import QApplication, QMainWindow, QPushButton
    print("✓ PyQt5 imported successfully")
except ImportError as e:
    print(f"✗ PyQt5 import failed: {e}")
    sys.exit(1)

print("\nTesting display...")
try:
    app = QApplication(sys.argv)
    print("✓ QApplication created")
except Exception as e:
    print(f"✗ QApplication creation failed: {e}")
    sys.exit(1)

print("\nTesting MainWindow import...")
try:
    from ims_control.ui.main_window import MainWindow
    print("✓ MainWindow imported")
except Exception as e:
    print(f"✗ MainWindow import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nTesting MainWindow creation...")
try:
    window = MainWindow()
    print("✓ MainWindow created")
    print(f"  Window title: {window.windowTitle()}")
    print(f"  Window size: {window.width()}x{window.height()}")
except Exception as e:
    print(f"✗ MainWindow creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nShowing window...")
try:
    window.show()
    print("✓ Window shown")
    print(f"  Window visible: {window.isVisible()}")
    print(f"  Window geometry: {window.geometry()}")
except Exception as e:
    print(f"✗ Window show failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nEntering event loop...")
print("(Window should be visible on screen)")
sys.exit(app.exec_())
