"""Unit tests for FTIMS configuration classes."""

import pytest
from ims_control.data_model.experiment import (
    OperationMode,
    FTIMSConfig,
    ExperimentConfig,
)


class TestOperationMode:
    """Test OperationMode enum."""

    def test_dtims_value(self):
        """Test DTIMS enum value."""
        assert OperationMode.DTIMS.value == "DTIMS"

    def test_ftims_value(self):
        """Test FTIMS enum value."""
        assert OperationMode.FTIMS.value == "FTIMS"

    def test_from_string_dtims(self):
        """Test creating enum from string."""
        mode = OperationMode("DTIMS")
        assert mode == OperationMode.DTIMS

    def test_from_string_ftims(self):
        """Test creating enum from string."""
        mode = OperationMode("FTIMS")
        assert mode == OperationMode.FTIMS


class TestFTIMSConfig:
    """Test FTIMSConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values match article recommendations."""
        config = FTIMSConfig()
        assert config.start_frequency_hz == 10.0
        assert config.frequency_step_hz == 5.0
        assert config.end_frequency_hz == 4000.0
        assert config.time_per_frequency_ms == 1000.0
        assert config.enable_fft is True

    def test_custom_values(self):
        """Test setting custom values."""
        config = FTIMSConfig(
            start_frequency_hz=20.0,
            frequency_step_hz=10.0,
            end_frequency_hz=2000.0,
            time_per_frequency_ms=500.0,
        )
        assert config.start_frequency_hz == 20.0
        assert config.frequency_step_hz == 10.0
        assert config.end_frequency_hz == 2000.0
        assert config.time_per_frequency_ms == 500.0

    def test_frequency_steps_calculation(self):
        """Test frequency step generation."""
        config = FTIMSConfig(
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            end_frequency_hz=20.0,
        )
        steps = config.frequency_steps()
        expected = [10.0, 15.0, 20.0]
        assert steps == pytest.approx(expected)

    def test_frequency_steps_with_float_precision(self):
        """Test frequency steps handle floating-point arithmetic."""
        config = FTIMSConfig(
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            end_frequency_hz=4000.0,
        )
        steps = config.frequency_steps()
        # Should have 799 steps: (4000 - 10) / 5 + 1 = 799
        assert len(steps) == 799
        assert steps[0] == pytest.approx(10.0)
        assert steps[-1] == pytest.approx(4000.0)

    def test_total_frequencies(self):
        """Test total frequency count."""
        config = FTIMSConfig(
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            end_frequency_hz=20.0,
        )
        assert config.total_frequencies() == 3

    def test_estimated_duration(self):
        """Test duration estimation."""
        config = FTIMSConfig(
            start_frequency_hz=10.0,
            frequency_step_hz=5.0,
            end_frequency_hz=20.0,
            time_per_frequency_ms=1000.0,
        )
        # 3 frequencies * 1000ms = 3000ms = 3.0s
        assert config.estimated_duration_seconds() == pytest.approx(3.0)

    def test_estimated_duration_with_article_defaults(self):
        """Test estimated duration with article-recommended defaults."""
        config = FTIMSConfig()
        # (4000 - 10) / 5 + 1 = 799 frequencies
        # 799 * 1000ms = 799000ms = 799s ≈ 13.3 min
        expected_seconds = 799 * 1.0
        assert config.estimated_duration_seconds() == pytest.approx(expected_seconds)

    def test_to_dict(self):
        """Test serialization to dict."""
        config = FTIMSConfig(
            start_frequency_hz=20.0,
            frequency_step_hz=10.0,
            end_frequency_hz=2000.0,
            time_per_frequency_ms=500.0,
        )
        config_dict = config.to_dict()
        assert config_dict["start_frequency_hz"] == 20.0
        assert config_dict["frequency_step_hz"] == 10.0
        assert config_dict["end_frequency_hz"] == 2000.0
        assert config_dict["time_per_frequency_ms"] == 500.0

    def test_from_dict(self):
        """Test deserialization from dict."""
        raw = {
            "start_frequency_hz": 20.0,
            "frequency_step_hz": 10.0,
            "end_frequency_hz": 2000.0,
            "time_per_frequency_ms": 500.0,
            "enable_fft": True,
        }
        config = FTIMSConfig.from_dict(raw)
        assert config.start_frequency_hz == 20.0
        assert config.frequency_step_hz == 10.0
        assert config.end_frequency_hz == 2000.0
        assert config.time_per_frequency_ms == 500.0

    def test_from_dict_with_defaults(self):
        """Test deserialization with missing fields uses defaults."""
        raw = {"start_frequency_hz": 20.0}
        config = FTIMSConfig.from_dict(raw)
        assert config.start_frequency_hz == 20.0
        assert config.frequency_step_hz == 5.0  # default
        assert config.end_frequency_hz == 4000.0  # default


