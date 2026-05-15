"""Subprocess entrypoint for data acquisition across all IMS operation modes."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

from ims_control.data_model.experiment import HVPowerConfig
from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller


def _emit(payload: dict) -> None:
    """Write one JSON event to stdout for the worker thread."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _extract_peak_metrics(spectrum: np.ndarray) -> dict:
    """
    Extract peak metrics from a spectrum for display.
    
    Returns:
        Dictionary with peak_height, fwhm, and other useful metrics
    """
    try:
        peak_idx = np.argmax(spectrum)
        peak_height = float(spectrum[peak_idx])
        
        # Estimate FWHM (Full Width Half Max)
        half_max = peak_height / 2.0
        above_half = np.where(spectrum >= half_max)[0]
        if len(above_half) > 1:
            fwhm = float(above_half[-1] - above_half[0])
        else:
            fwhm = 1.0
        
        # Calculate SNR: peak height / RMS noise (estimate from low-signal regions)
        noise_estimate = float(np.sqrt(np.mean(spectrum[:10] ** 2)))
        snr = peak_height / (noise_estimate + 1e-6)
        
        return {
            "peak_height": peak_height,
            "fwhm": fwhm,
            "snr": snr,
            "peak_index": int(peak_idx),
        }
    except Exception:
        return {
            "peak_height": 0.0,
            "fwhm": 0.0,
            "snr": 0.0,
            "peak_index": 0,
        }


