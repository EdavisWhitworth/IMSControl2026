from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt5.QtCore import QRectF, Qt
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
from ims_control.data_model.experiment import ExperimentConfig, ExperimentData
from ims_control.io.export_import import ExperimentExporter, ExperimentImporter
from ims_control.ui.config_dialog import ExperimentConfigDialog


class MainWindow(QMainWindow):
    DEFAULT_CONFIG_PATH = Path.home() / ".ims_control_defaults.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("IMS Control")
        self.resize(1200, 780)

        self.config = self._load_default_config()
        self.experiment_data = ExperimentData(self.config)
        self.worker: AcquisitionWorker | None = None
        self._heat_levels_initialized = False
        self._current_line_x = np.array([], dtype=np.float64)
        self._current_line_y = np.array([], dtype=np.float64)
        self._line_cursor_locked = False
        self._heat_cursor_locked = False
        self._heat_row_count = 0
        self._heat_matrix = np.empty((0, 0), dtype=np.float64)
        self._selected_heat_iteration_index = None
        self._selected_line_x = np.array([], dtype=np.float64)
        self._selected_line_y = np.array([], dtype=np.float64)
        self._axis_controls: dict[str, dict[str, object]] = {}

        self._build_ui()
        self._refresh_config_label()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QGridLayout(central)
        root.setColumnStretch(0, 0)
        root.setColumnStretch(1, 1)
        self.setCentralWidget(central)

        control_box = QGroupBox("Control")
        control_box.setMinimumWidth(430)
        control_box.setMaximumWidth(430)
        control_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        control_layout = QVBoxLayout(control_box)

        row1 = QHBoxLayout()
        self.btn_edit = QPushButton("Edit Settings")
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        row1.addWidget(self.btn_edit)
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        control_layout.addLayout(row1)

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
        control_layout.addWidget(self.config_label)

        self.status_label = QLabel("Status: Idle")
        self.progress_label = QLabel("Iteration: 0/0 | Average: 0/0")
        self.line_cursor_label = QLabel("Line cursor: x=-- ms, y=--")
        self.heat_cursor_label = QLabel("Heat cursor: x=-- (iter), y=-- ms")
        self.status_label.setMinimumWidth(395)
        self.progress_label.setMinimumWidth(395)
        self.line_cursor_label.setMinimumWidth(395)
        self.heat_cursor_label.setMinimumWidth(395)
        control_layout.addWidget(self.status_label)
        control_layout.addWidget(self.progress_label)
        control_layout.addWidget(self.line_cursor_label)
        control_layout.addWidget(self.heat_cursor_label)
        control_layout.addStretch()

        plot_tabs = QTabWidget()

        line_tab = QWidget()
        line_layout = QVBoxLayout(line_tab)
        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Display iteration:"))
        self.iteration_selector = QComboBox()
        chooser.addWidget(self.iteration_selector)
        chooser.addStretch()
        line_layout.addLayout(chooser)

        self.line_plot = pg.PlotWidget(title="IMS Signal")
        self.line_plot.setLabel("left", "Signal")
        self.line_plot.setLabel("bottom", "Time (ms)")
        self.line_curve = self.line_plot.plot(pen=pg.mkPen(width=2))
        self.line_cursor_v = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("y", width=1))
        self.line_cursor_h = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("y", width=1))
        self.line_plot.addItem(self.line_cursor_v, ignoreBounds=True)
        self.line_plot.addItem(self.line_cursor_h, ignoreBounds=True)
        line_layout.addWidget(self.line_plot)
        self._axis_controls["line"] = self._create_axis_controls(line_layout, "line")

        heat_tab = QWidget()
        heat_layout = QVBoxLayout(heat_tab)
        self.heat_view = pg.GraphicsLayoutWidget()
        self.heat_plot = self.heat_view.addPlot(title="Iterations Heatmap")
        self.heat_plot.setLabel("left", "Time (ms)")
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
        self.line_plot_from_heat = pg.PlotWidget(title="IMS Signal (Selected from Heatmap)")
        self.line_plot_from_heat.setLabel("left", "Signal")
        self.line_plot_from_heat.setLabel("bottom", "Time (ms)")
        self.line_curve_from_heat = self.line_plot_from_heat.plot(pen=pg.mkPen("m", width=2))
        selected_layout.addWidget(self.line_plot_from_heat)
        self._axis_controls["selected"] = self._create_axis_controls(selected_layout, "selected")

        plot_tabs.addTab(line_tab, "Line Plot")
        plot_tabs.addTab(heat_tab, "2D Colormap")
        plot_tabs.addTab(selected_tab, "Selected Iteration")

        root.addWidget(control_box, 0, 0)
        root.addWidget(plot_tabs, 0, 1)

        self.btn_edit.clicked.connect(self.edit_settings)
        self.btn_start.clicked.connect(self.start_acquisition)
        self.btn_stop.clicked.connect(self.stop_acquisition)
        self.btn_save_csv.clicked.connect(self.save_csv)
        self.btn_save_h5.clicked.connect(self.save_hdf5)
        self.btn_load_h5.clicked.connect(self.load_hdf5)
        self.iteration_selector.currentIndexChanged.connect(self.update_line_plot)

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

        self._on_auto_axis_toggled("line")
        self._on_auto_axis_toggled("heat")
        self._on_auto_axis_toggled("selected")

        self._refresh_iteration_selector()

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
        if self._heat_matrix.size == 0:
            return None
        z_min_value = float(np.min(self._heat_matrix))
        z_max_value = float(np.max(self._heat_matrix))
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

    def _refresh_config_label(self) -> None:
        cfg = self.config
        text = (
            f"Pulse width: {cfg.pulse_width_ms} ms\n"
            f"Length: {cfg.experiment_length_ms} ms\n"
            f"Data points: {cfg.data_points}\n"
            f"Averages: {cfg.averages_per_iteration}\n"
            f"Iterations: {cfg.total_iterations}\n"
            f"AI: {cfg.ai_channel}\n"
            f"Counter: {cfg.counter_channel}\n"
            f"PFI trigger: {cfg.pfi_trigger}\n"
            f"Polarity: {'Positive' if cfg.positive_mode else 'Negative'}\n"
            f"Acquisition mode: {'Simulation' if cfg.use_simulation else 'Hardware'}"
        )
        self.config_label.setText(text)

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

    def _append_iteration_selector(self, iteration: int) -> None:
        previous_count = self.iteration_selector.count()
        was_showing_latest = previous_count == 0 or self.iteration_selector.currentIndex() == (previous_count - 1)

        self.iteration_selector.blockSignals(True)
        self.iteration_selector.addItem(str(iteration))
        if was_showing_latest:
            self.iteration_selector.setCurrentIndex(self.iteration_selector.count() - 1)
        self.iteration_selector.blockSignals(False)

        if was_showing_latest:
            self.update_line_plot()

    def update_line_plot(self) -> None:
        if self.experiment_data.iteration_count() == 0:
            self.line_curve.setData([], [])
            self.line_curve_from_heat.setData([], [])
            self._current_line_x = np.array([], dtype=np.float64)
            self._current_line_y = np.array([], dtype=np.float64)
            self._selected_line_x = np.array([], dtype=np.float64)
            self._selected_line_y = np.array([], dtype=np.float64)
            self._line_cursor_locked = False
            self.line_cursor_label.setText("Line cursor: x=-- ms, y=--")
            return

        idx = max(0, self.iteration_selector.currentIndex())
        idx = min(idx, self.experiment_data.iteration_count() - 1)
        y = self.experiment_data.get_iteration(idx)
        max_time_ms = float(self.config.experiment_length_ms)
        x = np.linspace(0.0, max_time_ms, y.shape[0], endpoint=True)
        self._current_line_x = x
        self._current_line_y = y
        self.line_curve.setData(x, y)
        self._update_auto_axis("line")

    def _set_secondary_line_plot(self, iteration_index: int) -> None:
        if self.experiment_data.iteration_count() == 0:
            self.line_curve_from_heat.setData([], [])
            return

        bounded_index = int(np.clip(iteration_index, 0, self.experiment_data.iteration_count() - 1))
        y = self.experiment_data.get_iteration(bounded_index)
        max_time_ms = float(self.config.experiment_length_ms)
        x = np.linspace(0.0, max_time_ms, y.shape[0], endpoint=True)
        self._selected_line_x = x
        self._selected_line_y = y
        self.line_curve_from_heat.setData(x, y)
        self._update_auto_axis("selected")
        self.line_plot_from_heat.setTitle(
            f"IMS Signal (Selected from Heatmap) - Iteration {bounded_index + 1}"
        )

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
        self.heat_img.setImage(matrix.T, autoLevels=auto_levels, axisOrder="row-major")

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
        self.line_cursor_label.setText(f"Line cursor: x={x_val:.4f} ms, y={y_val:.6f}{status}")

    def _on_line_mouse_clicked(self, event) -> None:
        if self._current_line_x.size == 0:
            return

        mouse_event = event[0] if isinstance(event, tuple) else event
        if mouse_event.button() != Qt.LeftButton:
            return
        if not self.line_plot.plotItem.vb.sceneBoundingRect().contains(mouse_event.scenePos()):
            return

        self._line_cursor_locked = not self._line_cursor_locked
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
            self._selected_heat_iteration_index = selected_iter_idx
            self._set_secondary_line_plot(selected_iter_idx)
            self._set_heat_cursor_label(x_iter=x_val, y_ms=y_val, z_value=z_val, locked=True)
            return

        self.heat_cursor_v.setPos(x_val)
        self.heat_cursor_h.setPos(y_val)
        self._set_heat_cursor_label(x_iter=x_val, y_ms=y_val, z_value=z_val, locked=False)

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

    def start_acquisition(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Already running", "Acquisition is already running.")
            return

        self.experiment_data.reset(self.config)
        self._selected_heat_iteration_index = None
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
        self.worker.start()

    def stop_acquisition(self) -> None:
        if self.worker is not None:
            self.worker.request_stop()
            self.status_label.setText("Status: Stopping...")

    def on_status(self, message: str) -> None:
        self.status_label.setText(f"Status: {message}")

    def on_progress(self, iteration: int, total_iterations: int, avg_count: int, avg_total: int) -> None:
        self.progress_label.setText(
            f"Iteration: {iteration}/{total_iterations} | Average: {avg_count}/{avg_total}"
        )

    def on_iteration_ready(self, iteration: int, y: np.ndarray) -> None:
        self.experiment_data.add_iteration(y)
        self._append_iteration_selector(iteration)

        if iteration < 200:
            refresh_every = 5
        elif iteration < 1000:
            refresh_every = 20
        else:
            refresh_every = 50
        if iteration % refresh_every == 0 or iteration == self.config.total_iterations:
            self.update_heatmap()

        self.status_label.setText(f"Status: Iteration {iteration} complete")

    def on_finished(self) -> None:
        self.update_heatmap()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_edit.setEnabled(True)

    def on_failed(self, message: str) -> None:
        self.on_finished()
        QMessageBox.critical(self, "Acquisition error", message)
        self.status_label.setText("Status: Error")

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
        self._refresh_config_label()
        self._refresh_iteration_selector()
        self.update_heatmap(force_levels=True)
        self.status_label.setText(f"Status: Loaded {Path(file_path).name}")

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(3000)
        event.accept()