class TestExperimentConfig:
    """Test ExperimentConfig with operation mode."""

    def test_default_mode_is_dtims(self):
        """Test that default operation mode is DTIMS."""
        config = ExperimentConfig()
        assert config.operation_mode == OperationMode.DTIMS

    def test_ftims_mode_creation(self):
        """Test creating FTIMS config."""
        config = ExperimentConfig(operation_mode=OperationMode.FTIMS)
        assert config.operation_mode == OperationMode.FTIMS
        assert config.ftims_config is not None

    def test_ftims_config_attributes(self):
        """Test FTIMS config attributes are accessible."""
        config = ExperimentConfig(operation_mode=OperationMode.FTIMS)
        assert config.ftims_config.start_frequency_hz == 10.0
        assert config.ftims_config.end_frequency_hz == 4000.0

    def test_to_dict_includes_mode(self):
        """Test serialization includes operation mode."""
        config = ExperimentConfig(operation_mode=OperationMode.FTIMS)
        config_dict = config.to_dict()
        assert config_dict["operation_mode"] == "FTIMS"

    def test_to_dict_includes_ftims_config(self):
        """Test serialization includes FTIMS config."""
        config = ExperimentConfig(operation_mode=OperationMode.FTIMS)
        config_dict = config.to_dict()
        assert "ftims_config" in config_dict
        assert isinstance(config_dict["ftims_config"], dict)

    def test_from_dict_dtims_mode(self):
        """Test deserialization with DTIMS mode."""
        raw = {
            "operation_mode": "DTIMS",
            "pulse_width_ms": 1.0,
            "experiment_length_ms": 50.0,
            "data_points": 4000,
            "averages_per_iteration": 10,
            "total_iterations": 50,
        }
        config = ExperimentConfig.from_dict(raw)
        assert config.operation_mode == OperationMode.DTIMS

    def test_from_dict_ftims_mode(self):
        """Test deserialization with FTIMS mode."""
        raw = {
            "operation_mode": "FTIMS",
            "pulse_width_ms": 1.0,
            "experiment_length_ms": 50.0,
            "data_points": 4000,
            "averages_per_iteration": 10,
            "total_iterations": 50,
            "ftims_config": {
                "start_frequency_hz": 20.0,
                "frequency_step_hz": 10.0,
                "end_frequency_hz": 2000.0,
                "time_per_frequency_ms": 500.0,
            },
        }
        config = ExperimentConfig.from_dict(raw)
        assert config.operation_mode == OperationMode.FTIMS
        assert config.ftims_config.start_frequency_hz == 20.0

    def test_from_dict_backward_compatibility(self):
        """Test loading old DTIMS-only config still works."""
        # Old config without operation_mode field
        raw = {
            "pulse_width_ms": 1.0,
            "experiment_length_ms": 50.0,
            "data_points": 4000,
            "averages_per_iteration": 10,
            "total_iterations": 50,
        }
        config = ExperimentConfig.from_dict(raw)
        # Should default to DTIMS
        assert config.operation_mode == OperationMode.DTIMS

    def test_round_trip_serialization_dtims(self):
        """Test DTIMS config can be serialized and deserialized."""
        original = ExperimentConfig(
            operation_mode=OperationMode.DTIMS,
            pulse_width_ms=2.5,
            experiment_length_ms=100.0,
            total_iterations=25,
        )
        serialized = original.to_dict()
        restored = ExperimentConfig.from_dict(serialized)
        assert restored.operation_mode == original.operation_mode
        assert restored.pulse_width_ms == original.pulse_width_ms
        assert restored.experiment_length_ms == original.experiment_length_ms
        assert restored.total_iterations == original.total_iterations

    def test_round_trip_serialization_ftims(self):
        """Test FTIMS config can be serialized and deserialized."""
        original = ExperimentConfig(
            operation_mode=OperationMode.FTIMS,
            total_iterations=10,
            ftims_config=FTIMSConfig(
                start_frequency_hz=20.0,
                frequency_step_hz=10.0,
                end_frequency_hz=2000.0,
            ),
        )
        serialized = original.to_dict()
        restored = ExperimentConfig.from_dict(serialized)
        assert restored.operation_mode == original.operation_mode
        assert restored.ftims_config.start_frequency_hz == 20.0
        assert restored.ftims_config.frequency_step_hz == 10.0
        assert restored.total_iterations == 10
