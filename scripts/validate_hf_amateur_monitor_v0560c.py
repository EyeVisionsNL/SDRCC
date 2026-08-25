#!/usr/bin/env python3
"""Validate v0.56.0c HF spectrum measurement and live retune."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()
sys.path.insert(0, str(ROOT))

from scripts import validate_hf_amateur_monitor_v0560b as base  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_retune_contract() -> None:
    check(read("VERSION").strip() in {"0.56.0c", "0.56.0d"}, "release retains the v0.56.0c contract")
    check((ROOT / "docs/hf-amateur-monitor-v0560c.md").is_file(), "v0.56.0c HF documentation is present")

    backend = read("core/hf_monitor_backend.py")
    controller = read("core/hf_monitor_controller.py")
    app = read("dashboard/app.py")
    template = read("dashboard/templates/index.html")
    javascript = read("dashboard/static/js/hf_monitor.js")
    stylesheet = read("dashboard/static/css/hf_monitor.css")

    check("def retune(self, center_frequency_hz: int)" in backend, "open RTL-SDR device supports bounded retune")
    check("def retune(*, center_frequency_hz: int" in backend, "backend exposes worker-owned live retune")
    check("_retune_request" in backend and "_retune_completed_id" in backend, "retune uses request and acknowledgement state")
    check("processor = HFSignalProcessor(" in backend and '_settings["center_frequency_hz"] = target' in backend, "confirmed retune rebuilds DSP and updates observed frequency")
    check('"points": list(_spectrum_points) if spectrum_available else []' in backend, "stale spectrum is not projected as live data")
    check('"waterfall": list(_waterfall) if spectrum_available else []' in backend, "stale waterfall is not projected as live data")

    retune_start = controller.index("def retune(selection:")
    retune_end = controller.index("\ndef update_rf_controls(", retune_start)
    retune_body = controller[retune_start:retune_end]
    check("hf_monitor_backend.retune" in retune_body, "controller delegates live tuning to the existing HF backend")
    check("receiver_manager." not in retune_body and "service_action" not in retune_body, "live retune changes no Receiver Manager or service state")
    check('session["selection"] = normalized' in retune_body and '_write_session(session)' in retune_body, "confirmed live frequency is stored durably")
    check('"retune"' in app and 'hf_monitor_controller.retune' in app, "bounded action endpoint accepts live retune")

    for element in ("hf-monitor-retune", "hf-monitor-spectrum-tooltip", "hf-monitor-spectrum-hint"):
        check(f'id="{element}"' in template, f"HF page contains {element}")
    check('addEventListener("mousemove", moveSpectrumCursor)' in javascript, "spectrum hover measurement is wired")
    check('addEventListener("click", chooseSpectrumFrequency)' in javascript, "spectrum click tuning is wired")
    check('action("retune")' in javascript and "frequencyDirty" in javascript, "manual live frequency changes survive dashboard polling")
    check("dBFS" in javascript and "toFixed(4)" in javascript, "spectrum axes and tooltip expose useful precision")
    check("cursor: crosshair" in stylesheet and ".hf-monitor-spectrum-tooltip" in stylesheet, "measurement cursor follows the HF theme")


def main() -> int:
    try:
        base.validate_static_boundaries()
        base.validate_dsp()
        base.validate_backend_worker()
        result = base.validate_runtime_and_lifecycle()
        validate_retune_contract()
    except Exception as error:  # noqa: BLE001 - release validator
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    result["release"] = "0.56.0c"
    result["live_retune"] = True
    result["spectrum_measurement"] = "MHz+dBFS"
    print("VALIDATION PASS: SDRCC v0.56.0c HF spectrum measurement and live retune")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
