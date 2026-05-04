from __future__ import annotations

from PyQt5.QtCore import QThread, pyqtSignal

from ims_control.data_model.experiment import ExperimentConfig
from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller
from ims_control.processing.aggregator import DataAggregator


class AcquisitionWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, int, int)  # iteration, total_iterations, avg_count, avg_total
    iteration_ready = pyqtSignal(int, object)  # iteration index (1-based), np.ndarray
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, config: ExperimentConfig) -> None:
        super().__init__()
        self.config = config
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        daq = NiUSB6351Controller(
            DaqConfig(
                ai_channel=self.config.ai_channel,
                counter_channel=self.config.counter_channel,
                pfi_trigger=self.config.pfi_trigger,
                pulse_width_ms=self.config.pulse_width_ms,
                experiment_length_ms=self.config.experiment_length_ms,
                data_points=self.config.data_points,
                use_simulation=self.config.use_simulation,
            )
        )
        aggregator = DataAggregator(
            data_points=self.config.data_points,
            averages_per_iteration=self.config.averages_per_iteration,
        )

        try:
            daq.open()
            self.status.emit("Acquisition running")
            for iteration in range(1, self.config.total_iterations + 1):
                if self._stop_requested:
                    break

                aggregator.reset()
                for avg_idx in range(1, self.config.averages_per_iteration + 1):
                    if self._stop_requested:
                        break
                    scan = daq.acquire_scan()
                    aggregator.add_scan(scan)
                    self.progress.emit(
                        iteration,
                        self.config.total_iterations,
                        avg_idx,
                        self.config.averages_per_iteration,
                    )

                if self._stop_requested:
                    break

                averaged = aggregator.finalize_iteration()
                if self.config.positive_mode:
                    averaged = -averaged
                self.iteration_ready.emit(iteration, averaged)

            self.status.emit("Acquisition stopped")
            self.finished_ok.emit()
        except Exception as exc:  # pragma: no cover
            self.failed.emit(str(exc))
        finally:
            daq.close()
