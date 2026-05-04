from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

try:
    import nidaqmx
    from nidaqmx.constants import AcquisitionType, Edge
except Exception:  # pragma: no cover
    nidaqmx = None
    AcquisitionType = Edge = None


@dataclass
class DaqConfig:
    ai_channel: str
    counter_channel: str
    pfi_trigger: str
    pulse_width_ms: float
    experiment_length_ms: float
    data_points: int
    use_simulation: bool = False

    @property
    def sample_rate_hz(self) -> float:
        return float(self.data_points) / (self.experiment_length_ms / 1000.0)


class NiUSB6351Controller:
    def __init__(self, config: DaqConfig) -> None:
        self.config = config
        self._rng = np.random.default_rng()
        self._ai_task: Optional[Any] = None
        self._co_task: Optional[Any] = None

    @property
    def available(self) -> bool:
        return nidaqmx is not None and not self.config.use_simulation

    def open(self) -> None:
        if not self.available:
            return
        self._ai_task = nidaqmx.Task()
        self._ai_task.ai_channels.add_ai_voltage_chan(self.config.ai_channel)
        self._ai_task.timing.cfg_samp_clk_timing(
            rate=self.config.sample_rate_hz,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=self.config.data_points,
        )

        self._co_task = nidaqmx.Task()
        self._co_task.co_channels.add_co_pulse_chan_time(
            counter=self.config.counter_channel,
            high_time=max(1e-6, self.config.pulse_width_ms / 1000.0),
            low_time=max(1e-6, (self.config.experiment_length_ms / 1000.0) - (self.config.pulse_width_ms / 1000.0)),
        )
        self._co_task.timing.cfg_implicit_timing(samps_per_chan=1)

    def close(self) -> None:
        if self._ai_task is not None:
            self._ai_task.close()
            self._ai_task = None
        if self._co_task is not None:
            self._co_task.close()
            self._co_task = None

    def acquire_scan(self) -> np.ndarray:
        if not self.available:
            return self._simulate_scan()

        if self._ai_task is None or self._co_task is None:
            self.open()

        assert self._ai_task is not None
        assert self._co_task is not None

        self._co_task.start()
        self._ai_task.start()
        data = self._ai_task.read(number_of_samples_per_channel=self.config.data_points)
        self._ai_task.stop()
        self._co_task.stop()
        y = np.asarray(data, dtype=np.float64)
        return y

    def _simulate_scan(self) -> np.ndarray:
        points = self.config.data_points
        t = np.linspace(0.0, self.config.experiment_length_ms, points)
        center = 0.35 * self.config.experiment_length_ms
        width = 0.07 * self.config.experiment_length_ms
        peak = np.exp(-0.5 * ((t - center) / width) ** 2)
        tail = 0.35 * np.exp(-t / (0.45 * self.config.experiment_length_ms))
        noise = self._rng.normal(0, 0.02, size=points)
        scale = 1.0 + self._rng.normal(0, 0.03)
        return (scale * (peak + tail) + noise).astype(np.float64)
