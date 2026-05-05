from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Dict, List

import numpy as np


@dataclass
class ExperimentConfig:
    pulse_width_ms: float = 1.0
    experiment_length_ms: float = 50.0
    data_points: int = 4000
    averages_per_iteration: int = 10
    total_iterations: int = 50
    ai_channel: str = "Dev1/ai0"
    counter_channel: str = "Dev1/ctr0"
    pfi_trigger: str = "Dev1/PFI0"
    positive_mode: bool = False
    use_simulation: bool = False

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


@dataclass
class HVPowerConfig:
    ims_ao_channel: str = "Dev1/ao0"
    ion_ao_channel: str = "Dev1/ao1"
    hv_enable_do_line: str = "Dev1/port0/line0"
    ims_max_output_kv: float = 20.0
    control_voltage_max_v: float = 10.0
    ims_setpoint_kv: float = 10.0
    ionization_bias_kv: float = 0.0
    save_as_default: bool = False

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "HVPowerConfig":
        return cls(
            ims_ao_channel=str(raw.get("ims_ao_channel", "Dev1/ao0")),
            ion_ao_channel=str(raw.get("ion_ao_channel", "Dev1/ao1")),
            hv_enable_do_line=str(raw.get("hv_enable_do_line", "Dev1/port0/line0")),
            ims_max_output_kv=float(raw.get("ims_max_output_kv", 20.0)),
            control_voltage_max_v=float(raw.get("control_voltage_max_v", 10.0)),
            ims_setpoint_kv=float(raw.get("ims_setpoint_kv", 10.0)),
            ionization_bias_kv=float(raw.get("ionization_bias_kv", 0.0)),
            save_as_default=bool(raw.get("save_as_default", False)),
        )


class ExperimentData:
    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.iterations: List[np.ndarray] = []
        self.iteration_timestamps: List[str] = []
        self._matrix = np.empty((max(1, self.config.total_iterations), self.config.data_points), dtype=np.float64)

    def reset(self, config: ExperimentConfig | None = None) -> None:
        if config is not None:
            self.config = config
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.iterations.clear()
        self.iteration_timestamps.clear()
        self._matrix = np.empty((max(1, self.config.total_iterations), self.config.data_points), dtype=np.float64)

    def _ensure_capacity(self, required_rows: int) -> None:
        if required_rows <= self._matrix.shape[0]:
            return
        new_rows = max(required_rows, self._matrix.shape[0] * 2)
        new_matrix = np.empty((new_rows, self.config.data_points), dtype=np.float64)
        current_rows = self.iteration_count()
        if current_rows > 0:
            new_matrix[:current_rows, :] = self._matrix[:current_rows, :]
        self._matrix = new_matrix

    def add_iteration(self, y: np.ndarray) -> None:
        y_arr = np.asarray(y, dtype=np.float64)
        if y_arr.shape[0] != self.config.data_points:
            raise ValueError(
                f"Iteration length {y_arr.shape[0]} does not match expected {self.config.data_points}."
            )

        row_index = self.iteration_count()
        self._ensure_capacity(row_index + 1)
        self._matrix[row_index, :] = y_arr
        self.iterations.append(self._matrix[row_index, :])
        self.iteration_timestamps.append(datetime.now().isoformat(timespec="seconds"))

    def get_iteration(self, index: int) -> np.ndarray:
        return self.iterations[index]

    def iteration_count(self) -> int:
        return len(self.iterations)

    def all_iterations_matrix(self) -> np.ndarray:
        count = self.iteration_count()
        if count == 0:
            return np.empty((0, self.config.data_points), dtype=np.float64)
        return self._matrix[:count, :]
