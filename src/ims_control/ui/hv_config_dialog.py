from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)

from ims_control.data_model.experiment import HVPowerConfig


class HVConfigDialog(QDialog):
    def __init__(self, config: HVPowerConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("HV Parameters")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.ims_ao_channel = QLineEdit(config.ims_ao_channel)
        self.ion_ao_channel = QLineEdit(config.ion_ao_channel)
        self.hv_enable_do_line = QLineEdit(config.hv_enable_do_line)

        self.ims_max_output_kv = QDoubleSpinBox()
        self.ims_max_output_kv.setDecimals(3)
        self.ims_max_output_kv.setRange(0.001, 1000.0)
        self.ims_max_output_kv.setValue(config.ims_max_output_kv)
        self.ims_max_output_kv.setSuffix(" kV")

        self.control_voltage_max_v = QDoubleSpinBox()
        self.control_voltage_max_v.setDecimals(3)
        self.control_voltage_max_v.setRange(0.1, 20.0)
        self.control_voltage_max_v.setValue(config.control_voltage_max_v)
        self.control_voltage_max_v.setSuffix(" V")

        self.ims_setpoint_kv = QDoubleSpinBox()
        self.ims_setpoint_kv.setDecimals(3)
        self.ims_setpoint_kv.setRange(0.0, 1000.0)
        self.ims_setpoint_kv.setValue(config.ims_setpoint_kv)
        self.ims_setpoint_kv.setSuffix(" kV")

        self.ionization_bias_kv = QDoubleSpinBox()
        self.ionization_bias_kv.setDecimals(3)
        self.ionization_bias_kv.setRange(-1000.0, 1000.0)
        self.ionization_bias_kv.setValue(config.ionization_bias_kv)
        self.ionization_bias_kv.setSuffix(" kV")

        self.save_defaults = QCheckBox("Save as default")
        self.save_defaults.setChecked(False)

        form.addRow("IMS AO channel", self.ims_ao_channel)
        form.addRow("Ionization AO channel", self.ion_ao_channel)
        form.addRow("HV enable DO line", self.hv_enable_do_line)
        form.addRow("IMS max output", self.ims_max_output_kv)
        form.addRow("Control voltage max", self.control_voltage_max_v)
        form.addRow("IMS setpoint", self.ims_setpoint_kv)
        form.addRow("Ionization bias", self.ionization_bias_kv)
        form.addRow("Defaults", self.save_defaults)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def to_config(self) -> HVPowerConfig:
        return HVPowerConfig(
            ims_ao_channel=self.ims_ao_channel.text().strip() or "Dev1/ao0",
            ion_ao_channel=self.ion_ao_channel.text().strip() or "Dev1/ao1",
            hv_enable_do_line=self.hv_enable_do_line.text().strip() or "Dev1/port0/line0",
            ims_max_output_kv=float(self.ims_max_output_kv.value()),
            control_voltage_max_v=float(self.control_voltage_max_v.value()),
            ims_setpoint_kv=float(self.ims_setpoint_kv.value()),
            ionization_bias_kv=float(self.ionization_bias_kv.value()),
            save_as_default=self.save_defaults.isChecked(),
        )

    def should_save_as_default(self) -> bool:
        return self.save_defaults.isChecked()
