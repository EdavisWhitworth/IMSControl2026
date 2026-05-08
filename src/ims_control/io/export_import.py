"""CSV and HDF5 persistence helpers for experiment results."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ims_control.data_model.experiment import ExperimentConfig, ExperimentData


class ExperimentExporter:
    """Write experiment results and metadata to supported file formats."""
    @staticmethod
    def to_csv(file_path: str, experiment: ExperimentData) -> None:
        """Export iterations to CSV plus a JSON sidecar containing metadata."""
        matrix = experiment.all_iterations_matrix()
        time_ms = np.linspace(
            0.0,
            float(experiment.config.experiment_length_ms),
            int(experiment.config.data_points),
            endpoint=True,
        )
        if matrix.size == 0:
            df = pd.DataFrame({"time_ms": time_ms})
        else:
            data = {"time_ms": time_ms}
            for i in range(matrix.shape[0]):
                data[f"iteration_{i + 1}"] = matrix[i]
            df = pd.DataFrame(data)

        out = Path(file_path)
        df.to_csv(out, index=False)

        meta_out = out.with_suffix(out.suffix + ".meta.json")
        meta_out.write_text(
            json.dumps(
                {
                    "created_at": experiment.created_at,
                    "config": experiment.config.to_dict(),
                    "iteration_timestamps": experiment.iteration_timestamps,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def to_hdf5(file_path: str, experiment: ExperimentData) -> None:
        """Export experiment configuration and iterations to an HDF5 container."""
        with h5py.File(file_path, "w") as h5:
            h5.attrs["created_at"] = experiment.created_at
            cfg_group = h5.create_group("config")
            config_dict = experiment.config.to_dict()
            # Keep a canonical JSON payload so nested mode configs round-trip reliably.
            cfg_group.attrs["config_json"] = json.dumps(config_dict)
            # Also preserve flat scalar attrs for backward compatibility/tools.
            for k, v in config_dict.items():
                if isinstance(v, (str, int, float, bool, np.number, np.bool_)):
                    cfg_group.attrs[k] = v

            runs = h5.create_group("iterations")
            for i, y in enumerate(experiment.iterations, start=1):
                ds = runs.create_dataset(f"iteration_{i}", data=np.asarray(y, dtype=np.float64))
                ds.attrs["timestamp"] = experiment.iteration_timestamps[i - 1]

            if experiment.ftims_raw_spectrum_iterations:
                raw_group = h5.create_group("ftims_raw_spectra")
                for i, raw_points in enumerate(experiment.ftims_raw_spectrum_iterations, start=1):
                    if not raw_points:
                        raw_group.create_dataset(f"iteration_{i}", data=np.empty((0, 2), dtype=np.float64))
                        continue
                    frequencies = np.asarray(sorted(raw_points.keys()), dtype=np.float64)
                    values = np.asarray([raw_points[f] for f in frequencies], dtype=np.float64)
                    raw_group.create_dataset(
                        f"iteration_{i}",
                        data=np.column_stack((frequencies, values)),
                    )

            if experiment.swept_raw_time_domain_iterations:
                swept_raw_group = h5.create_group("swept_raw_iterations")
                for i, raw_sweep in enumerate(experiment.swept_raw_time_domain_iterations, start=1):
                    swept_raw_group.create_dataset(
                        f"iteration_{i}",
                        data=np.asarray(raw_sweep, dtype=np.float64),
                    )

            if experiment.swept_fft_frequency_bins_iterations:
                swept_bins_group = h5.create_group("swept_fft_bins_hz")
                for i, fft_bins in enumerate(experiment.swept_fft_frequency_bins_iterations, start=1):
                    swept_bins_group.create_dataset(
                        f"iteration_{i}",
                        data=np.asarray(fft_bins, dtype=np.float64),
                    )


class ExperimentImporter:
    """Reconstruct experiment objects from persisted files."""
    @staticmethod
    def from_hdf5(file_path: str) -> ExperimentData:
        """Load an experiment and its iteration history from HDF5."""
        with h5py.File(file_path, "r") as h5:
            cfg_group = h5["config"]
            raw_json = cfg_group.attrs.get("config_json")
            if raw_json is not None:
                if isinstance(raw_json, bytes):
                    raw_json = raw_json.decode("utf-8", errors="replace")
                config = ExperimentConfig.from_dict(json.loads(str(raw_json)))
            else:
                # Fallback for legacy files that stored scalar attrs only.
                cfg_attrs = {
                    key: (value.item() if isinstance(value, np.generic) else value)
                    for key, value in dict(cfg_group.attrs).items()
                }
                config = ExperimentConfig.from_dict(cfg_attrs)

            exp = ExperimentData(config)
            exp.created_at = str(h5.attrs.get("created_at", exp.created_at))
            for key in sorted(h5["iterations"].keys(), key=lambda x: int(x.split("_")[-1])):
                ds = h5["iterations"][key]
                exp.add_iteration(np.asarray(ds[:], dtype=np.float64))
                exp.iteration_timestamps[-1] = str(ds.attrs.get("timestamp", exp.iteration_timestamps[-1]))

            raw_group = h5.get("ftims_raw_spectra")
            if isinstance(raw_group, h5py.Group):
                for key in sorted(raw_group.keys(), key=lambda x: int(x.split("_")[-1])):
                    ds = raw_group[key]
                    rows = np.asarray(ds[:], dtype=np.float64)
                    raw_points: dict[float, float] = {}
                    if rows.ndim == 2 and rows.shape[1] == 2:
                        for row in rows:
                            raw_points[float(row[0])] = float(row[1])
                    exp.add_ftims_raw_spectrum_iteration(raw_points)

            swept_raw_group = h5.get("swept_raw_iterations")
            swept_bins_group = h5.get("swept_fft_bins_hz")
            if isinstance(swept_raw_group, h5py.Group) or isinstance(swept_bins_group, h5py.Group):
                keys: set[str] = set()
                if isinstance(swept_raw_group, h5py.Group):
                    keys.update(swept_raw_group.keys())
                if isinstance(swept_bins_group, h5py.Group):
                    keys.update(swept_bins_group.keys())

                for key in sorted(keys, key=lambda x: int(x.split("_")[-1])):
                    raw_arr = np.empty((0,), dtype=np.float64)
                    bins_arr = np.empty((0,), dtype=np.float64)
                    if isinstance(swept_raw_group, h5py.Group) and key in swept_raw_group:
                        raw_arr = np.asarray(swept_raw_group[key][:], dtype=np.float64)
                    if isinstance(swept_bins_group, h5py.Group) and key in swept_bins_group:
                        bins_arr = np.asarray(swept_bins_group[key][:], dtype=np.float64)
                    exp.add_swept_ftims_iteration(raw_arr, bins_arr)
            return exp
