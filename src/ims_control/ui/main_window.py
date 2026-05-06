from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QThread, QTimer, QRectF, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ims_control.acquisition.worker_thread import AcquisitionWorker
from ims_control.data_model.experiment import ExperimentConfig, ExperimentData, HVPowerConfig, OperationMode
from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller
from ims_control.io.export_import import ExperimentExporter, ExperimentImporter
from ims_control.ui.config_dialog import ExperimentConfigDialog
from ims_control.ui.hv_config_dialog import HVConfigDialog


class HVOutputWorker(QThread):
    applied = pyqtSignal(bool, float, float)
    failed = pyqtSignal(str)

    def __init__(self, payload: dict[str, object], timeout_seconds: float = 8.0) -> None:
        super().__init__()
        self.payload = payload
        self.timeout_seconds = float(timeout_seconds)
        self._proc: subprocess.Popen[str] | None = None

    def request_stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        try:
            src_dir = Path(__file__).resolve().parents[2]
            cmd = [
                sys.executable,
                "-m",
                "ims_control.acquisition.hv_cli",
                "--payload",
                json.dumps(self.payload, separators=(",", ":")),
            ]

            env = os.environ.copy()
            existing_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = str(src_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

            self._proc = subprocess.Popen(
                cmd,
                cwd=str(src_dir.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            stdout_text, stderr_text = self._proc.communicate(timeout=self.timeout_seconds)
            exit_code = self._proc.returncode

            if exit_code != 0:
                error = stderr_text.strip() or "HV subprocess failed"
                for line in reversed(stdout_text.splitlines()):
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(event, dict) and event.get("ok") is False:
                        error = str(event.get("error", error))
                        break
                self.failed.emit(error)
                return

            event = None
            for line in reversed(stdout_text.splitlines()):
                try:
                    candidate = json.loads(line)
                except Exception:
                    continue
                if isinstance(candidate, dict):
                    event = candidate
                    break

            if not isinstance(event, dict) or event.get("ok") is not True:
                self.failed.emit("HV subprocess returned no valid success payload")
                return

            self.applied.emit(bool(event.get("enabled", False)), float(event.get("ims_v", 0.0)), float(event.get("ion_v", 0.0)))
        except subprocess.TimeoutExpired:
            self.request_stop()
            self.failed.emit("HV subprocess timed out while writing NI outputs")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self._proc = None


class MainWindow(QMainWindow):
    DEFAULT_CONFIG_PATH = Path.home() / ".ims_control_defaults.json"
    DEFAULT_HV_CONFIG_PATH = Path.home() / ".ims_control_hv_defaults.json"
    DEFAULT_USER_PARAMS_PATH = Path.home() / ".ims_control_user_params_defaults.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IMS Control")
        self.resize(1500, 780)

        self.config = self._load_default_config()
        self.user_param_defaults = self._load_default_user_params()
        self.hv_config = self._load_default_hv_config()
        self.hv_enabled = False
        self.hv_worker: HVOutputWorker | None = None
        self._pending_hv_enabled = False
        self._pending_hv_ims_v = 0.0
        self._pending_hv_ion_v = 0.0
        self.experiment_data = ExperimentData(self.config)
        self.worker: AcquisitionWorker | None = None
        self._heat_levels_initialized = False
        self._current_line_x = np.array([], dtype=np.float64)
        self._current_line_y = np.array([], dtype=np.float64)
        self._line_cursor_locked = False
        self._selected_cursor_locked = False
        self._heat_cursor_locked = False
        self._heat_row_count = 0
        self._heat_matrix = np.empty((0, 0), dtype=np.float64)
        self._selected_heat_iteration_index = None
        self._selected_line_x = np.array([], dtype=np.float64)
        self._selected_line_y = np.array([], dtype=np.float64)
        self._axis_controls: dict[str, dict[str, object]] = {}
        self._current_cursor_x = 0.0
        self.line_baseline_curve = None
        self.selected_baseline_curve = None
        self._selected_plot_update_queued = False
        self._pending_selected_iteration_index: int | None = None
        self._time_axis_cache = np.array([], dtype=np.float64)
        self._heat_z_min: float | None = None
        self._heat_z_max: float | None = None
        self._heat_max_display_pixels = 2_500_000

        # Parameter spinboxes for Ko calculation
        self.pressure_spinbox: QDoubleSpinBox | None = None
        self.temperature_spinbox: QDoubleSpinBox | None = None
        self.length_spinbox: QDoubleSpinBox | None = None
        self.voltage_spinbox: QDoubleSpinBox | None = None
        self.gate_v_multiplier_spinbox: QDoubleSpinBox | None = None
        self.ko_label: QLabel | None = None
        self.noise_start_spinbox: QDoubleSpinBox | None = None
        self.noise_end_spinbox: QDoubleSpinBox | None = None
        self.resolving_power_label: QLabel | None = None
        self.snr_label: QLabel | None = None
        self.hv_state_readout_label: QLabel | None = None
        self.hv_ims_readout_label: QLabel | None = None
        self.hv_ion_readout_label: QLabel | None = None
        self.hv_ims_kv_readout_label: QLabel | None = None
        self.hv_ion_kv_readout_label: QLabel | None = None
        self.hardware_params_label: QLabel | None = None
        self.btn_save_user_params_defaults: QPushButton | None = None

        # FTIMS-specific attributes
        self._ftims_raw_time_domain_data: dict[float, np.ndarray] = {}  # freq -> time-domain signal
        self._ftims_current_frequency_hz: float | None = None
        self._ftims_current_average_count: int = 0
        self._ftims_total_averages: int = 0
        self.ftims_frequency_selector: QComboBox | None = None
        self.ftims_raw_plot: pg.PlotWidget | None = None
        self.ftims_raw_curve: Any | None = None
        self.ftims_raw_cursor_v: pg.InfiniteLine | None = None
        self.ftims_raw_cursor_h: pg.InfiniteLine | None = None
        self.plot_tabs: QTabWidget | None = None

        self._line_peak_region: pg.LinearRegionItem | None = None
        self._line_fwhm_left: pg.InfiniteLine | None = None
        self._line_fwhm_right: pg.InfiniteLine | None = None
        self._selected_peak_region: pg.LinearRegionItem | None = None
        self._selected_fwhm_left: pg.InfiniteLine | None = None
        self._selected_fwhm_right: pg.InfiniteLine | None = None

        self._build_ui()
        self._refresh_config_label()
        self._update_hv_status_label(ims_v=0.0, ion_v=0.0)
        self._apply_hv_background(False)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QGridLayout(central)
        root.setColumnStretch(0, 0)
        root.setColumnStretch(1, 3)
        self.setCentralWidget(central)

        control_box = QGroupBox("Control")
        control_box.setMinimumWidth(430)
        control_box.setMaximumWidth(430)
        control_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        control_layout = QVBoxLayout(control_box)

        row1 = QHBoxLayout()
        self.btn_edit = QPushButton("Edit Settings")
        self.btn_hv_settings = QPushButton("HV Settings")
        self.btn_hv_enable = QPushButton("HV OFF")
        self.btn_hv_enable.setCheckable(True)
        self.btn_hv_update = QPushButton("Update HV Values")
        self.btn_hv_update.setEnabled(False)
        self.btn_hv_update.setMinimumWidth(140)
        self.btn_hv_update.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Fixed)
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row1.addWidget(self.btn_edit)
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        control_layout.addLayout(row1)

        row1b = QHBoxLayout()
        row1b.addWidget(self.btn_hv_enable)
        row1b.addWidget(self.btn_hv_update)
        row1b.addWidget(self.btn_hv_settings)

        row2 = QHBoxLayout()
        self.btn_save_csv = QPushButton("Save CSV")
        self.btn_save_h5 = QPushButton("Save HDF5")
        self.btn_load_h5 = QPushButton("Load HDF5")
        row2.addWidget(self.btn_save_csv)
        row2.addWidget(self.btn_save_h5)
        row2.addWidget(self.btn_load_h5)
        control_layout.addLayout(row2)

        self.config_label = QLabel()
        self.config_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.config_label.setWordWrap(True)
        self.config_label.setMinimumWidth(395)

        self.status_label = QLabel("Status: Idle")
        self.status_label.setMinimumWidth(395)
        control_layout.addWidget(self.status_label)
        control_layout.addSpacing(8)
        control_layout.addWidget(self.config_label)

        self.progress_label = QLabel("Iteration: 0/0 | Average: 0/0")
        self.line_cursor_label = QLabel("Line cursor: x=-- ms, y=--")
        self.heat_cursor_label = QLabel("Heat cursor: x=-- (iter), y=-- ms")
        self.progress_label.setMinimumWidth(395)
        self.line_cursor_label.setMinimumWidth(395)
        self.heat_cursor_label.setMinimumWidth(395)
        control_layout.addWidget(self.progress_label)
        control_layout.addWidget(self.line_cursor_label)
        control_layout.addWidget(self.heat_cursor_label)

        hv_readout_box = QGroupBox("HV Readouts")
        hv_readout_layout = QVBoxLayout(hv_readout_box)
        hv_readout_layout.addLayout(row1b)
        self.hv_state_readout_label = QLabel("HV State: OFF")
        self.hv_ims_readout_label = QLabel("IMS AO: 0.000 V")
        self.hv_ion_readout_label = QLabel("Ionization AO: 0.000 V")
        self.hv_ims_kv_readout_label = QLabel("IMS: 0.000 kV")
        self.hv_ion_kv_readout_label = QLabel("Ionization: 0.000 kV")
        self.hv_state_readout_label.setMinimumWidth(395)
        self.hv_ims_readout_label.setMinimumWidth(395)
        self.hv_ion_readout_label.setMinimumWidth(395)
        self.hv_ims_kv_readout_label.setMinimumWidth(395)
        self.hv_ion_kv_readout_label.setMinimumWidth(395)
        hv_readout_layout.addWidget(self.hv_state_readout_label)
        hv_readout_layout.addWidget(self.hv_ims_readout_label)
        hv_readout_layout.addWidget(self.hv_ion_readout_label)
        hv_readout_layout.addWidget(self.hv_ims_kv_readout_label)
        hv_readout_layout.addWidget(self.hv_ion_kv_readout_label)
        control_layout.addWidget(hv_readout_box)

        params_box = QGroupBox("Parameters")
        params_layout = QGridLayout(params_box)
        
        self.pressure_spinbox = QDoubleSpinBox()
        self.pressure_spinbox.setDecimals(2)
        self.pressure_spinbox.setRange(0.0, 10000.0)
        self.pressure_spinbox.setValue(float(self.user_param_defaults["pressure_torr"]))
        self.pressure_spinbox.setSingleStep(1.0)
        self.pressure_spinbox.setSuffix(" Torr")
        
        self.temperature_spinbox = QDoubleSpinBox()
        self.temperature_spinbox.setDecimals(1)
        self.temperature_spinbox.setRange(-273.15, 1000.0)
        self.temperature_spinbox.setValue(float(self.user_param_defaults["temperature_c"]))
        self.temperature_spinbox.setSingleStep(0.1)
        self.temperature_spinbox.setSuffix(" °C")
        
        self.length_spinbox = QDoubleSpinBox()
        self.length_spinbox.setDecimals(2)
        self.length_spinbox.setRange(0.1, 1000.0)
        self.length_spinbox.setValue(float(self.user_param_defaults["length_cm"]))
        self.length_spinbox.setSingleStep(0.1)
        self.length_spinbox.setSuffix(" cm")
        
        self.voltage_spinbox = QDoubleSpinBox()
        self.voltage_spinbox.setDecimals(2)
        self.voltage_spinbox.setRange(0.1, 100.0)
        self.voltage_spinbox.setValue(float(self.user_param_defaults["voltage_kv"]))
        self.voltage_spinbox.setSingleStep(0.1)
        self.voltage_spinbox.setSuffix(" kV")
        
        self.gate_v_multiplier_spinbox = QDoubleSpinBox()
        self.gate_v_multiplier_spinbox.setDecimals(2)
        self.gate_v_multiplier_spinbox.setRange(0.01, 100.0)
        self.gate_v_multiplier_spinbox.setValue(float(self.user_param_defaults["gate_v_multiplier"]))
        self.gate_v_multiplier_spinbox.setSingleStep(0.01)

        self.noise_start_spinbox = QDoubleSpinBox()
        self.noise_start_spinbox.setDecimals(3)
        self.noise_start_spinbox.setRange(0.0, 1e6)
        self.noise_start_spinbox.setValue(float(self.user_param_defaults["noise_start_ms"]))
        self.noise_start_spinbox.setSuffix(" ms")

        self.noise_end_spinbox = QDoubleSpinBox()
        self.noise_end_spinbox.setDecimals(3)
        self.noise_end_spinbox.setRange(0.0, 1e6)
        self.noise_end_spinbox.setValue(float(self.user_param_defaults["noise_end_ms"]))
        self.noise_end_spinbox.setSuffix(" ms")

        params_layout.addWidget(QLabel("Pressure"), 0, 0)
        params_layout.addWidget(self.pressure_spinbox, 0, 1)
        params_layout.addWidget(QLabel("Temperature"), 1, 0)
        params_layout.addWidget(self.temperature_spinbox, 1, 1)
        params_layout.addWidget(QLabel("Length"), 2, 0)
        params_layout.addWidget(self.length_spinbox, 2, 1)
        params_layout.addWidget(QLabel("Voltage"), 3, 0)
        params_layout.addWidget(self.voltage_spinbox, 3, 1)
        params_layout.addWidget(QLabel("Gate V Multiplier"), 4, 0)
        params_layout.addWidget(self.gate_v_multiplier_spinbox, 4, 1)
        params_layout.addWidget(QLabel("Noise Start"), 5, 0)
        params_layout.addWidget(self.noise_start_spinbox, 5, 1)
        params_layout.addWidget(QLabel("Noise End"), 6, 0)
        params_layout.addWidget(self.noise_end_spinbox, 6, 1)
        self.btn_save_user_params_defaults = QPushButton("Save User Parameters as Default")
        params_layout.addWidget(self.btn_save_user_params_defaults, 7, 0, 1, 2)
        
        control_layout.addWidget(params_box)

        readout_box = QGroupBox("Live Readouts")
        readout_layout = QVBoxLayout(readout_box)
        self.ko_label = QLabel("Reduced Mobility (Ko): -- cm²/(V·s)")
        self.resolving_power_label = QLabel("Resolving Power (td/FWHM): --")
        self.snr_label = QLabel("SNR: --")
        self.ko_label.setMinimumWidth(395)
        self.resolving_power_label.setMinimumWidth(395)
        self.snr_label.setMinimumWidth(395)
        readout_layout.addWidget(self.ko_label)
        readout_layout.addWidget(self.resolving_power_label)
        readout_layout.addWidget(self.snr_label)
        
        control_layout.addWidget(readout_box)

        hardware_params_box = QGroupBox("Hardware Parameters")
        hardware_params_layout = QVBoxLayout(hardware_params_box)
        self.hardware_params_label = QLabel()
        self.hardware_params_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.hardware_params_label.setWordWrap(True)
        self.hardware_params_label.setMinimumWidth(395)
        hardware_params_layout.addWidget(self.hardware_params_label)
        control_layout.addWidget(hardware_params_box)

        control_layout.addStretch()

        plot_tabs = QTabWidget()

        line_tab = QWidget()
        line_layout = QVBoxLayout(line_tab)
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Display iteration:"))
        self.iteration_selector = QComboBox()
        chooser.addWidget(self.iteration_selector)
        self.follow_latest_checkbox = QCheckBox("Follow latest")
        self.follow_latest_checkbox.setChecked(True)
        chooser.addWidget(self.follow_latest_checkbox)
        chooser.addStretch()
        line_layout.addLayout(chooser)

        # Line plot title and labels depend on mode
        is_ftims = self.config.operation_mode == OperationMode.FTIMS
        plot_title = "FTIMS Mobility-Domain Spectrum" if is_ftims else "IMS Signal"
        y_label = "Intensity" if is_ftims else "Signal"
        x_label = "m/z or reduced mobility" if is_ftims else "Time (ms)"
        
        self.line_plot = pg.PlotWidget(title=plot_title)
        self.line_plot.setLabel("left", y_label)
        self.line_plot.setLabel("bottom", x_label)
        self.line_curve = self.line_plot.plot(pen=pg.mkPen(width=2))
        self.line_baseline_curve = self.line_plot.plot(pen=pg.mkPen("r", width=3))
        self.line_cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=1))
        self.line_cursor_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("y", width=1))
        self.line_plot.addItem(self.line_cursor_v, ignoreBounds=True)
        self.line_plot.addItem(self.line_cursor_h, ignoreBounds=True)
        self._line_peak_region = pg.LinearRegionItem(values=(0.0, 0.0), orientation="vertical")
        self._line_peak_region.setBrush(pg.mkBrush(0, 255, 0, 40))
        self._line_peak_region.setMovable(False)
        self._line_fwhm_left = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("c", width=1))
        self._line_fwhm_right = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("c", width=1))
        self.line_plot.addItem(self._line_peak_region, ignoreBounds=True)
        self.line_plot.addItem(self._line_fwhm_left, ignoreBounds=True)
        self.line_plot.addItem(self._line_fwhm_right, ignoreBounds=True)
        self._line_peak_region.hide()
        self._line_fwhm_left.hide()
        self._line_fwhm_right.hide()
        line_layout.addWidget(self.line_plot)
        self._axis_controls["line"] = self._create_axis_controls(line_layout, "line")

        heat_tab = QWidget()
        heat_layout = QVBoxLayout(heat_tab)
        self.heat_view = pg.GraphicsLayoutWidget()
        heat_title = "Frequency Heatmap (FTIMS)" if is_ftims else "Iterations Heatmap (DTIMS)"
        heat_y_label = "Frequency (Hz)" if is_ftims else "Time (ms)"
        self.heat_plot = self.heat_view.addPlot(title=heat_title)
        self.heat_plot.setLabel("left", heat_y_label)
        self.heat_plot.setLabel("bottom", "Iteration")
        self.heat_img = pg.ImageItem()
        self.heat_plot.addItem(self.heat_img)
        self.heat_cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("c", width=1))
        self.heat_cursor_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("c", width=1))
        self.heat_plot.addItem(self.heat_cursor_v, ignoreBounds=True)
        self.heat_plot.addItem(self.heat_cursor_h, ignoreBounds=True)
        self.heat_lut = pg.HistogramLUTItem()
        self.heat_lut.setImageItem(self.heat_img)
        self.heat_view.addItem(self.heat_lut)
        self._apply_heatmap_colormap()
        heat_layout.addWidget(self.heat_view)
        self._axis_controls["heat"] = self._create_axis_controls(heat_layout, "heat")

        selected_tab = QWidget()
        selected_layout = QVBoxLayout(selected_tab)
        selected_title = "Selected Frequency Spectrum (FTIMS)" if is_ftims else "IMS Signal (Selected from Heatmap)"
        selected_x_label = "m/z or reduced mobility" if is_ftims else "Time (ms)"
        self.line_plot_from_heat = pg.PlotWidget(title=selected_title)
        self.line_plot_from_heat.setLabel("left", y_label)
        self.line_plot_from_heat.setLabel("bottom", selected_x_label)
        self.line_curve_from_heat = self.line_plot_from_heat.plot(pen=pg.mkPen("w", width=2))
        self.selected_baseline_curve = self.line_plot_from_heat.plot(pen=pg.mkPen("r", width=3))
        self.selected_cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=1))
        self.selected_cursor_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("y", width=1))
        self.line_plot_from_heat.addItem(self.selected_cursor_v, ignoreBounds=True)
        self.line_plot_from_heat.addItem(self.selected_cursor_h, ignoreBounds=True)
        self._selected_peak_region = pg.LinearRegionItem(values=(0.0, 0.0), orientation="vertical")
        self._selected_peak_region.setBrush(pg.mkBrush(0, 255, 0, 40))
        self._selected_peak_region.setMovable(False)
        self._selected_fwhm_left = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("c", width=1))
        self._selected_fwhm_right = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("c", width=1))
        self.line_plot_from_heat.addItem(self._selected_peak_region, ignoreBounds=True)
        self.line_plot_from_heat.addItem(self._selected_fwhm_left, ignoreBounds=True)
        self.line_plot_from_heat.addItem(self._selected_fwhm_right, ignoreBounds=True)
        self._selected_peak_region.hide()
        self._selected_fwhm_left.hide()
        self._selected_fwhm_right.hide()
        selected_layout.addWidget(self.line_plot_from_heat)
        self._axis_controls["selected"] = self._create_axis_controls(selected_layout, "selected")

        # FTIMS raw time-domain data tab
        ftims_raw_tab = QWidget()
        ftims_raw_layout = QVBoxLayout(ftims_raw_tab)
        ftims_raw_chooser = QHBoxLayout()
        ftims_raw_chooser.addWidget(QLabel("Select frequency (Hz):"))
        self.ftims_frequency_selector = QComboBox()
        ftims_raw_chooser.addWidget(self.ftims_frequency_selector)
        ftims_raw_chooser.addStretch()
        ftims_raw_layout.addLayout(ftims_raw_chooser)
        
        self.ftims_raw_plot = pg.PlotWidget(title="FTIMS Raw Time-Domain Data")
        self.ftims_raw_plot.setLabel("left", "Signal")
        self.ftims_raw_plot.setLabel("bottom", "Time (ms)")
        self.ftims_raw_curve = self.ftims_raw_plot.plot(pen=pg.mkPen("g", width=2))
        self.ftims_raw_cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=1))
        self.ftims_raw_cursor_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("y", width=1))
        self.ftims_raw_plot.addItem(self.ftims_raw_cursor_v, ignoreBounds=True)
        self.ftims_raw_plot.addItem(self.ftims_raw_cursor_h, ignoreBounds=True)
        ftims_raw_layout.addWidget(self.ftims_raw_plot)
        self._axis_controls["ftims_raw"] = self._create_axis_controls(ftims_raw_layout, "ftims_raw")

        plot_tabs.addTab(line_tab, "Line Plot")
        plot_tabs.addTab(heat_tab, "2D Colormap")
        plot_tabs.addTab(selected_tab, "Selected Iteration")
        plot_tabs.addTab(ftims_raw_tab, "FTIMS Raw Data")
        
        # Store reference to plot tabs for later updates
        self.plot_tabs = plot_tabs
        
        # Show FTIMS raw tab if in FTIMS mode (initially DTIMS, but will be shown when data arrives)
        plot_tabs.setTabVisible(3, is_ftims)

        root.addWidget(control_box, 0, 0)
        root.addWidget(plot_tabs, 0, 1)

        self.btn_edit.clicked.connect(self.edit_settings)
        self.btn_hv_settings.clicked.connect(self.edit_hv_settings)
        self.btn_hv_enable.toggled.connect(self.on_hv_toggled)
        self.btn_hv_update.clicked.connect(self.on_update_hv_values)
        self.btn_start.clicked.connect(self.start_acquisition)
        self.btn_stop.clicked.connect(self.stop_acquisition)
        self.btn_save_csv.clicked.connect(self.save_csv)
        self.btn_save_h5.clicked.connect(self.save_hdf5)
        self.btn_load_h5.clicked.connect(self.load_hdf5)
        self.iteration_selector.currentIndexChanged.connect(self._on_iteration_selector_changed)
        self.follow_latest_checkbox.toggled.connect(self.update_line_plot)

        self.pressure_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.temperature_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.length_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.voltage_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.gate_v_multiplier_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.noise_start_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.noise_end_spinbox.valueChanged.connect(self._on_parameter_changed)
        self.btn_save_user_params_defaults.clicked.connect(self.save_user_parameters_as_default)

        self.line_mouse_proxy = pg.SignalProxy(
            self.line_plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_line_mouse_moved,
        )
        self.line_plot.scene().sigMouseClicked.connect(self._on_line_mouse_clicked)
        self.heat_mouse_proxy = pg.SignalProxy(
            self.heat_plot.scene().sigMouseMoved,
            rateLimit=25,
            slot=self._on_heat_mouse_moved,
        )
        self.heat_plot.scene().sigMouseClicked.connect(self._on_heat_mouse_clicked)

        self.selected_mouse_proxy = pg.SignalProxy(
            self.line_plot_from_heat.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_selected_mouse_moved,
        )
        self.line_plot_from_heat.scene().sigMouseClicked.connect(self._on_selected_mouse_clicked)

        self._on_auto_axis_toggled("line")
        self._on_auto_axis_toggled("heat")
        self._on_auto_axis_toggled("selected")

        self._refresh_iteration_selector()

    def _refresh_hv_control_states(self) -> None:
        hv_busy = self.hv_worker is not None and self.hv_worker.isRunning()
        acquisition_active = self.worker is not None and self.worker.isRunning()
        self.btn_hv_enable.setEnabled(not hv_busy)
        self.btn_hv_settings.setEnabled(not hv_busy)
        self.btn_hv_update.setEnabled(self.hv_enabled and (not hv_busy) and (not acquisition_active))

    def _create_axis_controls(self, parent_layout: QVBoxLayout, key: str) -> dict[str, object]:
        controls_widget = QWidget()
        controls_layout = QGridLayout(controls_widget)

        x_min = QDoubleSpinBox()
        x_max = QDoubleSpinBox()
        y_min = QDoubleSpinBox()
        y_max = QDoubleSpinBox()
        for spin in (x_min, x_max, y_min, y_max):
            spin.setDecimals(6)
            spin.setRange(-1e12, 1e12)
            spin.setSingleStep(0.1)

        auto_x = QCheckBox("Auto X")
        auto_y = QCheckBox("Auto Y")
        auto_x.setChecked(True)
        auto_y.setChecked(True)

        reset_btn = QPushButton("Reset to Data")

        controls_layout.addWidget(QLabel("X min"), 0, 0)
        controls_layout.addWidget(x_min, 0, 1)
        controls_layout.addWidget(QLabel("X max"), 0, 2)
        controls_layout.addWidget(x_max, 0, 3)
        controls_layout.addWidget(auto_x, 0, 4)

        controls_layout.addWidget(QLabel("Y min"), 1, 0)
        controls_layout.addWidget(y_min, 1, 1)
        controls_layout.addWidget(QLabel("Y max"), 1, 2)
        controls_layout.addWidget(y_max, 1, 3)
        controls_layout.addWidget(auto_y, 1, 4)

        controls_layout.addWidget(reset_btn, 0, 5, 2, 1)

        z_min = None
        z_max = None
        auto_z = None
        z_autoscale_btn = None
        if key == "heat":
            z_min = QDoubleSpinBox()
            z_max = QDoubleSpinBox()
            for spin in (z_min, z_max):
                spin.setDecimals(6)
                spin.setRange(-1e12, 1e12)
                spin.setSingleStep(0.1)

            auto_z = QCheckBox("Auto Z")
            auto_z.setChecked(True)
            z_autoscale_btn = QPushButton("Autoscale Z")

            controls_layout.addWidget(QLabel("Z min"), 2, 0)
            controls_layout.addWidget(z_min, 2, 1)
            controls_layout.addWidget(QLabel("Z max"), 2, 2)
            controls_layout.addWidget(z_max, 2, 3)
            controls_layout.addWidget(auto_z, 2, 4)
            controls_layout.addWidget(z_autoscale_btn, 2, 5)

        parent_layout.addWidget(controls_widget)

        ctrl = {
            "x_min": x_min,
            "x_max": x_max,
            "y_min": y_min,
            "y_max": y_max,
            "auto_x": auto_x,
            "auto_y": auto_y,
            "reset": reset_btn,
            "z_min": z_min,
            "z_max": z_max,
            "auto_z": auto_z,
            "z_autoscale": z_autoscale_btn,
        }

        x_min.valueChanged.connect(lambda _v, axis_key=key: self._on_axis_spin_changed(axis_key))
        x_max.valueChanged.connect(lambda _v, axis_key=key: self._on_axis_spin_changed(axis_key))
        y_min.valueChanged.connect(lambda _v, axis_key=key: self._on_axis_spin_changed(axis_key))
        y_max.valueChanged.connect(lambda _v, axis_key=key: self._on_axis_spin_changed(axis_key))
        auto_x.toggled.connect(lambda _checked, axis_key=key: self._on_auto_axis_toggled(axis_key))
        auto_y.toggled.connect(lambda _checked, axis_key=key: self._on_auto_axis_toggled(axis_key))
        reset_btn.clicked.connect(lambda _checked=False, axis_key=key: self._reset_axis_to_data(axis_key))
        if key == "heat":
            z_min.valueChanged.connect(lambda _v: self._on_heat_z_spin_changed())
            z_max.valueChanged.connect(lambda _v: self._on_heat_z_spin_changed())
            auto_z.toggled.connect(lambda _checked: self._on_heat_auto_z_toggled())
            z_autoscale_btn.clicked.connect(lambda _checked=False: self._autoscale_heat_z())

        return ctrl

    def _axis_plot(self, key: str):
        if key == "line":
            return self.line_plot
        if key == "heat":
            return self.heat_plot
        return self.line_plot_from_heat

    def _safe_bounds(self, min_value: float, max_value: float) -> tuple[float, float]:
        if min_value == max_value:
            delta = 1.0 if min_value == 0.0 else abs(min_value) * 0.05
            return min_value - delta, max_value + delta
        if min_value > max_value:
            return max_value, min_value
        return min_value, max_value

    def _bounds_for_key(self, key: str) -> tuple[float, float, float, float] | None:
        if key == "line":
            if self._current_line_x.size == 0:
                return None
            x_min, x_max = self._safe_bounds(float(self._current_line_x.min()), float(self._current_line_x.max()))
            y_min, y_max = self._safe_bounds(float(self._current_line_y.min()), float(self._current_line_y.max()))
            return x_min, x_max, y_min, y_max

        if key == "selected":
            if self._selected_line_x.size == 0:
                return None
            x_min, x_max = self._safe_bounds(float(self._selected_line_x.min()), float(self._selected_line_x.max()))
            y_min, y_max = self._safe_bounds(float(self._selected_line_y.min()), float(self._selected_line_y.max()))
            return x_min, x_max, y_min, y_max

        if self._heat_row_count == 0:
            return None
        x_min, x_max = self._safe_bounds(1.0, float(self._heat_row_count))
        y_min, y_max = self._safe_bounds(0.0, float(self.config.experiment_length_ms))
        return x_min, x_max, y_min, y_max

    def _heat_z_bounds(self) -> tuple[float, float] | None:
        if self._heat_z_min is not None and self._heat_z_max is not None:
            return self._safe_bounds(self._heat_z_min, self._heat_z_max)
        if self._heat_matrix.size == 0:
            return None
        z_min_value = float(np.min(self._heat_matrix))
        z_max_value = float(np.max(self._heat_matrix))
        self._heat_z_min = z_min_value
        self._heat_z_max = z_max_value
        return self._safe_bounds(z_min_value, z_max_value)

    def _set_axis_spin_values(
        self,
        key: str,
        x_min_value: float,
        x_max_value: float,
        y_min_value: float,
        y_max_value: float,
    ) -> None:
        ctrl = self._axis_controls[key]
        x_min_spin = ctrl["x_min"]
        x_max_spin = ctrl["x_max"]
        y_min_spin = ctrl["y_min"]
        y_max_spin = ctrl["y_max"]

        for spin, value in (
            (x_min_spin, x_min_value),
            (x_max_spin, x_max_value),
            (y_min_spin, y_min_value),
            (y_max_spin, y_max_value),
        ):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)

    def _apply_axis_from_controls(self, key: str) -> None:
        ctrl = self._axis_controls[key]
        x_min_value, x_max_value = self._safe_bounds(ctrl["x_min"].value(), ctrl["x_max"].value())
        y_min_value, y_max_value = self._safe_bounds(ctrl["y_min"].value(), ctrl["y_max"].value())
        plot = self._axis_plot(key)
        plot.setXRange(x_min_value, x_max_value, padding=0.0)
        plot.setYRange(y_min_value, y_max_value, padding=0.0)

    def _update_auto_axis(self, key: str) -> None:
        ctrl = self._axis_controls[key]
        auto_x = ctrl["auto_x"].isChecked()
        auto_y = ctrl["auto_y"].isChecked()
        if not auto_x and not auto_y:
            return

        bounds = self._bounds_for_key(key)
        if bounds is None:
            return
        x_min_value, x_max_value, y_min_value, y_max_value = bounds

        if auto_x:
            ctrl["x_min"].blockSignals(True)
            ctrl["x_max"].blockSignals(True)
            ctrl["x_min"].setValue(x_min_value)
            ctrl["x_max"].setValue(x_max_value)
            ctrl["x_min"].blockSignals(False)
            ctrl["x_max"].blockSignals(False)
        if auto_y:
            ctrl["y_min"].blockSignals(True)
            ctrl["y_max"].blockSignals(True)
            ctrl["y_min"].setValue(y_min_value)
            ctrl["y_max"].setValue(y_max_value)
            ctrl["y_min"].blockSignals(False)
            ctrl["y_max"].blockSignals(False)

        self._apply_axis_from_controls(key)

    def _reset_axis_to_data(self, key: str) -> None:
        bounds = self._bounds_for_key(key)
        if bounds is None:
            return
        self._set_axis_spin_values(key, *bounds)
        self._apply_axis_from_controls(key)
        if key == "heat":
            self._autoscale_heat_z()

    def _on_auto_axis_toggled(self, key: str) -> None:
        ctrl = self._axis_controls[key]
        auto_x = ctrl["auto_x"].isChecked()
        auto_y = ctrl["auto_y"].isChecked()
        ctrl["x_min"].setEnabled(not auto_x)
        ctrl["x_max"].setEnabled(not auto_x)
        ctrl["y_min"].setEnabled(not auto_y)
        ctrl["y_max"].setEnabled(not auto_y)
        if key == "heat":
            auto_z_checked = ctrl["auto_z"].isChecked()
            ctrl["z_min"].setEnabled(not auto_z_checked)
            ctrl["z_max"].setEnabled(not auto_z_checked)
        self._update_auto_axis(key)

    def _apply_heat_z_from_controls(self) -> None:
        ctrl = self._axis_controls["heat"]
        z_min_value, z_max_value = self._safe_bounds(ctrl["z_min"].value(), ctrl["z_max"].value())
        self.heat_img.setLevels((z_min_value, z_max_value))
        self.heat_lut.setLevels(z_min_value, z_max_value)

    def _autoscale_heat_z(self) -> None:
        bounds = self._heat_z_bounds()
        if bounds is None:
            return
        z_min_value, z_max_value = bounds
        ctrl = self._axis_controls["heat"]
        ctrl["z_min"].blockSignals(True)
        ctrl["z_max"].blockSignals(True)
        ctrl["z_min"].setValue(z_min_value)
        ctrl["z_max"].setValue(z_max_value)
        ctrl["z_min"].blockSignals(False)
        ctrl["z_max"].blockSignals(False)
        self._apply_heat_z_from_controls()

    def _on_heat_auto_z_toggled(self) -> None:
        ctrl = self._axis_controls["heat"]
        auto_z_checked = ctrl["auto_z"].isChecked()
        ctrl["z_min"].setEnabled(not auto_z_checked)
        ctrl["z_max"].setEnabled(not auto_z_checked)
        if auto_z_checked:
            self._autoscale_heat_z()

    def _on_heat_z_spin_changed(self) -> None:
        ctrl = self._axis_controls["heat"]
        if ctrl["auto_z"].isChecked():
            return
        self._apply_heat_z_from_controls()

    def _on_axis_spin_changed(self, key: str) -> None:
        ctrl = self._axis_controls[key]
        if ctrl["auto_x"].isChecked() or ctrl["auto_y"].isChecked():
            return
        self._apply_axis_from_controls(key)

    def _apply_heatmap_colormap(self) -> None:
        rainbow_positions = np.array([0.0, 0.2, 0.4, 0.6, 0.8, 1.0], dtype=np.float64)
        rainbow_colors = np.array(
            [
                (148, 0, 211, 255),
                (0, 0, 255, 255),
                (0, 255, 255, 255),
                (0, 255, 0, 255),
                (255, 255, 0, 255),
                (255, 0, 0, 255),
            ],
            dtype=np.ubyte,
        )
        rainbow_cmap = pg.ColorMap(rainbow_positions, rainbow_colors)
        lut = rainbow_cmap.getLookupTable(0.0, 1.0, 256)
        self.heat_img.setLookupTable(lut)
        self.heat_lut.gradient.setColorMap(rainbow_cmap)

    def _update_ko(self) -> None:
        """Calculate and update the reduced mobility (Ko) value (DTIMS only)."""
        if self.ko_label is None or self.config.operation_mode == OperationMode.FTIMS:
            return
        
        drift_time_ms = self._current_cursor_x
        if drift_time_ms <= 0:
            self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")
            return
        
        # Get parameter values
        pressure = self.pressure_spinbox.value()  # Torr
        temperature = self.temperature_spinbox.value()  # °C
        length = self.length_spinbox.value()  # cm
        voltage = self.voltage_spinbox.value() * 1000.0  # Convert from kV to V
        gate_v_multiplier = self.gate_v_multiplier_spinbox.value()
        
        # Convert drift time from ms to seconds
        drift_time_sec = drift_time_ms / 1000.0
        
        # Calculate Ko using the formula:
        # Ko = ((L^2)/(V*(Gate V Multiplier)*Drift Time (in seconds)))*(P/760)*(273.15/(T+273.15))
        try:
            numerator = length * length
            denominator = voltage * gate_v_multiplier * drift_time_sec
            pressure_factor = pressure / 760.0
            temperature_factor = 273.15 / (temperature + 273.15)
            
            ko = (numerator / denominator) * pressure_factor * temperature_factor
            
            self.ko_label.setText(f"Reduced Mobility (Ko): {ko:.4f} cm²/(V·s)")
        except (ValueError, ZeroDivisionError):
            self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")

    def _active_cursor_locked(self) -> bool:
        return self._line_cursor_locked or self._heat_cursor_locked or self._selected_cursor_locked

    def _clear_peak_readouts(self) -> None:
        self.resolving_power_label.setText("Resolving Power (td/FWHM): --")
        self.snr_label.setText("SNR: --")

    def _hide_peak_overlays(self, source: str | None = None) -> None:
        if source in (None, "line"):
            self._line_peak_region.hide()
            self._line_fwhm_left.hide()
            self._line_fwhm_right.hide()
        if source in (None, "selected"):
            self._selected_peak_region.hide()
            self._selected_fwhm_left.hide()
            self._selected_fwhm_right.hide()

    def _on_parameter_changed(self, _value: float | None = None) -> None:
        self._update_baseline_overlay("line")
        self._update_baseline_overlay("selected")
        if self._active_cursor_locked():
            self._update_ko()
            if self._line_cursor_locked:
                self._update_peak_metrics(self._current_line_x, self._current_line_y, self._current_cursor_x, "line")
            elif self._selected_cursor_locked:
                self._update_peak_metrics(
                    self._selected_line_x,
                    self._selected_line_y,
                    self._current_cursor_x,
                    "selected",
                )

    def _baseline_bounds(self, source: str) -> tuple[float, float]:
        del source
        return self._safe_bounds(self.noise_start_spinbox.value(), self.noise_end_spinbox.value())

    def _update_baseline_overlay(self, source: str) -> None:
        if source == "line":
            x_values = self._current_line_x
            y_values = self._current_line_y
            baseline_curve = self.line_baseline_curve
        else:
            x_values = self._selected_line_x
            y_values = self._selected_line_y
            baseline_curve = self.selected_baseline_curve

        if baseline_curve is None or x_values.size == 0 or y_values.size == 0:
            if baseline_curve is not None:
                baseline_curve.setData([], [])
            return

        low_bound, high_bound = self._baseline_bounds(source)
        baseline_mask = (x_values >= low_bound) & (x_values <= high_bound)

        baseline_y = np.full(y_values.shape, np.nan, dtype=np.float64)
        baseline_y[baseline_mask] = y_values[baseline_mask]
        baseline_curve.setData(x_values, baseline_y)

    def _interpolate_x(self, x1: float, y1: float, x2: float, y2: float, target_y: float) -> float:
        if y2 == y1:
            return x1
        return x1 + (target_y - y1) * (x2 - x1) / (y2 - y1)

    def _update_peak_metrics(self, x: np.ndarray, y: np.ndarray, cursor_x: float, source: str) -> None:
        if x.size == 0 or y.size == 0:
            self._clear_peak_readouts()
            self._hide_peak_overlays(source)
            return

        peak_idx = int(np.argmin(np.abs(x - cursor_x)))
        peak_signal = float(y[peak_idx])
        if peak_signal <= 0.0:
            self._clear_peak_readouts()
            self._hide_peak_overlays(source)
            return

        peak_time_ms = float(x[peak_idx])
        half_max = peak_signal * 0.5

        left_idx = peak_idx
        while left_idx > 0 and y[left_idx] > half_max:
            left_idx -= 1
        right_idx = peak_idx
        while right_idx < y.size - 1 and y[right_idx] > half_max:
            right_idx += 1

        if left_idx == peak_idx or right_idx == peak_idx:
            self._clear_peak_readouts()
            self._hide_peak_overlays(source)
            return

        left_x = self._interpolate_x(
            float(x[left_idx]),
            float(y[left_idx]),
            float(x[left_idx + 1]),
            float(y[left_idx + 1]),
            half_max,
        )
        right_x = self._interpolate_x(
            float(x[right_idx - 1]),
            float(y[right_idx - 1]),
            float(x[right_idx]),
            float(y[right_idx]),
            half_max,
        )

        fwhm_ms = right_x - left_x
        if fwhm_ms <= 0.0:
            self._clear_peak_readouts()
            self._hide_peak_overlays(source)
            return

        resolving_power = peak_time_ms / fwhm_ms

        noise_low, noise_high = self._baseline_bounds(source)
        noise_mask = (x >= noise_low) & (x <= noise_high)
        noise_values = y[noise_mask]
        snr_text = "SNR: --"
        if noise_values.size >= 2:
            noise_mean = float(np.mean(noise_values))
            noise_rms = float(np.sqrt(np.mean((noise_values - noise_mean) ** 2)))
            signal_height = max(peak_signal - noise_mean, 0.0)
            if noise_rms > 0.0 and signal_height > 0.0:
                snr_linear = signal_height / noise_rms
                snr_db = 20.0 * np.log10(snr_linear)
                snr_text = f"SNR: {snr_linear:.2f} ({snr_db:.2f} dB)"

        self.resolving_power_label.setText(
            f"Resolving Power (td/FWHM): {resolving_power:.3f} | td={peak_time_ms:.4f} ms, FWHM={fwhm_ms:.4f} ms"
        )
        self.snr_label.setText(snr_text)

        if source == "line":
            self._line_peak_region.setRegion((float(x[left_idx]), float(x[right_idx])))
            self._line_fwhm_left.setPos(left_x)
            self._line_fwhm_right.setPos(right_x)
            self._line_peak_region.show()
            self._line_fwhm_left.show()
            self._line_fwhm_right.show()
        elif source == "selected":
            self._selected_peak_region.setRegion((float(x[left_idx]), float(x[right_idx])))
            self._selected_fwhm_left.setPos(left_x)
            self._selected_fwhm_right.setPos(right_x)
            self._selected_peak_region.show()
            self._selected_fwhm_left.show()
            self._selected_fwhm_right.show()

    def _refresh_config_label(self) -> None:
        cfg = self.config
        text = (
            f"Pulse width: {cfg.pulse_width_ms} ms\n"
            f"Length: {cfg.experiment_length_ms} ms\n"
            f"Data points: {cfg.data_points}\n"
            f"Averages: {cfg.averages_per_iteration}\n"
            f"Iterations: {cfg.total_iterations}"
        )
        self.config_label.setText(text)

        hardware_text = (
            f"AI: {cfg.ai_channel}\n"
            f"Counter: {cfg.counter_channel}\n"
            f"PFI trigger: {cfg.pfi_trigger}\n"
            f"Polarity: {'Positive' if cfg.positive_mode else 'Negative'}\n"
            f"Acquisition mode: {'Simulation' if cfg.use_simulation else 'Hardware'}"
        )
        if self.hardware_params_label is not None:
            self.hardware_params_label.setText(hardware_text)

    def _daq_for_hv(self) -> NiUSB6351Controller:
        daq_cfg = DaqConfig(
            ai_channel=self.config.ai_channel,
            counter_channel=self.config.counter_channel,
            pfi_trigger=self.config.pfi_trigger,
            pulse_width_ms=self.config.pulse_width_ms,
            experiment_length_ms=self.config.experiment_length_ms,
            data_points=self.config.data_points,
            use_simulation=self.config.use_simulation,
        )
        return NiUSB6351Controller(daq_cfg)

    def _calculate_hv_outputs(self) -> tuple[float, float, float]:
        cfg = self.hv_config
        max_kv = float(cfg.ims_max_output_kv)
        ctrl_max_v = float(cfg.control_voltage_max_v)
        ims_kv = float(cfg.ims_setpoint_kv)
        ion_total_kv = float(cfg.ims_setpoint_kv + cfg.ionization_bias_kv)

        if max_kv <= 0.0:
            raise ValueError("IMS max output must be greater than 0 kV.")
        if ctrl_max_v <= 0.0:
            raise ValueError("Control voltage max must be greater than 0 V.")
        if ims_kv < 0.0:
            raise ValueError("IMS setpoint cannot be negative.")
        if ion_total_kv < 0.0:
            raise ValueError("Ionization total voltage cannot be negative.")
        if ims_kv > max_kv:
            raise ValueError(
                f"IMS setpoint ({ims_kv:.3f} kV) exceeds IMS max output ({max_kv:.3f} kV)."
            )
        if ion_total_kv > max_kv:
            raise ValueError(
                f"Ionization total ({ion_total_kv:.3f} kV) exceeds IMS max output ({max_kv:.3f} kV)."
            )

        ims_v = (ims_kv / max_kv) * ctrl_max_v
        ion_v = (ion_total_kv / max_kv) * ctrl_max_v
        return ims_v, ion_v, ion_total_kv

    def _apply_hv_background(self, enabled: bool) -> None:
        color = "#b73131" if enabled else "#2f8f46"
        self.setStyleSheet(f"QMainWindow {{ background-color: {color}; }}")

    def _update_hv_status_label(self, ims_v: float, ion_v: float) -> None:
        state = "ON" if self.hv_enabled else "OFF"
        ctrl_max_v = float(self.hv_config.control_voltage_max_v)
        max_kv = float(self.hv_config.ims_max_output_kv)
        ims_kv = 0.0
        ion_kv = 0.0
        if ctrl_max_v > 0.0 and max_kv > 0.0:
            ims_kv = (float(ims_v) / ctrl_max_v) * max_kv
            ion_kv = (float(ion_v) / ctrl_max_v) * max_kv

        if self.hv_state_readout_label is not None:
            self.hv_state_readout_label.setText(f"HV State: {state}")
        if self.hv_ims_readout_label is not None:
            self.hv_ims_readout_label.setText(f"IMS AO: {ims_v:.3f} V")
        if self.hv_ion_readout_label is not None:
            self.hv_ion_readout_label.setText(f"Ionization AO: {ion_v:.3f} V")
        if self.hv_ims_kv_readout_label is not None:
            self.hv_ims_kv_readout_label.setText(f"IMS: {ims_kv:.3f} kV")
        if self.hv_ion_kv_readout_label is not None:
            self.hv_ion_kv_readout_label.setText(f"Ionization: {ion_kv:.3f} kV")

    def _build_hv_payload(self, enabled: bool, ims_v: float, ion_v: float) -> dict[str, object]:
        return {
            "ai_channel": self.config.ai_channel,
            "counter_channel": self.config.counter_channel,
            "pfi_trigger": self.config.pfi_trigger,
            "pulse_width_ms": self.config.pulse_width_ms,
            "experiment_length_ms": self.config.experiment_length_ms,
            "data_points": self.config.data_points,
            "use_simulation": self.config.use_simulation,
            "ims_ao_channel": self.hv_config.ims_ao_channel,
            "ion_ao_channel": self.hv_config.ion_ao_channel,
            "hv_enable_do_line": self.hv_config.hv_enable_do_line,
            "enabled": bool(enabled),
            "ims_v": float(ims_v),
            "ion_v": float(ion_v),
        }

    def _run_hv_payload_sync(self, payload: dict[str, object], timeout_seconds: float = 10.0) -> dict[str, object]:
        src_dir = Path(__file__).resolve().parents[2]
        cmd = [
            sys.executable,
            "-m",
            "ims_control.acquisition.hv_cli",
            "--payload",
            json.dumps(payload, separators=(",", ":")),
        ]

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

        completed = subprocess.run(
            cmd,
            cwd=str(src_dir.parent),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_seconds),
            check=False,
        )

        event = None
        for line in reversed(completed.stdout.splitlines()):
            try:
                candidate = json.loads(line)
            except Exception:
                continue
            if isinstance(candidate, dict):
                event = candidate
                break

        if completed.returncode != 0:
            error = completed.stderr.strip() or "HV subprocess failed"
            if isinstance(event, dict) and event.get("ok") is False:
                error = str(event.get("error", error))
            raise RuntimeError(error)

        if not isinstance(event, dict) or event.get("ok") is not True:
            raise RuntimeError("HV subprocess returned no valid success payload")

        return event

    def _set_hv_outputs(self, enabled: bool, silent: bool = False) -> None:
        ims_v = 0.0
        ion_v = 0.0

        if enabled:
            ims_v, ion_v, _ion_total_kv = self._calculate_hv_outputs()

        try:
            daq = self._daq_for_hv()
            daq.write_analog_output(self.hv_config.ims_ao_channel, ims_v)
            daq.write_analog_output(self.hv_config.ion_ao_channel, ion_v)
            daq.write_digital_line(self.hv_config.hv_enable_do_line, bool(enabled))
        except Exception as exc:
            if not silent:
                raise RuntimeError(str(exc)) from exc

        self.hv_enabled = bool(enabled)
        self.btn_hv_enable.blockSignals(True)
        self.btn_hv_enable.setChecked(self.hv_enabled)
        self.btn_hv_enable.setText("HV ON" if self.hv_enabled else "HV OFF")
        self.btn_hv_enable.blockSignals(False)
        self._apply_hv_background(self.hv_enabled)
        self._update_hv_status_label(ims_v=ims_v, ion_v=ion_v)

    def _start_hv_apply(self, enabled: bool) -> None:
        if self.hv_worker is not None and self.hv_worker.isRunning():
            self.status_label.setText("Status: HV update already in progress")
            self.btn_hv_enable.blockSignals(True)
            self.btn_hv_enable.setChecked(self.hv_enabled)
            self.btn_hv_enable.blockSignals(False)
            self._refresh_hv_control_states()
            return

        ims_v = 0.0
        ion_v = 0.0
        if enabled:
            ims_v, ion_v, _ion_total_kv = self._calculate_hv_outputs()

        self._pending_hv_enabled = bool(enabled)
        self._pending_hv_ims_v = float(ims_v)
        self._pending_hv_ion_v = float(ion_v)

        self._refresh_hv_control_states()
        self.status_label.setText("Status: Applying HV outputs...")

        payload = self._build_hv_payload(enabled=bool(enabled), ims_v=float(ims_v), ion_v=float(ion_v))

        self.hv_worker = HVOutputWorker(payload=payload, timeout_seconds=30.0)
        self.hv_worker.applied.connect(self._on_hv_apply_success)
        self.hv_worker.failed.connect(self._on_hv_apply_failed)
        self.hv_worker.finished.connect(self._on_hv_apply_finished)
        self.hv_worker.start()

    def _on_hv_apply_success(self, enabled: bool, ims_v: float, ion_v: float) -> None:
        self.hv_enabled = bool(enabled)
        self.btn_hv_enable.blockSignals(True)
        self.btn_hv_enable.setChecked(self.hv_enabled)
        self.btn_hv_enable.setText("HV ON" if self.hv_enabled else "HV OFF")
        self.btn_hv_enable.blockSignals(False)
        self._apply_hv_background(self.hv_enabled)
        self._update_hv_status_label(ims_v=ims_v, ion_v=ion_v)

        if self.hv_enabled:
            _ims_v, _ion_v, ion_total_kv = self._calculate_hv_outputs()
            self.status_label.setText(
                "Status: HV enabled "
                f"(IMS={self.hv_config.ims_setpoint_kv:.3f} kV -> {ims_v:.3f} V, "
                f"Ionization={ion_total_kv:.3f} kV -> {ion_v:.3f} V)"
            )
        else:
            self.status_label.setText("Status: HV disabled")
        self._refresh_hv_control_states()

    def _on_hv_apply_failed(self, message: str) -> None:
        self.hv_enabled = False
        self.btn_hv_enable.blockSignals(True)
        self.btn_hv_enable.setChecked(False)
        self.btn_hv_enable.setText("HV OFF")
        self.btn_hv_enable.blockSignals(False)
        self._apply_hv_background(False)
        self._update_hv_status_label(ims_v=0.0, ion_v=0.0)
        self._refresh_hv_control_states()
        QMessageBox.critical(self, "HV output error", message)

    def _on_hv_apply_finished(self) -> None:
        self.hv_worker = None
        self._refresh_hv_control_states()

    def on_update_hv_values(self) -> None:
        if not self.hv_enabled:
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Acquisition active", "Update HV Values is disabled during acquisition.")
            self._refresh_hv_control_states()
            return
        try:
            self.status_label.setText("Status: Applying updated HV values...")
            self._start_hv_apply(enabled=True)
        except Exception as exc:
            QMessageBox.critical(self, "HV output error", str(exc))
            self._refresh_hv_control_states()

    def _load_default_hv_config(self) -> HVPowerConfig:
        path = self.DEFAULT_HV_CONFIG_PATH
        if not path.exists():
            return HVPowerConfig()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return HVPowerConfig()
            return HVPowerConfig.from_dict(raw)
        except Exception:
            return HVPowerConfig()

    def _save_default_hv_config(self, config: HVPowerConfig) -> None:
        path = self.DEFAULT_HV_CONFIG_PATH
        try:
            path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
            self.status_label.setText(f"Status: HV defaults saved to {path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Save defaults failed", f"Could not save HV defaults:\n{exc}")

    def _set_heat_cursor_label(
        self,
        x_iter: float | None = None,
        y_ms: float | None = None,
        z_value: float | None = None,
        locked: bool = False,
    ) -> None:
        if x_iter is None or y_ms is None:
            self.heat_cursor_label.setText("Heat cursor: x=-- (iter), y=-- ms")
            return

        lock_suffix = " [LOCKED]" if locked else ""
        base_line = f"Heat cursor: x={x_iter:.3f} (iter), y={y_ms:.4f} ms{lock_suffix}"
        if z_value is None:
            self.heat_cursor_label.setText(base_line)
            return

        self.heat_cursor_label.setText(f"{base_line}\n    z={z_value:.6f}")

    def _default_noise_window(self) -> tuple[float, float]:
        length_ms = float(self.config.experiment_length_ms)
        noise_end = max(length_ms, 0.0)
        noise_start = max(noise_end - 10.0, 0.0)
        return noise_start, noise_end

    def _load_default_user_params(self) -> dict[str, float]:
        noise_start_default, noise_end_default = self._default_noise_window()
        defaults = {
            "pressure_torr": 705.0,
            "temperature_c": 20.0,
            "length_cm": 10.0,
            "voltage_kv": 4.0,
            "gate_v_multiplier": 0.5,
            "noise_start_ms": noise_start_default,
            "noise_end_ms": noise_end_default,
        }

        path = self.DEFAULT_USER_PARAMS_PATH
        if not path.exists():
            return defaults

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return defaults

            for key in defaults:
                if key in raw:
                    defaults[key] = float(raw[key])

            if "noise_start_ms" not in raw and "noise_end_ms" not in raw:
                defaults["noise_start_ms"], defaults["noise_end_ms"] = self._default_noise_window()

            noise_start = max(0.0, float(defaults["noise_start_ms"]))
            noise_end = max(0.0, float(defaults["noise_end_ms"]))
            if noise_start > noise_end:
                noise_start, noise_end = noise_end, noise_start
            defaults["noise_start_ms"] = noise_start
            defaults["noise_end_ms"] = noise_end
            return defaults
        except Exception:
            return defaults

    def _current_user_params(self) -> dict[str, float]:
        return {
            "pressure_torr": float(self.pressure_spinbox.value()),
            "temperature_c": float(self.temperature_spinbox.value()),
            "length_cm": float(self.length_spinbox.value()),
            "voltage_kv": float(self.voltage_spinbox.value()),
            "gate_v_multiplier": float(self.gate_v_multiplier_spinbox.value()),
            "noise_start_ms": float(self.noise_start_spinbox.value()),
            "noise_end_ms": float(self.noise_end_spinbox.value()),
        }

    def _save_default_user_params(self, values: dict[str, float]) -> bool:
        path = self.DEFAULT_USER_PARAMS_PATH
        try:
            path.write_text(json.dumps(values, indent=2), encoding="utf-8")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Save defaults failed", f"Could not save user parameter defaults:\n{exc}")
            return False

    def save_user_parameters_as_default(self) -> None:
        values = self._current_user_params()
        if not self._save_default_user_params(values):
            return
        self.user_param_defaults = values
        self.status_label.setText(f"Status: User parameter defaults saved to {self.DEFAULT_USER_PARAMS_PATH.name}")

    def _load_default_config(self) -> ExperimentConfig:
        path = self.DEFAULT_CONFIG_PATH
        if not path.exists():
            return ExperimentConfig()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ExperimentConfig(
                pulse_width_ms=float(raw.get("pulse_width_ms", 1.0)),
                experiment_length_ms=float(raw.get("experiment_length_ms", 50.0)),
                data_points=int(raw.get("data_points", 4000)),
                averages_per_iteration=int(raw.get("averages_per_iteration", 10)),
                total_iterations=int(raw.get("total_iterations", 50)),
                ai_channel=str(raw.get("ai_channel", "Dev1/ai0")),
                counter_channel=str(raw.get("counter_channel", "Dev1/ctr0")),
                pfi_trigger=str(raw.get("pfi_trigger", "Dev1/PFI0")),
                positive_mode=bool(raw.get("positive_mode", False)),
                use_simulation=bool(raw.get("use_simulation", False)),
            )
        except Exception:
            return ExperimentConfig()

    def _save_default_config(self, config: ExperimentConfig) -> None:
        path = self.DEFAULT_CONFIG_PATH
        try:
            path.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
            self.status_label.setText(f"Status: Defaults saved to {path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "Save defaults failed", f"Could not save defaults:\n{exc}")

    def _refresh_iteration_selector(self) -> None:
        current_index = self.iteration_selector.currentIndex()
        self.iteration_selector.blockSignals(True)
        self.iteration_selector.clear()
        for i in range(1, self.experiment_data.iteration_count() + 1):
            self.iteration_selector.addItem(str(i))
        new_count = self.iteration_selector.count()
        if new_count > 0:
            self.iteration_selector.setCurrentIndex(min(max(current_index, 0), new_count - 1))
        self.iteration_selector.blockSignals(False)
        self.update_line_plot()

    def _on_iteration_selector_changed(self) -> None:
        """Called when user manually changes the iteration selector."""
        if self.follow_latest_checkbox.isChecked():
            self.follow_latest_checkbox.blockSignals(True)
            self.follow_latest_checkbox.setChecked(False)
            self.follow_latest_checkbox.blockSignals(False)
        self.update_line_plot()

    def _append_iteration_selector(self, iteration: int, refresh_plot: bool = True) -> None:
        previous_count = self.iteration_selector.count()
        follow_latest = self.follow_latest_checkbox.isChecked()
        was_showing_latest = (
            previous_count == 0
            or self.iteration_selector.currentIndex() == (previous_count - 1)
            or follow_latest
        )

        self.iteration_selector.blockSignals(True)
        for value in range(previous_count + 1, iteration + 1):
            self.iteration_selector.addItem(str(value))
        if was_showing_latest:
            self.iteration_selector.setCurrentIndex(self.iteration_selector.count() - 1)
        self.iteration_selector.blockSignals(False)

        if was_showing_latest and refresh_plot:
            self.update_line_plot()

    def _time_axis(self, point_count: int) -> np.ndarray:
        """Generate x-axis for plot based on operation mode."""
        if self.config.operation_mode == OperationMode.FTIMS:
            # For FTIMS, generate a generic spectral index axis (0 to data_points-1)
            return np.arange(point_count, dtype=np.float64)
        else:
            # For DTIMS, generate time axis in milliseconds
            if self._time_axis_cache.size != point_count:
                max_time_ms = float(self.config.experiment_length_ms)
                self._time_axis_cache = np.linspace(0.0, max_time_ms, point_count, endpoint=True)
            return self._time_axis_cache

    def update_line_plot(self) -> None:
        if self.experiment_data.iteration_count() == 0:
            self.line_curve.setData([], [])
            self.line_curve_from_heat.setData([], [])
            self.line_baseline_curve.setData([], [])
            self.selected_baseline_curve.setData([], [])
            self._current_line_x = np.array([], dtype=np.float64)
            self._current_line_y = np.array([], dtype=np.float64)
            self._selected_line_x = np.array([], dtype=np.float64)
            self._selected_line_y = np.array([], dtype=np.float64)
            self._line_cursor_locked = False
            self._selected_cursor_locked = False
            cursor_label = "Line cursor: x=-- (Hz), y=--" if self.config.operation_mode == OperationMode.FTIMS else "Line cursor: x=-- ms, y=--"
            self.line_cursor_label.setText(cursor_label)
            if self.config.operation_mode == OperationMode.DTIMS:
                self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")
            else:
                self.ko_label.setText("Peak metrics: --")
            self._clear_peak_readouts()
            self._hide_peak_overlays()
            return

        if self.follow_latest_checkbox.isChecked():
            idx = self.experiment_data.iteration_count() - 1
        else:
            idx = max(0, self.iteration_selector.currentIndex())
            idx = min(idx, self.experiment_data.iteration_count() - 1)
        y = self.experiment_data.get_iteration(idx)
        x = self._time_axis(y.shape[0])
        self._current_line_x = x
        self._current_line_y = y
        self.line_curve.setData(x, y)
        self._update_baseline_overlay("line")
        self._update_auto_axis("line")

    def _set_secondary_line_plot(self, iteration_index: int) -> None:
        if self.experiment_data.iteration_count() == 0:
            self.line_curve_from_heat.setData([], [])
            self.selected_baseline_curve.setData([], [])
            return

        bounded_index = int(np.clip(iteration_index, 0, self.experiment_data.iteration_count() - 1))
        y = self.experiment_data.get_iteration(bounded_index)
        x = self._time_axis(y.shape[0])
        self._selected_line_x = x
        self._selected_line_y = y
        self.line_curve_from_heat.setData(x, y)
        self._update_baseline_overlay("selected")
        self._update_auto_axis("selected")
        self.line_plot_from_heat.setTitle(
            f"IMS Signal (Selected from Heatmap) - Iteration {bounded_index + 1}"
        )

    def _queue_selected_line_plot_update(self, iteration_index: int) -> None:
        self._pending_selected_iteration_index = int(iteration_index)
        if self._selected_plot_update_queued:
            return
        self._selected_plot_update_queued = True
        QTimer.singleShot(0, self._flush_selected_line_plot_update)

    def _flush_selected_line_plot_update(self) -> None:
        self._selected_plot_update_queued = False
        if self._pending_selected_iteration_index is None:
            return
        pending_index = self._pending_selected_iteration_index
        self._pending_selected_iteration_index = None
        self._set_secondary_line_plot(pending_index)

    def update_heatmap(self, force_levels: bool = False) -> None:
        matrix = self.experiment_data.all_iterations_matrix()
        self._heat_matrix = matrix
        self._heat_row_count = matrix.shape[0] if matrix.ndim == 2 else 0
        if matrix.size == 0:
            self.heat_img.setImage(np.zeros((1, 1)))
            self.heat_img.setRect(QRectF(0.0, 0.0, 1.0, 1.0))
            self._heat_levels_initialized = False
            self._heat_cursor_locked = False
            self._selected_heat_iteration_index = None
            self._set_heat_cursor_label()
            return

        auto_levels = force_levels or not self._heat_levels_initialized
        point_count = matrix.shape[1]
        display_stride = 1
        if self._heat_row_count > 0 and point_count > 0:
            total_pixels = self._heat_row_count * point_count
            if total_pixels > self._heat_max_display_pixels:
                display_stride = int(np.ceil(total_pixels / self._heat_max_display_pixels))

        matrix_for_display = matrix[:, ::display_stride]
        self.heat_img.setImage(matrix_for_display.T, autoLevels=auto_levels, axisOrder="row-major")

        max_time_ms = float(self.config.experiment_length_ms)
        row_count = matrix.shape[0]
        self.heat_img.setRect(QRectF(1.0, 0.0, float(row_count), max_time_ms))
        self._update_auto_axis("heat")
        if self._axis_controls["heat"]["auto_z"].isChecked():
            self._autoscale_heat_z()
        else:
            self._apply_heat_z_from_controls()

        if auto_levels:
            self._heat_levels_initialized = True

    def _on_line_mouse_moved(self, event) -> None:
        if self._line_cursor_locked:
            return
        if self._current_line_x.size == 0:
            return

        pos = event[0]
        if not self.line_plot.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.line_plot.plotItem.vb.mapSceneToView(pos)
        mouse_x = float(mouse_point.x())

        nearest_idx = int(np.argmin(np.abs(self._current_line_x - mouse_x)))
        x_val = float(self._current_line_x[nearest_idx])
        y_val = float(self._current_line_y[nearest_idx])

        self.line_cursor_v.setPos(x_val)
        self.line_cursor_h.setPos(y_val)
        status = " [LOCKED]" if self._line_cursor_locked else ""
        if self.config.operation_mode == OperationMode.FTIMS:
            self.line_cursor_label.setText(f"Line cursor: x={x_val:.1f} (index), y={y_val:.6f}{status}")
        else:
            self.line_cursor_label.setText(f"Line cursor: x={x_val:.4f} ms, y={y_val:.6f}{status}")

    def _on_line_mouse_clicked(self, event) -> None:
        if self._current_line_x.size == 0:
            return

        mouse_event = event[0] if isinstance(event, tuple) else event
        if mouse_event.button() != Qt.LeftButton:
            return
        if not self.line_plot.plotItem.vb.sceneBoundingRect().contains(mouse_event.scenePos()):
            return

        mouse_point = self.line_plot.plotItem.vb.mapSceneToView(mouse_event.scenePos())
        mouse_x = float(mouse_point.x())
        nearest_idx = int(np.argmin(np.abs(self._current_line_x - mouse_x)))
        x_val = float(self._current_line_x[nearest_idx])
        y_val = float(self._current_line_y[nearest_idx])

        self._line_cursor_locked = not self._line_cursor_locked
        if self._line_cursor_locked:
            self._selected_cursor_locked = False
            self._current_cursor_x = x_val
            self.line_cursor_v.setPos(x_val)
            self.line_cursor_h.setPos(y_val)
            self._update_ko()
            self._update_peak_metrics(self._current_line_x, self._current_line_y, x_val, "line")
        else:
            self._hide_peak_overlays("line")
            if not self._active_cursor_locked():
                if self.config.operation_mode == OperationMode.DTIMS:
                    self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")
                else:
                    self.ko_label.setText("Peak metrics: --")
                self._clear_peak_readouts()

        base_text = self.line_cursor_label.text().split(" [")[0]
        suffix = " [LOCKED]" if self._line_cursor_locked else ""
        self.line_cursor_label.setText(base_text + suffix)

    def _on_heat_mouse_moved(self, event) -> None:
        if self._heat_cursor_locked:
            return
        matrix = self._heat_matrix
        row_count = self._heat_row_count
        if matrix.size == 0 or row_count == 0:
            return

        pos = event[0]
        if not self.heat_plot.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.heat_plot.vb.mapSceneToView(pos)
        max_time_ms = float(self.config.experiment_length_ms)
        x_val = float(np.clip(mouse_point.x(), 1.0, float(row_count)))
        y_val = float(np.clip(mouse_point.y(), 0.0, max_time_ms))

        self.heat_cursor_v.setPos(x_val)
        self.heat_cursor_h.setPos(y_val)

        iter_idx = int(np.clip(round(x_val - 1.0), 0, row_count - 1))
        point_idx = int(round((y_val / max_time_ms) * (self.config.data_points - 1))) if max_time_ms > 0 else 0
        point_idx = int(np.clip(point_idx, 0, self.config.data_points - 1))
        z_val = float(matrix[iter_idx, point_idx])

        self._set_heat_cursor_label(
            x_iter=x_val,
            y_ms=y_val,
            z_value=z_val,
            locked=self._heat_cursor_locked,
        )

    def _on_heat_mouse_clicked(self, event) -> None:
        if self._heat_row_count == 0:
            return

        mouse_event = event[0] if isinstance(event, tuple) else event
        if mouse_event.button() != Qt.LeftButton:
            return
        if not self.heat_plot.vb.sceneBoundingRect().contains(mouse_event.scenePos()):
            return

        self._heat_cursor_locked = not self._heat_cursor_locked
        mouse_point = self.heat_plot.vb.mapSceneToView(mouse_event.scenePos())
        selected_iter_idx = int(np.clip(round(float(mouse_point.x()) - 1.0), 0, self._heat_row_count - 1))

        max_time_ms = float(self.config.experiment_length_ms)
        x_val = float(np.clip(mouse_point.x(), 1.0, float(self._heat_row_count)))
        y_val = float(np.clip(mouse_point.y(), 0.0, max_time_ms))
        iter_idx = int(np.clip(round(x_val - 1.0), 0, self._heat_row_count - 1))
        point_idx = int(round((y_val / max_time_ms) * (self.config.data_points - 1))) if max_time_ms > 0 else 0
        point_idx = int(np.clip(point_idx, 0, self.config.data_points - 1))
        z_val = float(self._heat_matrix[iter_idx, point_idx])

        if self._heat_cursor_locked:
            self._line_cursor_locked = False
            self._selected_cursor_locked = False
            self._selected_heat_iteration_index = selected_iter_idx
            self._queue_selected_line_plot_update(selected_iter_idx)
            self._set_heat_cursor_label(x_iter=x_val, y_ms=y_val, z_value=z_val, locked=True)
            self._current_cursor_x = y_val
            self._update_ko()
            self._clear_peak_readouts()
            self._hide_peak_overlays()
            return

        self.heat_cursor_v.setPos(x_val)
        self.heat_cursor_h.setPos(y_val)
        self._set_heat_cursor_label(x_iter=x_val, y_ms=y_val, z_value=z_val, locked=False)
        if not self._active_cursor_locked():
            self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")
            self._clear_peak_readouts()
            self._hide_peak_overlays()

    def _on_selected_mouse_moved(self, event) -> None:
        """Handle mouse movement on the Selected Iteration plot."""
        if self._selected_cursor_locked:
            return
        if self._selected_line_x.size == 0:
            return

        pos = event[0]
        if not self.line_plot_from_heat.sceneBoundingRect().contains(pos):
            return

        mouse_point = self.line_plot_from_heat.plotItem.vb.mapSceneToView(pos)
        mouse_x = float(mouse_point.x())

        nearest_idx = int(np.argmin(np.abs(self._selected_line_x - mouse_x)))
        x_val = float(self._selected_line_x[nearest_idx])
        y_val = float(self._selected_line_y[nearest_idx])
        self.selected_cursor_v.setPos(x_val)
        self.selected_cursor_h.setPos(y_val)

    def _on_selected_mouse_clicked(self, event) -> None:
        if self._selected_line_x.size == 0:
            return

        mouse_event = event[0] if isinstance(event, tuple) else event
        if mouse_event.button() != Qt.LeftButton:
            return
        if not self.line_plot_from_heat.plotItem.vb.sceneBoundingRect().contains(mouse_event.scenePos()):
            return

        mouse_point = self.line_plot_from_heat.plotItem.vb.mapSceneToView(mouse_event.scenePos())
        mouse_x = float(mouse_point.x())
        nearest_idx = int(np.argmin(np.abs(self._selected_line_x - mouse_x)))
        x_val = float(self._selected_line_x[nearest_idx])
        y_val = float(self._selected_line_y[nearest_idx])

        self._selected_cursor_locked = not self._selected_cursor_locked
        if self._selected_cursor_locked:
            self._line_cursor_locked = False
            self._heat_cursor_locked = False
            self._current_cursor_x = x_val
            self.selected_cursor_v.setPos(x_val)
            self.selected_cursor_h.setPos(y_val)
            self._update_ko()
            self._update_peak_metrics(self._selected_line_x, self._selected_line_y, x_val, "selected")
        else:
            self._hide_peak_overlays("selected")
            if not self._active_cursor_locked():
                self.ko_label.setText("Reduced Mobility (Ko): -- cm²/(V·s)")
                self._clear_peak_readouts()

    def _update_ftims_frequency_selector(self) -> None:
        """Populate the FTIMS frequency selector with available frequencies."""
        if self.ftims_frequency_selector is None:
            return
        
        # Get sorted frequencies
        frequencies = sorted(self._ftims_raw_time_domain_data.keys())
        
        self.ftims_frequency_selector.blockSignals(True)
        self.ftims_frequency_selector.clear()
        for freq in frequencies:
            self.ftims_frequency_selector.addItem(f"{freq:.1f} Hz", freq)
        self.ftims_frequency_selector.blockSignals(False)
        
        # Connect to handle frequency selection changes
        if self.ftims_frequency_selector.count() > 0:
            self.ftims_frequency_selector.currentIndexChanged.connect(self._on_ftims_frequency_changed)
            self.ftims_frequency_selector.setCurrentIndex(0)
            self._on_ftims_frequency_changed(0)

    def _on_ftims_frequency_changed(self, index: int) -> None:
        """Update the FTIMS raw plot when frequency selection changes."""
        if self.ftims_frequency_selector is None or self.ftims_raw_curve is None:
            return
        
        if index < 0 or self.ftims_frequency_selector.count() == 0:
            self.ftims_raw_curve.setData([], [])
            return
        
        selected_frequency_hz = self.ftims_frequency_selector.itemData(index)
        if selected_frequency_hz is None or selected_frequency_hz not in self._ftims_raw_time_domain_data:
            self.ftims_raw_curve.setData([], [])
            return
        
        signal = self._ftims_raw_time_domain_data[selected_frequency_hz]
        x = np.arange(len(signal), dtype=np.float64)
        self.ftims_raw_curve.setData(x, signal)

    def edit_settings(self) -> None:
        dlg = ExperimentConfigDialog(self.config, self)
        if dlg.exec_():
            self.config = dlg.to_config()
            if dlg.should_save_as_default():
                self._save_default_config(self.config)
            self.experiment_data.reset(self.config)
            self._selected_heat_iteration_index = None
            self._refresh_config_label()
            self._refresh_iteration_selector()
            self.update_heatmap(force_levels=True)
            if self.hv_enabled:
                self.status_label.setText("Status: Settings updated. Click Update HV Values to apply HV changes.")

    def edit_hv_settings(self) -> None:
        dlg = HVConfigDialog(self.hv_config, self)
        if dlg.exec_():
            self.hv_config = dlg.to_config()
            if dlg.should_save_as_default():
                self._save_default_hv_config(self.hv_config)
            if self.hv_enabled:
                self.status_label.setText("Status: HV settings updated. Click Update HV Values to apply.")
            else:
                self._update_hv_status_label(ims_v=0.0, ion_v=0.0)
            self._refresh_hv_control_states()

    def on_hv_toggled(self, checked: bool) -> None:
        try:
            self._start_hv_apply(enabled=bool(checked))
        except Exception as exc:
            QMessageBox.critical(self, "HV output error", str(exc))
            self.hv_enabled = False
            self.btn_hv_enable.blockSignals(True)
            self.btn_hv_enable.setChecked(False)
            self.btn_hv_enable.setText("HV OFF")
            self.btn_hv_enable.blockSignals(False)
            self._apply_hv_background(False)
            self._update_hv_status_label(ims_v=0.0, ion_v=0.0)
            self._refresh_hv_control_states()

    def start_acquisition(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Already running", "Acquisition is already running.")
            return

        self.experiment_data.reset(self.config)
        self._selected_heat_iteration_index = None
        self._time_axis_cache = np.array([], dtype=np.float64)
        self._heat_z_min = None
        self._heat_z_max = None
        self._refresh_iteration_selector()
        self.update_heatmap(force_levels=True)

        self.worker = AcquisitionWorker(self.config)
        self.worker.status.connect(self.on_status)
        self.worker.progress.connect(self.on_progress)
        self.worker.iteration_ready.connect(self.on_iteration_ready)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_edit.setEnabled(False)
        self._refresh_hv_control_states()
        self.worker.start()

    def stop_acquisition(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.status_label.setText("Status: Stopping...")

    def on_status(self, message: str) -> None:
        self.status_label.setText(f"Status: {message}")

    def on_progress(self, iteration: int, total_iterations: int, avg_count: int, avg_total: int, current_frequency_hz: float | None = None, total_frequencies: int | None = None) -> None:
        is_ftims = self.config.operation_mode == OperationMode.FTIMS
        
        if is_ftims and current_frequency_hz is not None and total_frequencies is not None:
            # FTIMS mode: show frequency and average at that frequency
            self.progress_label.setText(
                f"Iteration: {iteration}/{total_iterations} | Frequency: {current_frequency_hz:.1f} Hz | Average: {avg_count}/{avg_total}"
            )
            self._ftims_current_frequency_hz = current_frequency_hz
            self._ftims_current_average_count = avg_count
            self._ftims_total_averages = avg_total
        else:
            # DTIMS mode: show standard progress
            self.progress_label.setText(
                f"Iteration: {iteration}/{total_iterations} | Average: {avg_count}/{avg_total}"
            )

    def on_iteration_ready(self, iteration: int, y: np.ndarray, metadata: dict | None = None) -> None:
        self.experiment_data.add_iteration(y)
        
        # Handle FTIMS raw time-domain data if available
        if metadata is None:
            metadata = {}
        
        if self.config.operation_mode == OperationMode.FTIMS:
            raw_time_domain = metadata.get("raw_time_domain_data", {})
            if raw_time_domain:
                # Convert string keys to floats and numpy arrays
                for freq_str, signal_list in raw_time_domain.items():
                    try:
                        freq = float(freq_str)
                        self._ftims_raw_time_domain_data[freq] = np.asarray(signal_list, dtype=np.float64)
                    except (ValueError, TypeError):
                        pass
                
                # Update frequency selector if this is the first iteration
                if iteration == 1:
                    self._update_ftims_frequency_selector()
                    # Make sure the FTIMS raw data tab is visible
                    if self.plot_tabs is not None:
                        self.plot_tabs.setTabVisible(3, True)
        
        if iteration < 200:
            refresh_every = 5
        elif iteration < 1000:
            refresh_every = 20
        elif iteration < 3000:
            refresh_every = 50
        else:
            refresh_every = 100

        should_refresh_heatmap = (
            iteration == 1
            or iteration % refresh_every == 0
            or iteration == self.config.total_iterations
        )
        should_refresh_selector = should_refresh_heatmap or iteration == 1
        if should_refresh_selector:
            self._append_iteration_selector(iteration, refresh_plot=False)

        # Always update the line plot when follow-latest is on; otherwise throttle it
        if self.follow_latest_checkbox.isChecked():
            self.update_line_plot()
        elif should_refresh_heatmap:
            self.update_line_plot()

        y_min = float(np.min(y))
        y_max = float(np.max(y))
        if self._heat_z_min is None or y_min < self._heat_z_min:
            self._heat_z_min = y_min
        if self._heat_z_max is None or y_max > self._heat_z_max:
            self._heat_z_max = y_max

        if should_refresh_heatmap:
            self.update_heatmap()

        self.status_label.setText(f"Status: Iteration {iteration} complete")

    def on_finished(self) -> None:
        self._append_iteration_selector(self.experiment_data.iteration_count(), refresh_plot=False)
        self.update_line_plot()
        self.update_heatmap()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_edit.setEnabled(True)
        self._refresh_hv_control_states()

    def on_failed(self, message: str) -> None:
        self.on_finished()
        QMessageBox.critical(self, "Acquisition error", message)
        self.status_label.setText("Status: Error")
        self._refresh_hv_control_states()

    def save_csv(self) -> None:
        if self.experiment_data.iteration_count() == 0:
            QMessageBox.warning(self, "No data", "No experiment data to save.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV (*.csv)")
        if not file_path:
            return
        ExperimentExporter.to_csv(file_path, self.experiment_data)

    def save_hdf5(self) -> None:
        if self.experiment_data.iteration_count() == 0:
            QMessageBox.warning(self, "No data", "No experiment data to save.")
            return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save HDF5", "", "HDF5 (*.h5 *.hdf5)")
        if not file_path:
            return
        ExperimentExporter.to_hdf5(file_path, self.experiment_data)

    def load_hdf5(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Load HDF5", "", "HDF5 (*.h5 *.hdf5)")
        if not file_path:
            return
        loaded = ExperimentImporter.from_hdf5(file_path)
        self.config = loaded.config
        self.experiment_data = loaded
        self._selected_heat_iteration_index = None
        self._time_axis_cache = np.array([], dtype=np.float64)
        loaded_matrix = self.experiment_data.all_iterations_matrix()
        if loaded_matrix.size > 0:
            self._heat_z_min = float(np.min(loaded_matrix))
            self._heat_z_max = float(np.max(loaded_matrix))
        else:
            self._heat_z_min = None
            self._heat_z_max = None
        self._refresh_config_label()
        self._refresh_iteration_selector()
        self.update_heatmap(force_levels=True)
        if self.hv_enabled:
            try:
                self._set_hv_outputs(enabled=True, silent=False)
            except Exception as exc:
                QMessageBox.critical(self, "HV output error", str(exc))
                self._set_hv_outputs(enabled=False, silent=True)
        self.status_label.setText(f"Status: Loaded {Path(file_path).name}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(3000)
        if self.hv_worker is not None and self.hv_worker.isRunning():
            self.hv_worker.request_stop()
            self.hv_worker.wait(200)

        if self.hv_enabled:
            try:
                payload = self._build_hv_payload(enabled=False, ims_v=0.0, ion_v=0.0)
                self._run_hv_payload_sync(payload=payload, timeout_seconds=10.0)
                self.hv_enabled = False
                self.btn_hv_enable.blockSignals(True)
                self.btn_hv_enable.setChecked(False)
                self.btn_hv_enable.setText("HV OFF")
                self.btn_hv_enable.blockSignals(False)
                self._apply_hv_background(False)
                self._update_hv_status_label(ims_v=0.0, ion_v=0.0)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "HV shutdown warning",
                    f"Failed to switch HV OFF before exit:\n{exc}",
                )
        event.accept()
