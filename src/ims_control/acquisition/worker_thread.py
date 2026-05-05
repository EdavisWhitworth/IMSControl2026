from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from ims_control.data_model.experiment import ExperimentConfig


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
        self._proc: subprocess.Popen[str] | None = None

    def request_stop(self) -> None:
        self._stop_requested = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        src_dir = Path(__file__).resolve().parents[2]
        payload = {
            "ai_channel": self.config.ai_channel,
            "counter_channel": self.config.counter_channel,
            "pfi_trigger": self.config.pfi_trigger,
            "pulse_width_ms": self.config.pulse_width_ms,
            "experiment_length_ms": self.config.experiment_length_ms,
            "data_points": self.config.data_points,
            "total_iterations": self.config.total_iterations,
            "averages_per_iteration": self.config.averages_per_iteration,
            "positive_mode": self.config.positive_mode,
            "use_simulation": self.config.use_simulation,
        }

        cmd = [
            sys.executable,
            "-m",
            "ims_control.acquisition.daq_cli",
            "--payload",
            json.dumps(payload, separators=(",", ":")),
        ]

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(src_dir.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            assert self._proc.stdout is not None
            for raw_line in self._proc.stdout:
                if self._stop_requested:
                    break

                line = raw_line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")
                if event_type == "status":
                    self.status.emit(str(event.get("message", "")))
                elif event_type == "progress":
                    self.progress.emit(
                        int(event.get("iteration", 0)),
                        int(event.get("total_iterations", 0)),
                        int(event.get("avg_count", 0)),
                        int(event.get("avg_total", 0)),
                    )
                elif event_type == "iteration":
                    iteration = int(event.get("iteration", 0))
                    data = np.asarray(event.get("data", []), dtype=np.float64)
                    self.iteration_ready.emit(iteration, data)
                elif event_type == "finished":
                    self.finished_ok.emit()
                    return
                elif event_type == "failed":
                    self.failed.emit(str(event.get("error", "Unknown acquisition error")))
                    return

            if self._stop_requested:
                self.status.emit("Acquisition stopped")
                self.finished_ok.emit()
                return

            if self._proc is not None:
                exit_code = self._proc.wait(timeout=2)
                if exit_code != 0:
                    stderr_text = ""
                    if self._proc.stderr is not None:
                        stderr_text = self._proc.stderr.read().strip()
                    self.failed.emit(stderr_text or f"Acquisition subprocess exited with code {exit_code}")
                else:
                    self.finished_ok.emit()
        except Exception as exc:  # pragma: no cover
            self.failed.emit(f"Unexpected error: {type(exc).__name__}: {exc}")
        finally:
            if self._proc is not None:
                try:
                    if self._proc.poll() is None:
                        self._proc.terminate()
                        self._proc.wait(timeout=2)
                except Exception:
                    pass
                self._proc = None
