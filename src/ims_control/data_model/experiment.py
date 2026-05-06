from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

import numpy as np


class OperationMode(Enum):
    """Enumeration of IMS operation modes."""
    DTIMS = "DTIMS"  # Drift Time Ion Mobility Spectrometry
    FTIMS = "FTIMS"  # Fourier Transform Ion Mobility Spectrometry


@dataclass
class FTIMSConfig:
    """Configuration for Stepped FTIMS mode."""
    start_frequency_hz: float = 10.0
    frequency_step_hz: float = 5.0
    end_frequency_hz: float = 4000.0
    time_per_frequency_ms: float = 1000.0
    enable_fft: bool = True

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "FTIMSConfig":
        return cls(
            start_frequency_hz=float(raw.get("start_frequency_hz", 10.0)),
            frequency_step_hz=float(raw.get("frequency_step_hz", 5.0)),
            end_frequency_hz=float(raw.get("end_frequency_hz", 4000.0)),
            time_per_frequency_ms=float(raw.get("time_per_frequency_ms", 1000.0)),
            enable_fft=bool(raw.get("enable_fft", True)),
        )

    def frequency_steps(self) -> List[float]:
        """Generate list of frequency steps from start to end."""
        num_steps = int((self.end_frequency_hz - self.start_frequency_hz) / self.frequency_step_hz) + 1
        return [self.start_frequency_hz + i * self.frequency_step_hz for i in range(num_steps)]

    def total_frequencies(self) -> int:
        """Calculate total number of frequency steps."""
        return len(self.frequency_steps())

    def estimated_duration_seconds(self) -> float:
        """Estimate total acquisition duration in seconds."""
        return (self.total_frequencies() * self.time_per_frequency_ms) / 1000.0


@dataclass
class ExperimentConfig:
    operation_mode: OperationMode = OperationMode.DTIMS
    # DTIMS parameters
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
    # FTIMS parameters
    ftims_config: Optional[FTIMSConfig] = field(default_factory=FTIMSConfig)

    def to_dict(self) -> Dict[str, object]:
        config_dict = asdict(self)
        # Convert enum to string for serialization
        config_dict["operation_mode"] = self.operation_mode.value
        if self.ftims_config:
            config_dict["ftims_config"] = self.ftims_config.to_dict()
        return config_dict

    @classmethod
    def from_dict(cls, raw: Dict[str, object]) -> "ExperimentConfig":
        """Reconstruct ExperimentConfig from dict, handling backward compatibility."""
        mode_str = str(raw.get("operation_mode", "DTIMS"))
        try:
            operation_mode = OperationMode(mode_str)
        except ValueError:
            operation_mode = OperationMode.DTIMS

        ftims_config_dict = raw.get("ftims_config")
        ftims_config = FTIMSConfig.from_dict(ftims_config_dict) if ftims_config_dict else FTIMSConfig()

        return cls(
            operation_mode=operation_mode,
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
            ftims_config=ftims_config,
        )


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
    """Stores experiment data for both DTIMS and FTIMS modes."""
    
    def __init__(self, config: ExperimentConfig) -> None:
        self.config = config
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.iterations: List[np.ndarray] = []
        self.iteration_timestamps: List[str] = []
        
        # For FTIMS mode: store frequency-domain data and FFT-transformed mobility data
        self.frequency_domain_iterations: List[Dict[float, np.ndarray]] = []
        self.frequency_bins: List[float] = []
        
        # Matrix dimensions depend on mode
        if config.operation_mode == OperationMode.DTIMS:
            # DTIMS: (iterations, data_points)
            self._matrix = np.empty((max(1, config.total_iterations), config.data_points), dtype=np.float64)
        else:
            # FTIMS: (iterations, data_points for FFT output)
            self._matrix = np.empty((max(1, config.total_iterations), config.data_points), dtype=np.float64)

    def reset(self, config: ExperimentConfig | None = None) -> None:
        if config is not None:
            self.config = config
        self.created_at = datetime.now().isoformat(timespec="seconds")
        self.iterations.clear()
        self.iteration_timestamps.clear()
        self.frequency_domain_iterations.clear()
        self.frequency_bins.clear()
        
        if config.operation_mode == OperationMode.DTIMS:
            self._matrix = np.empty((max(1, config.total_iterations), config.data_points), dtype=np.float64)
        else:
            self._matrix = np.empty((max(1, config.total_iterations), config.data_points), dtype=np.float64)

    def _ensure_capacity(self, required_rows: int) -> None:
        if required_rows <= self._matrix.shape[0]:
            return
        new_rows = max(required_rows, self._matrix.shape[0] * 2)
        new_matrix = np.empty((new_rows, self.config.data_points), dtype=np.float64)
        current_rows = self.iteration_count()
        if current_rows > 0:
            new_matrix[:current_rows, :] = self._matrix[:current_rows, :]
        self._matrix = new_matrix

    def add_iteration(self, y: np.ndarray, frequency_domain_data: Optional[Dict[float, np.ndarray]] = None) -> None:
        """
        Add an iteration to the experiment data.
        
        Args:
            y: The processed spectrum (mobility-domain for FTIMS, time-domain for DTIMS)
            frequency_domain_data: (FTIMS only) Dict mapping frequency → accumulated signal
        """
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
        
        # Store frequency-domain data for FTIMS
        if self.config.operation_mode == OperationMode.FTIMS and frequency_domain_data:
            self.frequency_domain_iterations.append(frequency_domain_data)
            # Update frequency bins on first iteration
            if not self.frequency_bins:
                self.frequency_bins = sorted(frequency_domain_data.keys())

    def get_iteration(self, index: int) -> np.ndarray:
        return self.iterations[index]

    def get_frequency_domain_iteration(self, index: int) -> Optional[Dict[float, np.ndarray]]:
        """Get frequency-domain data for a specific iteration (FTIMS only)."""
        if 0 <= index < len(self.frequency_domain_iterations):
            return self.frequency_domain_iterations[index]
        return None

    def iteration_count(self) -> int:
        return len(self.iterations)

    def all_iterations_matrix(self) -> np.ndarray:
        count = self.iteration_count()
        if count == 0:
            return np.empty((0, self.config.data_points), dtype=np.float64)
        return self._matrix[:count, :]
