from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from ims_control.data_model.experiment import ExperimentConfig


class AcquisitionWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, int, int, float, int)  # iteration, total_iterations, avg_count, avg_total, current_frequency_hz (or 0), total_frequencies
    ftims_raw_step = pyqtSignal(float, object)  # frequency_hz, np.ndarray signal
    iteration_ready = pyqtSignal(int, object, dict)  # iteration index (1-based), np.ndarray, metadata dict
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, config: ExperimentConfig) -> None:
        super().__init__()
        self.config = config
        self._stop_requested = False
        self._proc: subprocess.Popen[str] | None = None
        self._debug_log_path = Path.home() / "ims_ftims_debug.log"
        self._debug_events_written = 0

    def _debug_log(self, message: str) -> None:
        """Append a short worker diagnostic line (best-effort)."""
        try:
            ts = datetime.now().isoformat(timespec="seconds")
            self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._debug_log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"{ts} {message}\n")
        except Exception:
            pass

    def request_stop(self) -> None:
        self._stop_requested = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        src_dir = Path(__file__).resolve().parents[2]
        self._debug_events_written = 0
        self._debug_log(
            f"worker_start mode={getattr(self.config.operation_mode, 'value', self.config.operation_mode)} "
            f"python={sys.executable} src_dir={src_dir}"
        )
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
            "operation_mode": self.config.operation_mode.value,
        }

        # Add FTIMS-specific parameters if in FTIMS mode
        if self.config.operation_mode.value == "FTIMS" and self.config.ftims_config:
            payload.update({
                "ftims_start_frequency_hz": self.config.ftims_config.start_frequency_hz,
                "ftims_frequency_step_hz": self.config.ftims_config.frequency_step_hz,
                "ftims_end_frequency_hz": self.config.ftims_config.end_frequency_hz,
            })

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
                    if self._debug_events_written < 120:
                        self._debug_log(
                            "progress "
                            f"iter={event.get('iteration')} avg={event.get('avg_count')}/{event.get('avg_total')} "
                            f"freq={event.get('current_frequency_hz')} total_freq={event.get('total_frequencies')}"
                        )
                        self._debug_events_written += 1
                    self.progress.emit(
                        int(event.get("iteration", 0)),
                        int(event.get("total_iterations", 0)),
                        int(event.get("avg_count", 0)),
                        int(event.get("avg_total", 0)),
                        float(event.get("current_frequency_hz", 0.0)),
                        int(event.get("total_frequencies", 0)),
                    )
                elif event_type == "iteration":
                    iteration = int(event.get("iteration", 0))
                    data = np.asarray(event.get("data", []), dtype=np.float64)
                    raw_td = event.get("raw_time_domain_data", {})
                    freq_dom = event.get("frequency_domain_data", {})
                    if self._debug_events_written < 160:
                        self._debug_log(
                            "iteration "
                            f"iter={iteration} data_len={data.shape[0]} "
                            f"raw_keys={len(raw_td) if isinstance(raw_td, dict) else -1} "
                            f"freq_keys={len(freq_dom) if isinstance(freq_dom, dict) else -1}"
                        )
                        self._debug_events_written += 1
                    
                    # Extract FTIMS-specific metadata if available
                    metadata = {
                        "raw_time_domain_data": event.get("raw_time_domain_data", {}),
                        "raw_spectrum_points": event.get("raw_spectrum_points", {}),
                        "frequency_domain_data": event.get("frequency_domain_data", {}),
                        "peak_metrics": event.get("peak_metrics", {}),
                    }
                    
                    self.iteration_ready.emit(iteration, data, metadata)
                elif event_type == "ftims_raw_step":
                    try:
                        freq_hz = float(event.get("frequency_hz", 0.0))
                        signal = np.asarray(event.get("data", []), dtype=np.float64)
                        self.ftims_raw_step.emit(freq_hz, signal)
                    except Exception:
                        pass
                elif event_type == "finished":
                    self._debug_log("worker_finished")
                    self.finished_ok.emit()
                    return
                elif event_type == "failed":
                    self._debug_log(f"worker_failed error={event.get('error', 'unknown')}")
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
                    self._debug_log("worker_finished_exit_code_0")
                    self.finished_ok.emit()
        except Exception as exc:  # pragma: no cover
            self._debug_log(f"worker_exception {type(exc).__name__}: {exc}")
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
