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

from ims_control.data_model.experiment import ExperimentConfig, OperationMode, FTIMSConfig


class ExperimentConfigDialog(QDialog):
    def __init__(self, config: ExperimentConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experiment Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Mode selection
        self.operation_mode = QComboBox()
        self.operation_mode.addItems(["DTIMS", "FTIMS"])
        self.operation_mode.setCurrentText(config.operation_mode.value)
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

        self.time_per_frequency_ms = QDoubleSpinBox()
        self.time_per_frequency_ms.setDecimals(0)
        self.time_per_frequency_ms.setRange(100.0, 10000.0)
        self.time_per_frequency_ms.setValue(ftims_cfg.time_per_frequency_ms)

        self.frequency_info = QLabel()
        self._update_frequency_info()

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
        ftims_form.addRow("Time per frequency (ms)", self.time_per_frequency_ms)
        ftims_form.addRow("", self.frequency_info)
        self.ftims_group.setLayout(ftims_form)

        form.addRow(self.dtims_group)
        form.addRow(self.ftims_group)

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
        self.time_per_frequency_ms.valueChanged.connect(self._update_frequency_info)

        # Initial visibility
        self._on_mode_changed()

    def _on_mode_changed(self) -> None:
        """Toggle visibility of DTIMS/FTIMS controls based on selected mode."""
        is_ftims = self.operation_mode.currentText() == "FTIMS"
        self.dtims_group.setVisible(not is_ftims)
        self.ftims_group.setVisible(is_ftims)

    def _update_frequency_info(self) -> None:
        """Update frequency step info display."""
        try:
            ftims_cfg = FTIMSConfig(
                start_frequency_hz=self.start_frequency_hz.value(),
                frequency_step_hz=self.frequency_step_hz.value(),
                end_frequency_hz=self.end_frequency_hz.value(),
                time_per_frequency_ms=self.time_per_frequency_ms.value(),
            )
            num_steps = ftims_cfg.total_frequencies()
            duration_sec = ftims_cfg.estimated_duration_seconds()
            self.frequency_info.setText(
                f"Frequency steps: {num_steps}  |  Est. duration: {duration_sec:.1f}s"
            )
        except Exception:
            self.frequency_info.setText("Invalid frequency configuration")

    def to_config(self) -> ExperimentConfig:
        mode = OperationMode.FTIMS if self.operation_mode.currentText() == "FTIMS" else OperationMode.DTIMS
        
        ftims_config = FTIMSConfig(
            start_frequency_hz=self.start_frequency_hz.value(),
            frequency_step_hz=self.frequency_step_hz.value(),
            end_frequency_hz=self.end_frequency_hz.value(),
            time_per_frequency_ms=self.time_per_frequency_ms.value(),
        ) if mode == OperationMode.FTIMS else FTIMSConfig()

        # For FTIMS mode, set pulse_width_ms to 50% of time_per_frequency_ms for proper duty cycle
        # For DTIMS mode, use the configured pulse_width_ms
        if mode == OperationMode.FTIMS:
            pulse_width = ftims_config.time_per_frequency_ms / 2.0
            experiment_length = ftims_config.time_per_frequency_ms
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
        )

    def should_save_as_default(self) -> bool:
        return self.save_defaults.isChecked()
