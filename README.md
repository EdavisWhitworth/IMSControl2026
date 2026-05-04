# Ion Mobility Spectrometer Control

Python + PyQt5 application for controlling an ion mobility spectrometer acquisition workflow with NI USB-6351.

## Features
- Configure pulse width, experiment length, data points, averages, and total iterations
- Start/stop during acquisition
- 1D line plot for current or prior iterations
- 2D colormap across all iterations
- Save/load experiment data to CSV and HDF5

## Quick Start
1. Install Python 3.10+
2. Install NI-DAQmx driver (for hardware mode)
3. Install dependencies:
   - `pip install -r requirements.txt`
4. Run:
   - `python -m ims_control.main`

## Notes
- If NI hardware/driver is unavailable, the app can run in simulation mode.
- Default values are tuned for typical IMS runs (50 ms, 4000 points).
