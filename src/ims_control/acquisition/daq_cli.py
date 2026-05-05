from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


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

    total_iterations = int(payload["total_iterations"])
    averages_per_iteration = int(payload["averages_per_iteration"])
    positive_mode = bool(payload.get("positive_mode", False))

    daq = NiUSB6351Controller(cfg)
    try:
        daq.open()
        _emit({"type": "status", "message": "Acquisition running"})

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