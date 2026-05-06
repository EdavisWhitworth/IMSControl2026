from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

try:
    import nidaqmx
    from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration, LineGrouping
    from nidaqmx.stream_writers import CounterWriter
    from nidaqmx.system import System
except Exception:  # pragma: no cover
    nidaqmx = None
    AcquisitionType = Edge = TerminalConfiguration = None
    LineGrouping = None
    CounterWriter = None
    System = None


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
        self._counter_writer: Optional[Any] = None
        self._counter_started = False

    @property
    def available(self) -> bool:
        return nidaqmx is not None and not self.config.use_simulation

    @staticmethod
    def _get_device_info() -> str:
        """Get available devices and their channels."""
        if System is None:
            return "nidaqmx not available"
        
        try:
            system = System.local()
            devices = system.devices
            if not devices:
                return "No DAQ devices found"
            
            info_lines = []
            for device in devices:
                info_lines.append(f"\nDevice: {device.name}")
                try:
                    ai_channels = device.ai_physical_chans
                    if ai_channels:
                        info_lines.append(f"  AI Channels: {', '.join(ch.name for ch in ai_channels)}")
                except Exception:
                    pass
                try:
                    co_channels = device.co_physical_chans
                    if co_channels:
                        info_lines.append(f"  Counter Channels: {', '.join(ch.name for ch in co_channels)}")
                except Exception:
                    pass
                try:
                    pfi_lines = device.pfi_physical_chans
                    if pfi_lines:
                        info_lines.append(f"  PFI Lines: {', '.join(ch.name for ch in pfi_lines)}")
                except Exception:
                    pass
            return "\n".join(info_lines)
        except Exception as e:
            return f"Error scanning devices: {e}"

    @staticmethod
    def _normalize_trigger_source(trigger: str) -> str:
        """Normalize trigger text into a DAQmx-compatible terminal string."""
        text = (trigger or "").strip()
        if not text:
            return ""

        if text.upper().startswith("PFI"):
            return text

        if text.startswith("/"):
            return text

        if "/" in text:
            device, line = text.split("/", 1)
            device = device.strip()
            line = line.strip()
            if device and line:
                return f"/{device}/{line}"

        return text

    @staticmethod
    def _counter_internal_output(counter_channel: str) -> str:
        """Map 'DevX/ctrN' to '/DevX/CtrNInternalOutput' for internal routing."""
        channel = (counter_channel or "").strip()
        if "/" not in channel:
            return ""
        device, ctr = channel.split("/", 1)
        device = device.strip()
        ctr = ctr.strip()
        if not device or not ctr:
            return ""
        ctr_name = ctr[0].upper() + ctr[1:] if ctr else ctr
        return f"/{device}/{ctr_name}InternalOutput"

    def open(self) -> None:
        if not self.available:
            return

        step = "initialization"
        try:
            # Validate channel strings format
            if not self.config.ai_channel or "/" not in self.config.ai_channel:
                raise ValueError(
                    f"Invalid AI channel format: {self.config.ai_channel}. "
                    f"Use format like 'Dev1/ai0'."
                )
            if not self.config.counter_channel or "/" not in self.config.counter_channel:
                raise ValueError(
                    f"Invalid Counter channel format: {self.config.counter_channel}. "
                    f"Use format like 'Dev1/ctr0'."
                )

            ai_channel = self.config.ai_channel.strip()
            counter_channel = self.config.counter_channel.strip()
            trigger_source = self._normalize_trigger_source(self.config.pfi_trigger)
            internal_trigger_source = self._counter_internal_output(counter_channel)

            # For self-clocked IMS acquisition, tie AI start to the counter's internal output.
            # This avoids missing external PFI edges across repeated iterations/scans.
            effective_trigger_source = internal_trigger_source or trigger_source

            # Create and configure AI task
            step = "AI task creation"
            ai_task = nidaqmx.Task()
            try:
                step = "AI channel configuration"
                ai_task.ai_channels.add_ai_voltage_chan(
                    ai_channel,
                    terminal_config=TerminalConfiguration.RSE,
                )

                if effective_trigger_source:
                    step = "AI trigger configuration"
                    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(effective_trigger_source)
                    ai_task.triggers.start_trigger.retriggerable = False

                step = "AI timing configuration"
                ai_task.timing.cfg_samp_clk_timing(
                    rate=self.config.sample_rate_hz,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=self.config.data_points,
                )
                self._ai_task = ai_task
            except Exception as e:
                ai_task.close()
                raise ValueError(f"Failed to configure AI task: {e}") from e

            # Create and configure counter task
            step = "counter task creation"
            co_task = nidaqmx.Task()
            try:
                # Calculate timing values (convert from ms to seconds)
                high_time = max(1e-6, self.config.pulse_width_ms / 1000.0)
                low_time = max(1e-6, (self.config.experiment_length_ms / 1000.0) - (self.config.pulse_width_ms / 1000.0))

                # Prefer the known-good time-based call; fall back to frequency-based if needed.
                step = "counter channel configuration (time-based)"
                try:
                    co_task.co_channels.add_co_pulse_chan_time(
                        counter=counter_channel,
                        high_time=high_time,
                        low_time=low_time,
                    )
                except Exception as time_err:
                    period_s = max(2e-6, high_time + low_time)
                    freq_hz = 1.0 / period_s
                    duty_cycle = min(0.999999, max(1e-6, high_time / period_s))
                    step = "counter channel configuration (frequency fallback)"
                    co_task.co_channels.add_co_pulse_chan_freq(
                        counter=counter_channel,
                        freq=freq_hz,
                        duty_cycle=duty_cycle,
                    )

                # Configure CONTINUOUS timing mode for sustained pulse generation
                step = "counter timing configuration"
                co_task.timing.cfg_implicit_timing(
                    sample_mode=AcquisitionType.CONTINUOUS
                )

                self._co_task = co_task
                step = "counter start"
                self._co_task.start()
                self._counter_started = True

            except Exception as e:
                co_task.close()
                raise ValueError(f"Failed to configure counter task at '{step}': {e}") from e

        except Exception as e:
            # Clean up any partially initialized tasks
            if self._ai_task is not None:
                try:
                    self._ai_task.close()
                except Exception:
                    pass
                self._ai_task = None
            if self._co_task is not None:
                try:
                    if self._counter_started:
                        try:
                            self._co_task.stop()
                        except Exception:
                            pass
                    self._co_task.close()
                except Exception:
                    pass
                self._co_task = None
                self._counter_started = False
            
            device_info = self._get_device_info()
            error_msg = str(e)
            if "access violation" in error_msg.lower():
                device_msg = (
                    "Access violation during counter configuration. Try:\n"
                    "  1. Verify counter and AI channels are available\n"
                    "  2. Ensure no other application is using these channels\n"
                    "  3. Update NI-DAQmx drivers to the latest version\n"
                    "  4. Try a different counter line (for example Dev1/ctr1)"
                )
            else:
                device_msg = "Check the channel configuration and available devices."

            raise RuntimeError(
                f"Failed to configure DAQ device at step '{step}'. {device_msg}\n\n"
                f"Error: {error_msg}\n\n"
                f"Configured channels:\n"
                f"  AI: {ai_channel if 'ai_channel' in locals() else self.config.ai_channel}\n"
                f"  Counter: {counter_channel if 'counter_channel' in locals() else self.config.counter_channel}\n"
                f"  PFI Trigger: {trigger_source if 'trigger_source' in locals() else self.config.pfi_trigger}\n"
                f"  Effective Trigger: {effective_trigger_source if 'effective_trigger_source' in locals() else 'none'}\n"
                f"  Pulse Width (ms): {self.config.pulse_width_ms}\n"
                f"  Experiment Length (ms): {self.config.experiment_length_ms}\n"
                f"  Data Points: {self.config.data_points}\n"
                f"  Sample Rate (Hz): {self.config.sample_rate_hz:.3f}\n\n"
                f"Available devices and channels:\n{device_info}"
            ) from e

    def close(self) -> None:
        if self._ai_task is not None:
            try:
                self._ai_task.close()
            except Exception:
                pass
            self._ai_task = None
        if self._co_task is not None:
            try:
                if self._counter_started:
                    try:
                        self._co_task.stop()
                    except Exception:
                        pass
                self._co_task.close()
            except Exception:
                pass
            self._co_task = None
            self._counter_started = False
        self._counter_writer = None

    def _set_counter_frequency(self, frequency_hz: float, duty_cycle: float = 0.5) -> None:
        """Reconfigure counter output for a specific FTIMS step frequency."""
        if not self.available:
            return
        if nidaqmx is None:
            raise RuntimeError("nidaqmx is not available")

        freq = max(1e-6, float(frequency_hz))
        duty = min(0.999999, max(1e-6, float(duty_cycle)))

        # Stop and replace the counter task so new frequency settings take effect.
        if self._co_task is not None:
            try:
                if self._counter_started:
                    self._co_task.stop()
            except Exception:
                pass
            try:
                self._co_task.close()
            except Exception:
                pass
            self._co_task = None
            self._counter_started = False

        co_task = nidaqmx.Task()
        try:
            co_task.co_channels.add_co_pulse_chan_freq(
                counter=self.config.counter_channel.strip(),
                freq=freq,
                duty_cycle=duty,
            )
            co_task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)
            co_task.start()
            self._co_task = co_task
            self._counter_started = True
        except Exception:
            try:
                co_task.close()
            except Exception:
                pass
            raise

    def acquire_scan(self) -> np.ndarray:
        if not self.available:
            return self._simulate_scan()

        if self._ai_task is None or self._co_task is None:
            self.open()

        if self._ai_task is None or self._co_task is None:
            raise RuntimeError("DAQ tasks not initialized properly")

        try:
            # Keep counter running continuously so pulse spacing is hardware-timed and stable.
            if not self._counter_started:
                self._co_task.start()
                self._counter_started = True

            self._ai_task.start()
            
            # Read data
            data = self._ai_task.read(number_of_samples_per_channel=self.config.data_points)
            
            # Stop AI task only; counter continues running for deterministic pulse spacing.
            self._ai_task.stop()
            
            y = np.asarray(data, dtype=np.float64)
            return y
        except Exception as e:
            raise RuntimeError(f"Acquisition failed: {e}") from e

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

    def acquire_scan_stepped_ftims(
        self, 
        start_frequency_hz: float, 
        frequency_step_hz: float, 
        end_frequency_hz: float,
        time_per_frequency_ms: float
    ) -> dict[float, np.ndarray]:
        """
        Acquire frequency-domain data for Stepped FTIMS mode.
        
        Steps through discrete frequencies from start to end, collecting data at each frequency.
        Software-timed frequency stepping (asynchronous) compatible with long amplifier rise times.
        
        Args:
            start_frequency_hz: Starting frequency in Hz
            frequency_step_hz: Frequency step size in Hz
            end_frequency_hz: Ending frequency in Hz
            time_per_frequency_ms: Time to collect data at each frequency (ms)
            
        Returns:
            Dictionary mapping frequency (Hz) → accumulated signal (np.ndarray)
        """
        import time
        
        # Generate frequency steps
        frequencies = []
        f = start_frequency_hz
        while f <= end_frequency_hz + 1e-6:
            frequencies.append(f)
            f += frequency_step_hz
        
        if not frequencies:
            raise ValueError("No frequencies generated for FTIMS scan")
        
        frequency_domain_data: dict[float, np.ndarray] = {}
        
        for freq in frequencies:
            freq_data = self.acquire_ftims_frequency_step(
                frequency_hz=freq,
                time_per_frequency_ms=time_per_frequency_ms,
            )
            
            frequency_domain_data[freq] = freq_data
        
        return frequency_domain_data

    def acquire_ftims_frequency_step(self, frequency_hz: float, time_per_frequency_ms: float) -> np.ndarray:
        """Acquire one FTIMS frequency step and return its time-domain signal."""
        import time

        # Keep per-step length fixed to configured data_points so downstream
        # FFT output and UI storage dimensions always match.
        samples_needed = max(1, int(self.config.data_points))

        if not self.available:
            return self._simulate_ftims_frequency_scan(float(frequency_hz), samples_needed)

        if self._ai_task is None or self._co_task is None:
            self.open()

        if self._ai_task is None or self._co_task is None:
            raise RuntimeError("DAQ tasks not initialized properly")

        try:
            # Reconfigure counter output to the current FTIMS step frequency.
            self._set_counter_frequency(float(frequency_hz), duty_cycle=0.5)

            # Software-timed delay: 100ms per article to establish frequency.
            _ = float(time_per_frequency_ms)  # reserved for future timing policy
            time.sleep(0.1)

            # Create a temporary AI task scoped to this frequency step.
            temp_ai_task = nidaqmx.Task()
            try:
                temp_ai_task.ai_channels.add_ai_voltage_chan(
                    self.config.ai_channel,
                    terminal_config=TerminalConfiguration.RSE,
                )

                temp_ai_task.timing.cfg_samp_clk_timing(
                    rate=self.config.sample_rate_hz,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=samples_needed,
                )

                temp_ai_task.start()
                freq_data = np.asarray(
                    temp_ai_task.read(number_of_samples_per_channel=samples_needed),
                    dtype=np.float64,
                )
                temp_ai_task.stop()
            finally:
                temp_ai_task.close()
            return freq_data
        except Exception as e:
            raise RuntimeError(f"FTIMS acquisition failed at {float(frequency_hz)} Hz: {e}") from e

    def _simulate_ftims_frequency_scan(self, frequency_hz: float, samples: int) -> np.ndarray:
        """Generate synthetic frequency-domain data for simulation mode."""
        # Create a signal that varies with frequency to simulate realistic FTIMS response
        t = np.linspace(0, samples / self.config.sample_rate_hz, samples)
        
        # Simulate ion gate pulse at the given frequency
        gate_pulse = np.sin(2.0 * np.pi * frequency_hz * t)
        gate_pulse = np.where(gate_pulse > 0, 1.0, 0.0)
        
        # Simulate detector response with frequency-dependent amplitude
        # (lower frequencies have better response in typical IMS)
        response_amplitude = 1.0 / (1.0 + frequency_hz / 1000.0)
        
        # Add noise
        noise = self._rng.normal(0, 0.01 * response_amplitude, size=samples)
        
        signal = response_amplitude * gate_pulse + noise
        return signal.astype(np.float64)

    def write_analog_output(self, channel: str, voltage: float) -> None:
        """Write a single analog-output voltage on the provided AO channel."""
        if not self.available:
            return
        if nidaqmx is None:
            raise RuntimeError("nidaqmx is not available")

        text = (channel or "").strip()
        if not text or "/" not in text:
            raise ValueError(f"Invalid AO channel format: {channel}")

        try:
            with nidaqmx.Task() as ao_task:
                ao_task.ao_channels.add_ao_voltage_chan(text)
                ao_task.write(float(voltage), auto_start=True, timeout=1.0)
        except Exception as exc:
            raise RuntimeError(f"Failed AO write on '{text}': {exc}") from exc

    def write_dual_analog_output(
        self,
        channel_1: str,
        channel_2: str,
        voltage_1: float,
        voltage_2: float,
    ) -> None:
        """Write two AO channels in one task for faster and more stable updates."""
        if not self.available:
            return
        if nidaqmx is None:
            raise RuntimeError("nidaqmx is not available")

        ch1 = (channel_1 or "").strip()
        ch2 = (channel_2 or "").strip()
        if not ch1 or "/" not in ch1:
            raise ValueError(f"Invalid AO channel format: {channel_1}")
        if not ch2 or "/" not in ch2:
            raise ValueError(f"Invalid AO channel format: {channel_2}")

        try:
            with nidaqmx.Task() as ao_task:
                ao_task.ao_channels.add_ao_voltage_chan(ch1)
                ao_task.ao_channels.add_ao_voltage_chan(ch2)
                ao_task.write([float(voltage_1), float(voltage_2)], auto_start=True, timeout=2.0)
        except Exception as exc:
            raise RuntimeError(f"Failed dual AO write on '{ch1}, {ch2}': {exc}") from exc

    def write_digital_line(self, line: str, state: bool) -> None:
        """Write a single digital line state on the provided DO line."""
        if not self.available:
            return
        if nidaqmx is None:
            raise RuntimeError("nidaqmx is not available")

        text = (line or "").strip()
        if not text or "/" not in text:
            raise ValueError(f"Invalid DO line format: {line}")

        try:
            with nidaqmx.Task() as do_task:
                do_task.do_channels.add_do_chan(text, line_grouping=LineGrouping.CHAN_PER_LINE)
                do_task.write(bool(state), auto_start=True, timeout=1.0)
        except Exception as exc:
            raise RuntimeError(f"Failed DO write on '{text}': {exc}") from exc
