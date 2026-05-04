from __future__ import annotations

import numpy as np


class DataAggregator:
    def __init__(self, data_points: int, averages_per_iteration: int) -> None:
        self.data_points = data_points
        self.averages_per_iteration = max(1, averages_per_iteration)
        self._sum = np.zeros(self.data_points, dtype=np.float64)
        self._count = 0

    def reset(self) -> None:
        self._sum.fill(0.0)
        self._count = 0

    def add_scan(self, scan: np.ndarray) -> bool:
        y = np.asarray(scan, dtype=np.float64)
        if y.shape[0] != self.data_points:
            raise ValueError(
                f"Scan length {y.shape[0]} does not match expected {self.data_points}."
            )
        self._sum += y
        self._count += 1
        return self._count >= self.averages_per_iteration

    def progress(self) -> int:
        return self._count

    def finalize_iteration(self) -> np.ndarray:
        if self._count == 0:
            return np.zeros(self.data_points, dtype=np.float64)
        avg = self._sum / self._count
        self.reset()
        return avg
