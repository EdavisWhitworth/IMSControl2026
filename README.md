# Ion Mobility Spectrometer Control

Python + PyQt5 application for controlling an ion mobility spectrometer acquisition workflow with NI USB-6351 or USB-6341.

## Features
- Configure pulse width, experiment length, data points, averages, and total iterations
- Configure external HV control for IMS and Ionization Source power supplies
- Start/stop during acquisition
- Independent latched HV enable button (separate from Start)
- 1D line plot for current or prior iterations
- 2D colormap across all iterations
- Save/load experiment data to CSV and HDF5
- Support for USB-6351 and USB-6341 devices

## External HV Control
- Open HV parameters with the HV Settings button.
- Configure AO channels for IMS and Ionization Source plus one DO line for HV enable.
- Define IMS max output (kV), control voltage max (V), IMS setpoint (kV), and Ionization bias (kV).
- Ionization Source is computed as IMS setpoint + Ionization bias.
- The AO mapping is linear:
   - IMS AO = (IMS setpoint / IMS max output) * control voltage max
   - Ionization AO = ((IMS setpoint + Ionization bias) / IMS max output) * control voltage max
- HV ON sets the DO line to TRUE and window background to red.
- HV OFF sets both AO lines to 0 V, DO line to FALSE, and window background to green.
- HV settings can be saved to a default JSON file from the HV parameters dialog.

## Requirements

### System Requirements
- **Windows 10/11** (NI-DAQmx drivers are Windows-only)
- **Python 3.9 or later** (download from [python.org](https://www.python.org/downloads/))
- **Visual C++ Redistributable** (required by PyQt5; usually pre-installed on Windows)

### Optional
- **NI-DAQmx Runtime** (for USB-6351/6341 hardware mode)
  - Download from [ni.com/downloads](https://www.ni.com/downloads)
  - If not installed, the application will run in **simulation mode** (no hardware communication)
- **NI-MAX** (Measurement & Automation Explorer) - useful for verifying device configuration

## Quick Start

### First Time Setup (Automatic)
1. Download and install **Python 3.9 or later** from [python.org](https://www.python.org/downloads/)
   - Ensure "Add Python to PATH" is checked during installation
2. Clone or extract this repository
3. **Double-click `setup_env.bat`** in the repository root
   - This will create a Python virtual environment and install all dependencies
   - A command window will appear; press any key when setup is complete

### Running the Application
- **Double-click `Launch-IMSControl.cmd`** to start the application

### Command Line (Advanced)
If you prefer to run from a terminal:
```batch
.venv\Scripts\python.exe -m ims_control.main
```

Or, after activating the virtual environment:
```batch
.venv\Scripts\activate
imscontrol
```

## Hardware Configuration

### USB-6351
Default configuration for analog input and counter output channels.

### USB-6341
For USB-6341 devices, configure the following in the Experiment Settings dialog:
- **AI Channel**: e.g., `Dev1/ai0` (check your device name in NI-MAX)
- **Counter Channel**: e.g., `Dev1/ctr0` 
- **PFI Trigger**: e.g., `Dev1/PFI0`

To find your device name, use NI-MAX (Measurement & Automation Explorer) or check the error messages for available channels.

### Troubleshooting Setup Issues

**Python not found in PATH:**
- Reinstall Python from [python.org](https://www.python.org/downloads/)
- During installation, **check "Add Python to PATH"** before clicking Install
- Restart your computer or restart your terminal

**setup_env.bat fails to install dependencies:**
- Check your internet connection
- Ensure you have at least 500 MB free disk space
- If the error mentions "qmake," you may have a PyQt5 build issue
  - Delete the `.venv` folder and try again
  - If it persists, contact the development team

### Hardware Fallback Mode

If NI-DAQmx is not installed, the application will run in **simulation mode**:
- All hardware operations are simulated with realistic timing
- No physical hardware required
- Useful for testing and development
- A message will appear in the status bar or logs indicating simulation mode is active

To use actual hardware, install **NI-DAQmx Runtime** from [ni.com/downloads](https://www.ni.com/downloads).

### Troubleshooting "Access Violation" Errors

If you see "access violation reading 0x0000000000000000" error:

1. **Try Simulation Mode First**
   - Open Experiment Settings
   - Check "Use simulation mode"
   - Click OK to test if the configuration is correct

2. **Update NI-DAQmx Drivers**
   - The error may indicate an older or incompatible driver version
   - Visit [ni.com/downloads](https://www.ni.com/downloads) and install the latest NI-DAQmx runtime

3. **Verify Device Configuration**
   - Open NI-MAX (Measurement & Automation Explorer)
   - Confirm your device appears and has available channels
   - Test the device connection with NI-MAX's built-in tools

4. **Try Different Counter Channel**
   - Some USB-6341 units may have issues with specific counter channels
   - Try `Dev1/ctr1` or `Dev1/ctr2` instead of `Dev1/ctr0`

5. **Use External Trigger (Advanced)**
   - If counter output continues to fail, configure hardware for external triggering
   - Contact NI support for device-specific configuration guidance
