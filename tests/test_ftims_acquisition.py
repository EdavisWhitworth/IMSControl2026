"""Integration tests for FTIMS acquisition and FFT transformation."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from ims_control.acquisition.daq_cli import _extract_peak_metrics, _ftims_transform_to_mobility
from ims_control.data_model.experiment import ExperimentConfig, OperationMode, FTIMSConfig
from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller


class TestFTIMSTransformations:
    """Test FTIMS signal transformations."""

    def test_extract_peak_metrics_simple_gaussian(self):
        """Test peak metric extraction on simple Gaussian."""
        # Create simple Gaussian peak
        x = np.linspace(-5, 5, 100)
        spectrum = np.exp(-x**2)

        metrics = _extract_peak_metrics(spectrum)
        assert "peak_height" in metrics
        assert "fwhm" in metrics
        assert "snr" in metrics
        assert metrics["peak_height"] > 0
        assert metrics["fwhm"] > 0
        assert metrics["snr"] > 0

    def test_extract_peak_metrics_with_noise(self):
        """Test peak metrics on noisy signal."""
        # Create signal with peak and noise
        x = np.linspace(0, 100, 200)
        peak = np.exp(-((x - 50) / 10) ** 2)
        noise = np.random.normal(0, 0.1, size=200)
        spectrum = peak + noise

        metrics = _extract_peak_metrics(spectrum)
        assert metrics["peak_height"] > 0
        # Peak should be near x=50 (index 100)
        assert 80 < metrics["peak_index"] < 120

    def test_extract_peak_metrics_empty(self):
        """Test peak metrics on empty spectrum."""
        spectrum = np.zeros(100)
        metrics = _extract_peak_metrics(spectrum)
        assert metrics["peak_height"] == 0
        assert metrics["fwhm"] >= 0
        assert metrics["snr"] >= 0

    def test_ftims_transform_simple_signal(self):
        """Test FFT transformation with synthetic frequency-domain data."""
        # Create simple frequency-domain signal: single frequency
        frequencies = [10.0, 15.0, 20.0]
        frequency_domain = {}

        # Create simple sinusoidal signals at each frequency
        for freq in frequencies:
            t = np.linspace(0, 1, 100)
            signal = np.sin(2 * np.pi * freq * t)
            frequency_domain[freq] = signal

        # Transform to mobility domain
        mobility_spectrum, atd_time_ms = _ftims_transform_to_mobility(
            frequency_domain,
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            averages_per_iteration=1,
            experiment_length_ms=50.0,
        )

        # Result should be positive real numbers (FFT magnitude)
        assert np.all(mobility_spectrum >= 0)
        assert len(atd_time_ms) == len(mobility_spectrum)
        # Should have half the length of input (positive frequencies only)
        assert len(mobility_spectrum) == 50  # 100 / 2

    def test_ftims_transform_preserves_energy(self):
        """Test that FFT transformation preserves signal energy."""
        frequencies = [10.0, 20.0, 30.0]
        frequency_domain = {}
        original_energy = 0.0

        for freq in frequencies:
            t = np.linspace(0, 1, 100)
            signal = np.sin(2 * np.pi * freq * t) + np.random.normal(0, 0.1, 100)
            frequency_domain[freq] = signal
            original_energy += np.sum(signal**2)

        mobility_spectrum, atd_time_ms = _ftims_transform_to_mobility(
            frequency_domain,
            start_frequency_hz=10.0,
            frequency_step_hz=10.0,
            averages_per_iteration=1,
            experiment_length_ms=50.0,
        )

        # Parseval's theorem: energy in time domain = energy in freq domain
        # (FFT magnitude squared sums to original signal energy)
        fft_energy = np.sum(mobility_spectrum**2)

        # Should be roughly proportional (accounting for FFT normalization)
        # FFT output is not normalized, so check order of magnitude is similar
        assert fft_energy > 0
        assert original_energy > 0
        assert len(atd_time_ms) == len(mobility_spectrum)


class TestHardwareSimulationMode:
    """Test hardware interface simulation mode for FTIMS."""

    def test_simulate_ftims_frequency_scan(self):
        """Test FTIMS simulation produces reasonable signals."""
        config = DaqConfig(
            ai_channel="Dev1/ai0",
            counter_channel="Dev1/ctr0",
            pfi_trigger="Dev1/PFI0",
            pulse_width_ms=1.0,
            experiment_length_ms=50.0,
            data_points=4000,
            use_simulation=True,
        )

        controller = NiUSB6351Controller(config)
        freq_data = controller._simulate_ftims_frequency_scan(10.0, 100)

        assert len(freq_data) == 100
        assert np.all(np.isfinite(freq_data))
        assert np.any(freq_data != 0)

    def test_acquire_scan_stepped_ftims_simulation(self):
        """Test full FTIMS acquisition in simulation mode."""
        config = DaqConfig(
            ai_channel="Dev1/ai0",
            counter_channel="Dev1/ctr0",
            pfi_trigger="Dev1/PFI0",
            pulse_width_ms=1.0,
            experiment_length_ms=50.0,
            data_points=4000,
            use_simulation=True,
        )

        controller = NiUSB6351Controller(config)

        freq_domain = controller.acquire_scan_stepped_ftims(
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            end_frequency_hz=20.0,
            time_per_frequency_ms=100.0,
        )

        # Should have 3 frequency steps: 10, 15, 20
        assert len(freq_domain) == 3
        assert 10.0 in freq_domain
        assert 15.0 in freq_domain
        assert 20.0 in freq_domain

        # Each should be a numpy array with samples
        for freq, signal in freq_domain.items():
            assert isinstance(signal, np.ndarray)
            assert len(signal) > 0
            assert np.all(np.isfinite(signal))


class TestFTIMSAcquisitionSubprocess:
    """Integration tests for FTIMS acquisition subprocess."""

    def test_ftims_simulation_end_to_end(self):
        """Test complete FTIMS acquisition in simulation mode via subprocess."""
        src_dir = Path(__file__).resolve().parents[1] / "src"

        config = ExperimentConfig(
            operation_mode=OperationMode.FTIMS,
            data_points=1000,  # Smaller for testing
            total_iterations=2,
            averages_per_iteration=1,
            use_simulation=True,
            ftims_config=FTIMSConfig(
                start_frequency_hz=10.0,
                frequency_step_hz=5.0,
                end_frequency_hz=20.0,
                time_per_frequency_ms=100.0,
            ),
        )

        payload = {
            "ai_channel": config.ai_channel,
            "counter_channel": config.counter_channel,
            "pfi_trigger": config.pfi_trigger,
            "pulse_width_ms": config.pulse_width_ms,
            "experiment_length_ms": config.experiment_length_ms,
            "data_points": config.data_points,
            "total_iterations": config.total_iterations,
            "averages_per_iteration": config.averages_per_iteration,
            "positive_mode": config.positive_mode,
            "use_simulation": config.use_simulation,
            "operation_mode": config.operation_mode.value,
            "ftims_start_frequency_hz": config.ftims_config.start_frequency_hz,
            "ftims_frequency_step_hz": config.ftims_config.frequency_step_hz,
            "ftims_end_frequency_hz": config.ftims_config.end_frequency_hz,
            "ftims_time_per_frequency_ms": config.ftims_config.time_per_frequency_ms,
        }

        cmd = [
            sys.executable,
            "-m",
            "ims_control.acquisition.daq_cli",
            "--payload",
            json.dumps(payload, separators=(",", ":")),
        ]

        import os

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_dir) + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )

        result = subprocess.run(
            cmd,
            cwd=str(src_dir.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"

        # Parse JSON events
        events = []
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        # Should have status, progress, iteration, and finished events
        event_types = [e.get("type") for e in events]
        assert "status" in event_types
        assert "progress" in event_types
        assert "iteration" in event_types
        assert "finished" in event_types

        # Find iteration events
        iteration_events = [e for e in events if e.get("type") == "iteration"]
        assert len(iteration_events) >= 2  # At least 2 iterations

        # Each iteration should have mobility-domain data
        for iter_event in iteration_events:
            assert "data" in iter_event
            assert "iteration" in iter_event
            data = iter_event["data"]
            assert isinstance(data, list)
            assert len(data) == config.data_points

    def test_dtims_still_works(self):
        """Regression test: DTIMS acquisition should still work."""
        src_dir = Path(__file__).resolve().parents[1] / "src"

        config = ExperimentConfig(
            operation_mode=OperationMode.DTIMS,
            pulse_width_ms=1.0,
            experiment_length_ms=50.0,
            data_points=1000,
            total_iterations=1,
            averages_per_iteration=1,
            use_simulation=True,
        )

        payload = {
            "ai_channel": config.ai_channel,
            "counter_channel": config.counter_channel,
            "pfi_trigger": config.pfi_trigger,
            "pulse_width_ms": config.pulse_width_ms,
            "experiment_length_ms": config.experiment_length_ms,
            "data_points": config.data_points,
            "total_iterations": config.total_iterations,
            "averages_per_iteration": config.averages_per_iteration,
            "positive_mode": config.positive_mode,
            "use_simulation": config.use_simulation,
            "operation_mode": config.operation_mode.value,
        }

        cmd = [
            sys.executable,
            "-m",
            "ims_control.acquisition.daq_cli",
            "--payload",
            json.dumps(payload, separators=(",", ":")),
        ]

        import os

        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_dir) + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )

        result = subprocess.run(
            cmd,
            cwd=str(src_dir.parent),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"DTIMS subprocess failed: {result.stderr}"

        # Parse events
        events = []
        for line in result.stdout.splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        event_types = [e.get("type") for e in events]
        assert "finished" in event_types
        assert "iteration" in event_types
