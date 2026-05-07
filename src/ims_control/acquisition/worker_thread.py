"""Qt worker thread that launches the DAQ subprocess and forwards events to the UI."""

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
    """Run one acquisition job in a subprocess and translate JSON events into Qt signals."""
    status = pyqtSignal(str)
    progress = pyqtSignal(int, int, int, int, float, int)  # iteration, total_iterations, avg_count, avg_total, current_frequency_hz (or 0), total_frequencies
    ftims_raw_step = pyqtSignal(float, object)  # frequency_hz, np.ndarray signal
    vsims_sweep_complete = pyqtSignal(dict)  # sweep metadata
    iteration_ready = pyqtSignal(int, object, dict)  # iteration index (1-based), np.ndarray, metadata dict
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, config: ExperimentConfig, user_params: dict | None = None) -> None:
        """Store configuration and initialize worker-local debug state."""
        super().__init__()
        self.config = config
        self.user_params = user_params or {}
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
        """Request cooperative cancellation and terminate the subprocess if needed."""
        self._stop_requested = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        """Build the acquisition payload, stream subprocess events, and emit UI updates."""
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
        elif self.config.operation_mode.value == "SWEPT_FTIMS" and self.config.swept_ftims_config:
            payload.update({
                "swept_ftims_initial_frequency_hz": self.config.swept_ftims_config.initial_frequency_hz,
                "swept_ftims_final_frequency_hz": self.config.swept_ftims_config.final_frequency_hz,
                "swept_ftims_sweep_time_seconds": self.config.swept_ftims_config.sweep_time_seconds,
            })
        elif self.config.operation_mode.value == "STEPPED_VSIMS" and self.config.vsims_config:
            payload.update({
                "vsims_initial_voltage_kv": self.config.vsims_config.initial_voltage_kv,
                "vsims_final_voltage_kv": self.config.vsims_config.final_voltage_kv,
                "vsims_voltage_step_v": self.config.vsims_config.voltage_step_v,
                "vsims_time_add_ms": float(self.user_params.get("time_add_ms", self.config.vsims_config.time_add_ms)),
                "vsims_ionization_bias_kv": float(self.config.vsims_config.ionization_bias_kv),
            })
        elif self.config.operation_mode.value == "SWEPT_VSIMS" and self.config.swept_vsims_config:
            payload.update({
                "swept_vsims_v_add_kv": float(self.config.swept_vsims_config.v_add_kv),
                "swept_vsims_gate_pulse_delay_ms": float(self.config.swept_vsims_config.gate_pulse_delay_ms),
                "swept_vsims_ionization_bias_kv": float(self.config.swept_vsims_config.ionization_bias_kv),
                "swept_vsims_ims_max_output_kv": float(self.config.swept_vsims_config.ims_max_output_kv),
                "swept_vsims_control_voltage_max_v": float(self.config.swept_vsims_config.control_voltage_max_v),
                "gate_v_multiplier": float(self.user_params.get("gate_v_multiplier", 1.0)),
                "temperature_c": float(self.user_params.get("temperature_c", 20.0)),
                "ao_ims_channel": str(self.user_params.get("ims_ao_channel", "")),
                "ao_ion_channel": str(self.user_params.get("ion_ao_channel", "")),
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
                        "vsims_voltage_kv": event.get("vsims_voltage_kv"),
                        "vsims_sweep_iteration": event.get("vsims_sweep_iteration"),
                        "vsims_raw_point": event.get("vsims_raw_point"),
                        "vsims_v_opt_min_kv": event.get("vsims_v_opt_min_kv"),
                        "vsims_v_opt_max_kv": event.get("vsims_v_opt_max_kv"),
                        "vsims_waveform_clipped": event.get("vsims_waveform_clipped"),
                    }
                    
                    self.iteration_ready.emit(iteration, data, metadata)
                elif event_type == "ftims_raw_step":
                    try:
                        freq_hz = float(event.get("frequency_hz", 0.0))
                        signal = np.asarray(event.get("data", []), dtype=np.float64)
                        self.ftims_raw_step.emit(freq_hz, signal)
                    except Exception:
                        pass
                elif event_type == "vsims_sweep_complete":
                    payload = {
                        "sweep_iteration": int(event.get("sweep_iteration", 0)),
                        "raw_spectrum_points": event.get("raw_spectrum_points", {}),
                    }
                    self.vsims_sweep_complete.emit(payload)
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