def _ftims_transform_to_mobility(
    frequency_domain_data: dict,
    start_frequency_hz: float,
    frequency_step_hz: float,
    averages_per_iteration: int,
    experiment_length_ms: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Transform stepped-FTIMS raw spectrum to mobility-domain amplitude.

    Returns:
        Tuple of (FFT amplitude spectrum, ATD-time axis in ms)
    """
    frequencies = sorted(frequency_domain_data.keys())
    raw_spectrum = np.asarray([float(np.mean(np.asarray(frequency_domain_data[f]))) for f in frequencies], dtype=np.float64)
    n_pts = int(raw_spectrum.size)
    if n_pts <= 0:
        return np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)

    start_hz = max(1e-9, float(start_frequency_hz))
    step_hz = max(1e-9, float(frequency_step_hz))
    avg_count = max(1, int(averages_per_iteration))

    # Match IMSDataAnalysis FTIMS ATD mapping: dwell is experiment length +
    # averages/start-frequency contribution per stepped frequency point.
    dwell_seconds = max(0.0, float(experiment_length_ms) / 1000.0) + (avg_count / start_hz)
    if dwell_seconds <= 0.0:
        dwell_seconds = avg_count / start_hz
    sweep_rate_hz_per_s = step_hz / dwell_seconds

    norm_fac = 2.0 / float(n_pts)
    n_half = max(1, int(n_pts / 2))
    axis_fft_input_count = max(2, int(n_half * 2))
    yf = np.fft.fft(raw_spectrum)
    amplitude = (np.abs(yf[:n_half]) * norm_fac) ** 2
    # Keep axis generation consistent with IMSDataAnalysis, which derives the
    # FFT input point count from the displayed positive-frequency bins.
    xf = np.fft.fftfreq(axis_fft_input_count, d=dwell_seconds)
    freq_axis = xf[:n_half]
    atd_time_ms = (freq_axis / max(1e-9, sweep_rate_hz_per_s)) * 1000.0

    return amplitude, atd_time_ms


def _load_hv_defaults() -> HVPowerConfig:
    """Load persisted HV defaults, falling back to built-in defaults on error."""
    path = Path.home() / ".ims_control_hv_defaults.json"
    if not path.exists():
        return HVPowerConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return HVPowerConfig()
        return HVPowerConfig.from_dict(raw)
    except Exception:
        return HVPowerConfig()


def _vsims_to_control_voltages(voltage_kv: float, hv_cfg: HVPowerConfig) -> tuple[float, float]:
    """Convert requested VSIMS setpoints in kV into AO control voltages."""
    max_kv = max(1e-9, float(hv_cfg.ims_max_output_kv))
    ctrl_max_v = max(1e-9, float(hv_cfg.control_voltage_max_v))

    ims_kv = float(np.clip(float(voltage_kv), 0.0, max_kv))
    ion_kv = float(np.clip(ims_kv + float(hv_cfg.ionization_bias_kv), 0.0, max_kv))

    ims_v = (ims_kv / max_kv) * ctrl_max_v
    ion_v = (ion_kv / max_kv) * ctrl_max_v
    return float(ims_v), float(ion_v)


def _build_swept_vsims_waveforms(payload: dict) -> dict[str, object]:
    """Generate buffered IMS and ionization AO waveforms for Swept VSIMS mode."""
    data_points = max(1, int(payload.get("data_points", 4000)))
    experiment_length_s = max(1e-9, float(payload.get("experiment_length_ms", 50.0)) / 1000.0)
    pulse_width_s = max(1e-9, float(payload.get("pulse_width_ms", 0.2)) / 1000.0)
    temperature_k = max(1e-9, float(payload.get("temperature_c", 20.0)) + 273.15)
    v_add_kv = float(payload.get("swept_vsims_v_add_kv", 0.0))
    v_add_v = v_add_kv * 1000.0
    gate_v_multiplier = max(1e-9, float(payload.get("gate_v_multiplier", 1.0)))
    ionization_bias_kv = float(payload.get("swept_vsims_ionization_bias_kv", 0.0))
    ims_max_output_kv = max(1e-9, float(payload.get("swept_vsims_ims_max_output_kv", 20.0)))
    control_voltage_max_v = max(1e-9, float(payload.get("swept_vsims_control_voltage_max_v", 10.0)))
    sign = 1.0 if bool(payload.get("positive_mode", False)) else -1.0

    drift_times_s = np.linspace(0.0, experiment_length_s, data_points, endpoint=False, dtype=np.float64)
    v_opt_unclipped_v = (
        ((drift_times_s * (760.0 / 273.15) * ((0.0395 * temperature_k) / pulse_width_s)) ** 2) * (0.0395 / temperature_k)
        + v_add_v
    ) / gate_v_multiplier
    v_opt_unclipped_kv = v_opt_unclipped_v / 1000.0
    ims_kv = np.clip(v_opt_unclipped_kv, 0.0, ims_max_output_kv)
    ion_unclipped_kv = ims_kv + ionization_bias_kv
    ion_kv = np.clip(ion_unclipped_kv, 0.0, ims_max_output_kv)

    resting_ims_kv = float(np.clip(v_add_kv / gate_v_multiplier, 0.0, ims_max_output_kv))
    resting_ion_kv = float(np.clip(resting_ims_kv + ionization_bias_kv, 0.0, ims_max_output_kv))

    ims_waveform_v = ((ims_kv / ims_max_output_kv) * control_voltage_max_v) * sign
    ion_waveform_v = ((ion_kv / ims_max_output_kv) * control_voltage_max_v) * sign
    resting_ims_v = ((resting_ims_kv / ims_max_output_kv) * control_voltage_max_v) * sign
    resting_ion_v = ((resting_ion_kv / ims_max_output_kv) * control_voltage_max_v) * sign

    clipped = bool(
        np.any(v_opt_unclipped_kv < 0.0)
        or np.any(v_opt_unclipped_kv > ims_max_output_kv)
        or np.any(ion_unclipped_kv < 0.0)
        or np.any(ion_unclipped_kv > ims_max_output_kv)
    )

    return {
        "drift_times_s": drift_times_s,
        "v_opt_unclipped_v": v_opt_unclipped_v,
        "v_opt_unclipped_kv": v_opt_unclipped_kv,
        "ims_kv": ims_kv,
        "ion_kv": ion_kv,
        "ims_waveform_v": ims_waveform_v,
        "ion_waveform_v": ion_waveform_v,
        "resting_ims_kv": resting_ims_kv,
        "resting_ion_kv": resting_ion_kv,
        "resting_ims_v": float(resting_ims_v),
        "resting_ion_v": float(resting_ion_v),
        "v_opt_range_kv": (float(np.min(ims_kv)), float(np.max(ims_kv))),
        "clipped": clipped,
    }


def main(argv: list[str] | None = None) -> int:
    """Execute one acquisition request and emit progress/results as JSON events."""
    parser = argparse.ArgumentParser(description="DAQ acquisition subprocess")
    parser.add_argument("--payload", required=True, help="JSON-encoded acquisition payload")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.payload)
    except Exception as exc:
        _emit({"type": "failed", "error": f"Invalid payload: {exc}"})
        return 2

    cfg = DaqConfig(
        ai_channel=payload["ai_channel"],
        counter_channel=payload["counter_channel"],
        pfi_trigger=payload["pfi_trigger"],
        pulse_width_ms=float(payload["pulse_width_ms"]),
        experiment_length_ms=float(payload["experiment_length_ms"]),
        data_points=int(payload["data_points"]),
        use_simulation=bool(payload.get("use_simulation", False)),
    )

    operation_mode = str(payload.get("operation_mode", "DTIMS"))
    total_iterations = int(payload["total_iterations"])
    averages_per_iteration = int(payload["averages_per_iteration"])
    positive_mode = bool(payload.get("positive_mode", False))

    daq = NiUSB6351Controller(cfg)
    try:
        daq.open()
        _emit({"type": "status", "message": "Acquisition running"})

        if operation_mode == "FTIMS":
            # FTIMS acquisition with FFT
            start_freq = float(payload.get("ftims_start_frequency_hz", 10.0))
            freq_step = float(payload.get("ftims_frequency_step_hz", 5.0))
            end_freq = float(payload.get("ftims_end_frequency_hz", 4000.0))
            time_per_freq = (float(averages_per_iteration) / max(1e-9, start_freq)) * 1000.0
            
            # Generate frequency list for display
            frequencies = []
            f = start_freq
            while f <= end_freq + 1e-6:
                frequencies.append(f)
                f += freq_step
            total_frequencies = len(frequencies)

            for iteration in range(1, total_iterations + 1):
                freq_domain_acc: dict | None = None
                raw_spectrum_points: dict[float, float] = {}

                for freq in frequencies:
                    point_sum = 0.0
                    for avg_idx in range(1, averages_per_iteration + 1):
                        step_signal = daq.acquire_ftims_frequency_step(
                            frequency_hz=freq,
                            time_per_frequency_ms=time_per_freq,
                        )

                        step_signal_arr = np.asarray(step_signal, dtype=np.float64)
                        point_sum += float(np.mean(step_signal_arr))
                        running_avg_point = point_sum / float(avg_idx)

                        _emit(
                            {
                                "type": "ftims_raw_step",
                                "iteration": iteration,
                                "frequency_hz": freq,
                                "avg_count": avg_idx,
                                "avg_total": averages_per_iteration,
                                "data": [running_avg_point],
                                "point_value": running_avg_point,
                            }
                        )

                        if freq_domain_acc is None:
                            freq_domain_acc = {f: np.zeros_like(step_signal_arr, dtype=np.float64) for f in frequencies}

                        freq_domain_acc[freq] += step_signal_arr

                        _emit(
                            {
                                "type": "progress",
                                "iteration": iteration,
                                "total_iterations": total_iterations,
                                "avg_count": avg_idx,
                                "avg_total": averages_per_iteration,
                                "current_frequency_hz": freq,
                                "total_frequencies": total_frequencies,
                            }
                        )

                    raw_spectrum_points[freq] = point_sum / float(averages_per_iteration)

                if freq_domain_acc is None:
                    continue

                # Average the accumulated frequency-domain data
                for freq in freq_domain_acc:
                    freq_domain_acc[freq] /= float(averages_per_iteration)

                # Transform to mobility domain using FFT
                mobility_spectrum, atd_time_ms = _ftims_transform_to_mobility(
                    freq_domain_acc,
                    start_frequency_hz=start_freq,
                    frequency_step_hz=freq_step,
                    averages_per_iteration=averages_per_iteration,
                    experiment_length_ms=float(cfg.experiment_length_ms),
                )

                # Extract peak metrics for display
                peak_metrics = _extract_peak_metrics(mobility_spectrum)

                _emit(
                    {
                        "type": "iteration",
                        "iteration": iteration,
                        "data": mobility_spectrum.tolist(),
                        "raw_spectrum_points": {
                            str(f): float(raw_spectrum_points[f]) for f in sorted(raw_spectrum_points.keys())
                        },
                        "frequency_domain_data": {
                            str(f): sig.tolist() for f, sig in freq_domain_acc.items()
                        },
                        "ftims_atd_time_ms": atd_time_ms.tolist(),
                        "peak_metrics": peak_metrics,
                    }
                )

        elif operation_mode == "SWEPT_FTIMS":
            initial_freq = float(payload.get("swept_ftims_initial_frequency_hz", 1.0))
            final_freq = float(payload.get("swept_ftims_final_frequency_hz", 8000.0))
            sweep_time_s = max(1e-3, float(payload.get("swept_ftims_sweep_time_seconds", 4.0)))
            estimated_pulses = int(np.clip(round(0.5 * (initial_freq + final_freq) * sweep_time_s), 2, 100_000))

            for iteration in range(1, total_iterations + 1):
                acc: np.ndarray | None = None
                _emit(
                    {
                        "type": "status",
                        "message": (
                            f"Swept FTIMS iteration {iteration}/{total_iterations}: "
                            f"buffered gate sweep {initial_freq:.1f}->{final_freq:.1f} Hz, "
                            f"{sweep_time_s:.3f} s, ~{estimated_pulses} pulses"
                        ),
                    }
                )

                for avg_idx in range(1, averages_per_iteration + 1):
                    sweep_signal = daq.acquire_ftims_swept_scan(
                        initial_frequency_hz=initial_freq,
                        final_frequency_hz=final_freq,
                        sweep_time_seconds=sweep_time_s,
                    )
                    sweep_arr = np.asarray(sweep_signal, dtype=np.float64)
                    if acc is None:
                        acc = sweep_arr
                    else:
                        acc += sweep_arr

                    _emit(
                        {
                            "type": "progress",
                            "iteration": iteration,
                            "total_iterations": total_iterations,
                            "avg_count": avg_idx,
                            "avg_total": averages_per_iteration,
                            "current_frequency_hz": initial_freq,
                            "total_frequencies": 1,
                        }
                    )

                if acc is None:
                    continue

                averaged_td = acc / float(averages_per_iteration)
                fft_mag_native = np.abs(np.fft.rfft(averaged_td))
                sample_rate_hz = max(1e-9, float(cfg.data_points) / sweep_time_s)
                fft_freq_native = np.fft.rfftfreq(cfg.data_points, d=1.0 / sample_rate_hz)

                target_points = max(1, int(cfg.data_points))
                if fft_mag_native.shape[0] != target_points:
                    native_x = np.linspace(0.0, 1.0, fft_mag_native.shape[0], endpoint=True)
                    target_x = np.linspace(0.0, 1.0, target_points, endpoint=True)
                    fft_mag = np.interp(target_x, native_x, fft_mag_native)
                    fft_freq = np.interp(target_x, native_x, fft_freq_native)
                else:
                    fft_mag = fft_mag_native
                    fft_freq = fft_freq_native

                if positive_mode:
                    fft_mag = -fft_mag

                peak_metrics = _extract_peak_metrics(np.abs(fft_mag))

                _emit(
                    {
                        "type": "iteration",
                        "iteration": iteration,
                        "data": fft_mag.tolist(),
                        "raw_time_domain_sweep": averaged_td.tolist(),
                        "fft_frequency_bins_hz": fft_freq.tolist(),
                        "fft_spectrum": fft_mag.tolist(),
                        "peak_metrics": peak_metrics,
                    }
                )

        elif operation_mode == "STEPPED_VSIMS":
            initial_voltage_kv = float(payload.get("vsims_initial_voltage_kv", 4.0))
            final_voltage_kv = float(payload.get("vsims_final_voltage_kv", 8.0))
            voltage_step_v = float(payload.get("vsims_voltage_step_v", 100.0))
            hv_cfg = _load_hv_defaults()
            if "vsims_ionization_bias_kv" in payload:
                hv_cfg.ionization_bias_kv = float(payload.get("vsims_ionization_bias_kv", hv_cfg.ionization_bias_kv))
            ao_enabled = daq.available

            voltage_step_kv = voltage_step_v / 1000.0
            if voltage_step_kv <= 0.0:
                raise ValueError("VSIMS voltage step must be > 0 V")
            voltages_kv: list[float] = []
            v = initial_voltage_kv
            while v <= final_voltage_kv + 1e-9:
                voltages_kv.append(v)
                v += voltage_step_kv
            if not voltages_kv:
                raise ValueError("VSIMS voltage configuration produced no sweep points")
            total_voltages = len(voltages_kv)
            total_points = total_iterations * total_voltages

            point_counter = 0
            for sweep_iteration in range(1, total_iterations + 1):
                raw_spectrum_points: dict[float, float] = {}
                for voltage_kv in voltages_kv:
                    point_counter += 1
                    acc: np.ndarray | None = None

                    if ao_enabled:
                        ims_v, ion_v = _vsims_to_control_voltages(voltage_kv, hv_cfg)
                        daq.write_dual_analog_output(
                            hv_cfg.ims_ao_channel,
                            hv_cfg.ion_ao_channel,
                            ims_v,
                            ion_v,
                        )

                    for avg_idx in range(1, averages_per_iteration + 1):
                        scan = daq.acquire_vsims_voltage_step(voltage_kv=voltage_kv)
                        scan_arr = np.asarray(scan, dtype=np.float64)
                        if acc is None:
                            acc = scan_arr
                        else:
                            acc += scan_arr

                        _emit(
                            {
                                "type": "progress",
                                "iteration": point_counter,
                                "total_iterations": total_points,
                                "avg_count": avg_idx,
                                "avg_total": averages_per_iteration,
                                "current_frequency_hz": voltage_kv,
                                "total_frequencies": total_voltages,
                            }
                        )

                    if acc is None:
                        continue

                    averaged = acc / float(averages_per_iteration)

                    raw_point = float(np.mean(averaged))
                    raw_spectrum_points[voltage_kv] = raw_point

                    _emit(
                        {
                            "type": "iteration",
                            "iteration": point_counter,
                            "data": averaged.tolist(),
                            "vsims_voltage_kv": voltage_kv,
                            "vsims_sweep_iteration": sweep_iteration,
                            "vsims_raw_point": raw_point,
                        }
                    )

                _emit(
                    {
                        "type": "vsims_sweep_complete",
                        "sweep_iteration": sweep_iteration,
                        "raw_spectrum_points": {
                            str(k): float(v) for k, v in raw_spectrum_points.items()
                        },
                    }
                )

        elif operation_mode == "SWEPT_VSIMS":
            hv_cfg = _load_hv_defaults()
            ao_ims_channel = str(payload.get("ao_ims_channel", "") or hv_cfg.ims_ao_channel)
            ao_ion_channel = str(payload.get("ao_ion_channel", "") or hv_cfg.ion_ao_channel)
            gate_pulse_delay_ms = max(0.0, float(payload.get("swept_vsims_gate_pulse_delay_ms", 0.0)))
            waveforms = _build_swept_vsims_waveforms(payload)
            ims_waveform_v = np.asarray(waveforms["ims_waveform_v"], dtype=np.float64)
            ion_waveform_v = np.asarray(waveforms["ion_waveform_v"], dtype=np.float64)
            v_opt_min_kv, v_opt_max_kv = waveforms["v_opt_range_kv"]
            clipped = bool(waveforms["clipped"])
            initial_ims_v = float(waveforms["resting_ims_v"])
            initial_ion_v = float(waveforms["resting_ion_v"])

            # Ensure AO resets to initial values at the end of the 50 ms sweep.
            # The final sample is held by hardware between scans, so this keeps
            # outputs at initial values throughout the gate-delay interval.
            if ims_waveform_v.size > 0:
                ims_waveform_v[-1] = initial_ims_v
            if ion_waveform_v.size > 0:
                ion_waveform_v[-1] = initial_ion_v
            
            # Timing diagnostics
            experiment_length_ms = float(payload.get("experiment_length_ms", 50.0))
            data_points = len(ims_waveform_v)
            sample_rate_hz = data_points / (experiment_length_ms / 1000.0)
            waveform_duration_ms = (data_points / sample_rate_hz) * 1000.0
            
            timing_msg = (
                f"Swept VSIMS timing: {data_points} samples at {sample_rate_hz:.1f} Hz = "
                f"{waveform_duration_ms:.3f} ms waveform duration "
                f"(configured: {experiment_length_ms:.1f} ms), gate delay {gate_pulse_delay_ms:.1f} ms"
            )
            
            # Print to stderr for console visibility
            print(f"\n{'='*80}", file=sys.stderr)
            print(f"TIMING DIAGNOSTICS: {timing_msg}", file=sys.stderr)
            print(f"{'='*80}\n", file=sys.stderr)
            
            # Emit status message for GUI
            _emit({
                "type": "status",
                "message": timing_msg,
            })
            
            # Write timing diagnostics to persistent file
            try:
                timing_file = Path.cwd() / "swept_vsims_timing_diagnostics.txt"
                with timing_file.open("w", encoding="utf-8") as fh:
                    fh.write("Swept VSIMS Timing Diagnostics\n")
                    fh.write("=" * 80 + "\n\n")
                    fh.write(f"Data points: {data_points}\n")
                    fh.write(f"Sample rate: {sample_rate_hz:.1f} Hz\n")
                    fh.write(f"Waveform duration (calculated): {waveform_duration_ms:.3f} ms\n")
                    fh.write(f"Configured duration: {experiment_length_ms:.1f} ms\n")
                    fh.write(f"Gate pulse delay: {gate_pulse_delay_ms:.1f} ms\n")
                    fh.write(f"\nNote: If your external hardware observes >50 ms actual duration,\n")
                    fh.write(f"the difference is hardware overhead/synchronization time.\n")
                _emit({
                    "type": "status",
                    "message": f"Timing diagnostics saved to {timing_file.resolve()}",
                })
            except Exception as e:
                print(f"Failed to write timing diagnostics file: {e}", file=sys.stderr)
            
            # Export buffered AO waveforms to CSV for debugging
            try:
                csv_path = Path.cwd() / "swept_vsims_buffered_ao.csv"
                drift_times_s = np.asarray(waveforms["drift_times_s"], dtype=np.float64)
                experiment_length_s = max(1e-9, float(payload.get("experiment_length_ms", 50.0)) / 1000.0)
                data_points_csv = len(drift_times_s)
                sample_rate_hz_csv = data_points_csv / experiment_length_s
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow([
                        "index",
                        "time_s",
                        "time_ms",
                        "sample_rate_hz",
                        "ims_ao_v",
                        "ion_ao_v",
                        "resting_ims_v",
                        "resting_ion_v",
                    ])
                    for idx, t_s in enumerate(drift_times_s):
                        writer.writerow([
                            idx,
                            f"{float(t_s):.12f}",
                            f"{float(t_s) * 1000.0:.9f}",
                            f"{sample_rate_hz_csv:.6f}",
                            f"{float(ims_waveform_v[idx]):.12f}",
                            f"{float(ion_waveform_v[idx]):.12f}",
                            f"{initial_ims_v:.12f}",
                            f"{initial_ion_v:.12f}",
                        ])
                _emit({
                    "type": "status",
                    "message": f"Exported buffered AO waveforms to {csv_path.resolve()}",
                })
            except Exception as e:
                _emit({
                    "type": "status",
                    "message": f"CSV export warning: {e}",
                })

            try:
                for iteration in range(1, total_iterations + 1):
                    acc: np.ndarray | None = None
                    _emit(
                        {
                            "type": "status",
                            "message": (
                                f"Swept VSIMS iteration {iteration}/{total_iterations}: "
                                f"Vopt {v_opt_min_kv:.3f}->{v_opt_max_kv:.3f} kV"
                                + (" (clipped)" if clipped else "")
                            ),
                        }
                    )

                    for avg_idx in range(1, averages_per_iteration + 1):
                        scan = daq.acquire_swept_vsims_scan(
                            ims_ao_channel=ao_ims_channel,
                            ion_ao_channel=ao_ion_channel,
                            ims_waveform_v=ims_waveform_v,
                            ion_waveform_v=ion_waveform_v,
                            gate_pulse_delay_ms=gate_pulse_delay_ms,
                            initial_ims_v=initial_ims_v,
                            initial_ion_v=initial_ion_v,
                            restore_after_scan=False,
                        )
                        scan_arr = np.asarray(scan, dtype=np.float64)
                        if acc is None:
                            acc = scan_arr
                        else:
                            acc += scan_arr

                        _emit(
                            {
                                "type": "progress",
                                "iteration": iteration,
                                "total_iterations": total_iterations,
                                "avg_count": avg_idx,
                                "avg_total": averages_per_iteration,
                                "current_frequency_hz": 0.0,
                                "total_frequencies": 0,
                            }
                        )

                    if acc is None:
                        continue

                    averaged = acc / float(averages_per_iteration)
                    if positive_mode:
                        averaged = -averaged

                    _emit(
                        {
                            "type": "iteration",
                            "iteration": iteration,
                            "data": averaged.tolist(),
                            "vsims_v_opt_min_kv": v_opt_min_kv,
                            "vsims_v_opt_max_kv": v_opt_max_kv,
                            "vsims_waveform_clipped": clipped,
                        }
                    )
            finally:
                try:
                    # Release cached buffered tasks first so AO channels are free
                    # for the explicit reset-to-initial write.
                    daq.cleanup_swept_vsims_tasks()
                    daq.write_dual_analog_output(
                        ao_ims_channel,
                        ao_ion_channel,
                        float(initial_ims_v),
                        float(initial_ion_v),
                    )
                    if gate_pulse_delay_ms > 0.0:
                        time.sleep(max(0.0, gate_pulse_delay_ms / 1000.0))
                except Exception:
                    pass

        else:
            # DTIMS acquisition (existing logic)
            for iteration in range(1, total_iterations + 1):
                acc: np.ndarray | None = None

                for avg_idx in range(1, averages_per_iteration + 1):
                    scan = daq.acquire_scan()
                    if acc is None:
                        acc = np.asarray(scan, dtype=np.float64)
                    else:
                        acc += np.asarray(scan, dtype=np.float64)

                    _emit(
                        {
                            "type": "progress",
                            "iteration": iteration,
                            "total_iterations": total_iterations,
                            "avg_count": avg_idx,
                            "avg_total": averages_per_iteration,
                        }
                    )

                if acc is None:
                    continue

                averaged = acc / float(averages_per_iteration)
                if positive_mode:
                    averaged = -averaged

                _emit(
                    {
                        "type": "iteration",
                        "iteration": iteration,
                        "data": averaged.tolist(),
                    }
                )

        _emit({"type": "status", "message": "Acquisition stopped"})
        _emit({"type": "finished"})
        return 0
    except Exception as exc:
        _emit({"type": "failed", "error": str(exc)})
        return 1
    finally:
        daq.close()


if __name__ == "__main__":
    raise SystemExit(main())