from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from ims_control.data_model.experiment import HVPowerConfig
from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller


def _emit(payload: dict) -> None:
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


def _ftims_transform_to_mobility(frequency_domain_data: dict) -> np.ndarray:
    """
    Transform frequency-domain data to mobility-domain using FFT.
    
    Applies FFT independently to each frequency's time-domain signal,
    then averages the resulting mobility-domain spectra across frequencies.
    
    Args:
        frequency_domain_data: Dict mapping frequency (Hz) → time-domain signal at that frequency
        
    Returns:
        FFT-transformed and averaged spectrum as np.ndarray
    """
    # Sort frequencies
    frequencies = sorted(frequency_domain_data.keys())
    
    # Build a stepped-frequency raw spectrum (one scalar per frequency),
    # then FFT that spectrum.
    raw_spectrum = np.asarray([float(np.mean(np.asarray(frequency_domain_data[f]))) for f in frequencies], dtype=np.float64)
    fft_result = np.fft.fft(raw_spectrum)
    result = np.abs(fft_result)
    
    return result


def _load_hv_defaults() -> HVPowerConfig:
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
    max_kv = max(1e-9, float(hv_cfg.ims_max_output_kv))
    ctrl_max_v = max(1e-9, float(hv_cfg.control_voltage_max_v))

    ims_kv = float(np.clip(float(voltage_kv), 0.0, max_kv))
    ion_kv = float(np.clip(ims_kv + float(hv_cfg.ionization_bias_kv), 0.0, max_kv))

    ims_v = (ims_kv / max_kv) * ctrl_max_v
    ion_v = (ion_kv / max_kv) * ctrl_max_v
    return float(ims_v), float(ion_v)


def main(argv: list[str] | None = None) -> int:
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
                mobility_spectrum = _ftims_transform_to_mobility(freq_domain_acc)

                if positive_mode:
                    mobility_spectrum = -mobility_spectrum

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
                    if positive_mode:
                        averaged = -averaged

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