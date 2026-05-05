from __future__ import annotations

import argparse
import json
import sys

from ims_control.hardware.daq_interface import DaqConfig, NiUSB6351Controller


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HV output subprocess")
    parser.add_argument("--payload", required=True, help="JSON-encoded HV payload")
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.payload)
    except Exception as exc:
        _emit({"ok": False, "error": f"Invalid payload: {exc}"})
        return 2

    try:
        daq_cfg = DaqConfig(
            ai_channel=str(payload.get("ai_channel", "Dev1/ai0")),
            counter_channel=str(payload.get("counter_channel", "Dev1/ctr0")),
            pfi_trigger=str(payload.get("pfi_trigger", "Dev1/PFI0")),
            pulse_width_ms=float(payload.get("pulse_width_ms", 1.0)),
            experiment_length_ms=float(payload.get("experiment_length_ms", 50.0)),
            data_points=int(payload.get("data_points", 1000)),
            use_simulation=bool(payload.get("use_simulation", False)),
        )

        ims_ao_channel = str(payload["ims_ao_channel"])
        ion_ao_channel = str(payload["ion_ao_channel"])
        hv_enable_do_line = str(payload["hv_enable_do_line"])
        ims_v = float(payload["ims_v"])
        ion_v = float(payload["ion_v"])
        enabled = bool(payload["enabled"])

        daq = NiUSB6351Controller(daq_cfg)
        daq.write_dual_analog_output(ims_ao_channel, ion_ao_channel, ims_v, ion_v)
        daq.write_digital_line(hv_enable_do_line, enabled)

        _emit(
            {
                "ok": True,
                "enabled": enabled,
                "ims_v": ims_v,
                "ion_v": ion_v,
            }
        )
        return 0
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
