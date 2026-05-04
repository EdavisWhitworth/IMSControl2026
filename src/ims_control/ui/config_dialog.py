from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ims_control.data_model.experiment import ExperimentConfig


class ExperimentConfigDialog(QDialog):
    def __init__(self, config: ExperimentConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experiment Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.pulse_width_ms = QDoubleSpinBox()
        self.pulse_width_ms.setDecimals(3)
        self.pulse_width_ms.setRange(0.001, 1000.0)
        self.pulse_width_ms.setValue(config.pulse_width_ms)

        self.experiment_length_ms = QDoubleSpinBox()
        self.experiment_length_ms.setDecimals(3)
        self.experiment_length_ms.setRange(1.0, 2000.0)
        self.experiment_length_ms.setValue(config.experiment_length_ms)

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

        form.addRow("Pulse width (ms)", self.pulse_width_ms)
        form.addRow("Experiment length (ms)", self.experiment_length_ms)
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

    def to_config(self) -> ExperimentConfig:
        return ExperimentConfig(
            pulse_width_ms=float(self.pulse_width_ms.value()),
            experiment_length_ms=float(self.experiment_length_ms.value()),
            data_points=int(self.data_points.value()),
            averages_per_iteration=int(self.averages.value()),
            total_iterations=int(self.iterations.value()),
            ai_channel=self.ai_channel.text().strip() or "Dev1/ai0",
            counter_channel=self.counter_channel.text().strip() or "Dev1/ctr0",
            pfi_trigger=self.pfi_trigger.text().strip() or "Dev1/PFI0",
            positive_mode=self.polarity_mode.currentText() == "Positive",
            use_simulation=self.simulation.isChecked(),
        )

    def should_save_as_default(self) -> bool:
        return self.save_defaults.isChecked()
