from __future__ import annotations

import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ims_control.data_model.experiment import ExperimentConfig, ExperimentData


class ExperimentExporter:
    @staticmethod
    def to_csv(file_path: str, experiment: ExperimentData) -> None:
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
        with h5py.File(file_path, "w") as h5:
            h5.attrs["created_at"] = experiment.created_at
            cfg_group = h5.create_group("config")
            for k, v in experiment.config.to_dict().items():
                cfg_group.attrs[k] = v

            runs = h5.create_group("iterations")
            for i, y in enumerate(experiment.iterations, start=1):
                ds = runs.create_dataset(f"iteration_{i}", data=np.asarray(y, dtype=np.float64))
                ds.attrs["timestamp"] = experiment.iteration_timestamps[i - 1]


class ExperimentImporter:
    @staticmethod
    def from_hdf5(file_path: str) -> ExperimentData:
        with h5py.File(file_path, "r") as h5:
            cfg_attrs = dict(h5["config"].attrs)
            config = ExperimentConfig.from_dict(cfg_attrs)

            exp = ExperimentData(config)
            exp.created_at = str(h5.attrs.get("created_at", exp.created_at))
            for key in sorted(h5["iterations"].keys(), key=lambda x: int(x.split("_")[-1])):
                ds = h5["iterations"][key]
                exp.add_iteration(np.asarray(ds[:], dtype=np.float64))
                exp.iteration_timestamps[-1] = str(ds.attrs.get("timestamp", exp.iteration_timestamps[-1]))
            return exp
