# Ion Mobility Spectrometer Control

Python + PyQt5 application for controlling an ion mobility spectrometer acquisition workflow with NI USB-6351 or USB-6341.

## Features
- Configure pulse width, experiment length, data points, averages, and total iterations
- Start/stop during acquisition
- 1D line plot for current or prior iterations
- 2D colormap across all iterations
- Save/load experiment data to CSV and HDF5
- Support for USB-6351 and USB-6341 devices

## Quick Start
1. Install Python 3.10+
2. Install NI-DAQmx driver (for hardware mode)
3. Install dependencies:
   - `pip install -r requirements.txt`
4. Run:
   - `python -m ims_control.main`

## Hardware Configuration

### USB-6351
Default configuration for analog input and counter output channels.

### USB-6341
For USB-6341 devices, configure the following in the Experiment Settings dialog:
- **AI Channel**: e.g., `Dev1/ai0` (check your device name in NI-MAX)
- **Counter Channel**: e.g., `Dev1/ctr0` 
- **PFI Trigger**: e.g., `Dev1/PFI0`

To find your device name, use NI-MAX (Measurement & Automation Explorer) or check the error messages for available channels.

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
