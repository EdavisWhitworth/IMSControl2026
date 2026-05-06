from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QGroupBox,
)

from ims_control.data_model.experiment import ExperimentConfig, OperationMode, FTIMSConfig, SteppedVSIMSConfig


class ExperimentConfigDialog(QDialog):
    def __init__(self, config: ExperimentConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experiment Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Mode selection
        self.operation_mode = QComboBox()
        self.operation_mode.addItems(["DTIMS", "FTIMS", "Stepped VSIMS"])
        if config.operation_mode == OperationMode.STEPPED_VSIMS:
            self.operation_mode.setCurrentText("Stepped VSIMS")
        else:
            self.operation_mode.setCurrentText(config.operation_mode.value)
        self._last_mode_text = self.operation_mode.currentText()
        self.operation_mode.currentTextChanged.connect(self._on_mode_changed)

        # DTIMS controls (timing-based)
        self.pulse_width_ms = QDoubleSpinBox()
        self.pulse_width_ms.setDecimals(3)
        self.pulse_width_ms.setRange(0.001, 1000.0)
        self.pulse_width_ms.setValue(config.pulse_width_ms)

        self.experiment_length_ms = QDoubleSpinBox()
        self.experiment_length_ms.setDecimals(3)
        self.experiment_length_ms.setRange(1.0, 2000.0)
        self.experiment_length_ms.setValue(config.experiment_length_ms)

        # Common controls
        self.data_points = QSpinBox()
        self.data_points.setRange(100, 500000)
        self.data_points.setValue(config.data_points)

        self.averages = QSpinBox()
        self.averages.setRange(1, 5000)
        self.averages.setValue(config.averages_per_iteration)

        self.iterations = QSpinBox()
        self.iterations.setRange(1, 100000)
        self.iterations.setValue(config.total_iterations)

        self.ai_channel = QLineEdit(config.ai_channel)
        self.counter_channel = QLineEdit(config.counter_channel)
        self.pfi_trigger = QLineEdit(config.pfi_trigger)

        self.polarity_mode = QComboBox()
        self.polarity_mode.addItems(["Negative", "Positive"])
        self.polarity_mode.setCurrentText("Positive" if config.positive_mode else "Negative")

        self.simulation = QCheckBox("Use simulation mode")
        self.simulation.setChecked(config.use_simulation)
        
        self.save_defaults = QCheckBox("Save as default")
        self.save_defaults.setChecked(False)

        # FTIMS controls (frequency-based)
        ftims_cfg = config.ftims_config or FTIMSConfig()
        
        self.start_frequency_hz = QDoubleSpinBox()
        self.start_frequency_hz.setDecimals(1)
        self.start_frequency_hz.setRange(1.0, 1000.0)
        self.start_frequency_hz.setValue(ftims_cfg.start_frequency_hz)

        self.frequency_step_hz = QDoubleSpinBox()
        self.frequency_step_hz.setDecimals(1)
        self.frequency_step_hz.setRange(0.1, 100.0)
        self.frequency_step_hz.setValue(ftims_cfg.frequency_step_hz)

        self.end_frequency_hz = QDoubleSpinBox()
        self.end_frequency_hz.setDecimals(0)
        self.end_frequency_hz.setRange(10.0, 10000.0)
        self.end_frequency_hz.setValue(ftims_cfg.end_frequency_hz)

        self.frequency_info = QLabel()
        self._update_frequency_info()

        # VSIMS controls (voltage-stepped)
        vsims_cfg = config.vsims_config or SteppedVSIMSConfig()

        self.initial_voltage_kv = QDoubleSpinBox()
        self.initial_voltage_kv.setDecimals(3)
        self.initial_voltage_kv.setRange(0.1, 30.0)
        self.initial_voltage_kv.setValue(vsims_cfg.initial_voltage_kv)
        self.initial_voltage_kv.setSuffix(" kV")

        self.final_voltage_kv = QDoubleSpinBox()
        self.final_voltage_kv.setDecimals(3)
        self.final_voltage_kv.setRange(0.1, 30.0)
        self.final_voltage_kv.setValue(vsims_cfg.final_voltage_kv)
        self.final_voltage_kv.setSuffix(" kV")

        self.voltage_step_v = QDoubleSpinBox()
        self.voltage_step_v.setDecimals(1)
        self.voltage_step_v.setRange(1.0, 2000.0)
        self.voltage_step_v.setValue(vsims_cfg.voltage_step_v)
        self.voltage_step_v.setSuffix(" V")

        self.ionization_bias_kv = QDoubleSpinBox()
        self.ionization_bias_kv.setDecimals(3)
        self.ionization_bias_kv.setRange(-1000.0, 1000.0)
        self.ionization_bias_kv.setValue(vsims_cfg.ionization_bias_kv)
        self.ionization_bias_kv.setSuffix(" kV")

        self.vsims_info = QLabel()
        self._update_vsims_info()

        # Build form layout
        form.addRow("Operation Mode", self.operation_mode)
        
        # DTIMS section
        self.dtims_group = QGroupBox("DTIMS Settings")
        dtims_form = QFormLayout()
        dtims_form.addRow("Pulse width (ms)", self.pulse_width_ms)
        dtims_form.addRow("Experiment length (ms)", self.experiment_length_ms)
        self.dtims_group.setLayout(dtims_form)

        # FTIMS section
        self.ftims_group = QGroupBox("FTIMS Settings")
        ftims_form = QFormLayout()
        ftims_form.addRow("Start frequency (Hz)", self.start_frequency_hz)
        ftims_form.addRow("Frequency step (Hz)", self.frequency_step_hz)
        ftims_form.addRow("End frequency (Hz)", self.end_frequency_hz)
        ftims_form.addRow("", self.frequency_info)
        self.ftims_group.setLayout(ftims_form)

        self.vsims_group = QGroupBox("Stepped VSIMS Settings")
        vsims_form = QFormLayout()
        vsims_form.addRow("Initial voltage", self.initial_voltage_kv)
        vsims_form.addRow("Final voltage", self.final_voltage_kv)
        vsims_form.addRow("Voltage step", self.voltage_step_v)
        vsims_form.addRow("Ionization bias", self.ionization_bias_kv)
        vsims_form.addRow("", self.vsims_info)
        self.vsims_group.setLayout(vsims_form)

        form.addRow(self.dtims_group)
        form.addRow(self.ftims_group)
        form.addRow(self.vsims_group)

        # Common settings
        form.addRow("Data points", self.data_points)
        form.addRow("Averages per iteration", self.averages)
        form.addRow("Total iterations", self.iterations)
        form.addRow("AI channel", self.ai_channel)
        form.addRow("Counter channel", self.counter_channel)
        form.addRow("PFI trigger", self.pfi_trigger)
        form.addRow("Polarity mode", self.polarity_mode)
        form.addRow("Mode", self.simulation)
        form.addRow("Defaults", self.save_defaults)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Connect frequency controls to update info
        self.start_frequency_hz.valueChanged.connect(self._update_frequency_info)
        self.frequency_step_hz.valueChanged.connect(self._update_frequency_info)
        self.end_frequency_hz.valueChanged.connect(self._update_frequency_info)
        self.averages.valueChanged.connect(self._update_frequency_info)
        self.iterations.valueChanged.connect(self._update_frequency_info)

        self.initial_voltage_kv.valueChanged.connect(self._update_vsims_info)
        self.final_voltage_kv.valueChanged.connect(self._update_vsims_info)
        self.voltage_step_v.valueChanged.connect(self._update_vsims_info)
        self.averages.valueChanged.connect(self._update_vsims_info)
        self.iterations.valueChanged.connect(self._update_vsims_info)
        self.experiment_length_ms.valueChanged.connect(self._update_vsims_info)

        # Initial visibility
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        """Toggle visibility of DTIMS/FTIMS controls based on selected mode."""
        mode = self.operation_mode.currentText()
        is_ftims = mode == "FTIMS"
        is_vsims = mode == "Stepped VSIMS"
        if is_vsims and self._last_mode_text != "Stepped VSIMS":
            self.pulse_width_ms.setValue(0.2)
            self.experiment_length_ms.setValue(50.0)
        self.dtims_group.setVisible(not is_ftims)
        self.ftims_group.setVisible(is_ftims)
        self.vsims_group.setVisible(is_vsims)
        self._last_mode_text = mode

    def _update_frequency_info(self) -> None:
        """Update frequency step info display."""
        try:
            ftims_cfg = FTIMSConfig(
                start_frequency_hz=self.start_frequency_hz.value(),
                frequency_step_hz=self.frequency_step_hz.value(),
                end_frequency_hz=self.end_frequency_hz.value(),
            )
            num_steps = ftims_cfg.total_frequencies()
            step_sec = ftims_cfg.step_duration_seconds(self.averages.value())
            duration_sec = ftims_cfg.estimated_duration_seconds(self.averages.value())
            total_duration_sec = duration_sec * float(self.iterations.value())
            self.frequency_info.setText(
                f"Frequency steps: {num_steps}  |  Step time: {step_sec:.3f}s  |  "
                f"Est. sweep: {duration_sec:.1f}s  |  Est. total: {total_duration_sec:.1f}s"
            )
        except Exception:
            self.frequency_info.setText("Invalid frequency configuration")

    def _update_vsims_info(self) -> None:
        try:
            vsims_cfg = SteppedVSIMSConfig(
                initial_voltage_kv=self.initial_voltage_kv.value(),
                final_voltage_kv=self.final_voltage_kv.value(),
                voltage_step_v=self.voltage_step_v.value(),
            )
            points = vsims_cfg.total_voltages()
            est_s = vsims_cfg.estimated_duration_seconds(
                experiment_length_ms=self.experiment_length_ms.value(),
                averages_per_iteration=self.averages.value(),
                total_iterations=self.iterations.value(),
            )
            self.vsims_info.setText(f"Voltage points: {points}  |  Est. duration: {est_s:.1f}s")
        except Exception:
            self.vsims_info.setText("Invalid VSIMS voltage configuration")

    def to_config(self) -> ExperimentConfig:
        if self.operation_mode.currentText() == "FTIMS":
            mode = OperationMode.FTIMS
        elif self.operation_mode.currentText() == "Stepped VSIMS":
            mode = OperationMode.STEPPED_VSIMS
        else:
            mode = OperationMode.DTIMS
        
        ftims_config = FTIMSConfig(
            start_frequency_hz=self.start_frequency_hz.value(),
            frequency_step_hz=self.frequency_step_hz.value(),
            end_frequency_hz=self.end_frequency_hz.value(),
        ) if mode == OperationMode.FTIMS else FTIMSConfig()

        vsims_config = SteppedVSIMSConfig(
            initial_voltage_kv=self.initial_voltage_kv.value(),
            final_voltage_kv=self.final_voltage_kv.value(),
            voltage_step_v=self.voltage_step_v.value(),
            time_add_ms=0.0,
            ionization_bias_kv=self.ionization_bias_kv.value(),
        ) if mode == OperationMode.STEPPED_VSIMS else SteppedVSIMSConfig()

        # For FTIMS mode, set pulse_width_ms to 50% of time_per_frequency_ms for proper duty cycle
        # For DTIMS mode, use the configured pulse_width_ms
        if mode == OperationMode.FTIMS:
            step_ms = ftims_config.step_duration_ms(self.averages.value())
            pulse_width = step_ms / 2.0
            experiment_length = step_ms
            ftims_config.time_per_frequency_ms = step_ms
        else:
            pulse_width = float(self.pulse_width_ms.value())
            experiment_length = float(self.experiment_length_ms.value())

        return ExperimentConfig(
            operation_mode=mode,
            pulse_width_ms=pulse_width,
            experiment_length_ms=experiment_length,
            data_points=int(self.data_points.value()),
            averages_per_iteration=int(self.averages.value()),
            total_iterations=int(self.iterations.value()),
            ai_channel=self.ai_channel.text().strip() or "Dev1/ai0",
            counter_channel=self.counter_channel.text().strip() or "Dev1/ctr0",
            pfi_trigger=self.pfi_trigger.text().strip() or "Dev1/PFI0",
            positive_mode=self.polarity_mode.currentText() == "Positive",
            use_simulation=self.simulation.isChecked(),
            ftims_config=ftims_config,
            vsims_config=vsims_config,
        )

    def should_save_as_default(self) -> bool:
        return self.save_defaults.isChecked()
