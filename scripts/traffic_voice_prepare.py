#!/usr/bin/env python3
"""Render the selected Traffic Voice backend configuration atomically."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core import config as config_core
from core import hf_monitor_backend, traffic_voice


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    allowed_root = Path("/run/sdrcc-traffic-voice").resolve()
    try:
        output.relative_to(allowed_root)
    except ValueError as error:
        raise SystemExit("output must remain under /run/sdrcc-traffic-voice") from error
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    gain_status_path = output.parent / "smart_gain.json"
    gain_status_path.unlink(missing_ok=True)
    try:
        config = config_core.load_traffic_voice()
        receiver_settings = traffic_voice.get_receiver_settings(config)
        smart_gain = None
        if receiver_settings["gain_mode"] == "smart":
            plan = traffic_voice.smart_gain_probe_plan(config)
            smart_gain = hf_monitor_backend.probe_smart_gain_for_channels(
                serial=plan["serial"],
                frequencies_hz=plan["frequencies_hz"],
                minimum_snr_db=plan["minimum_snr_db"],
                channel_bandwidth_hz=plan["channel_bandwidth_hz"],
            )
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(traffic_voice.render_rtlsdr_airband_config(
                smart_gain_db=(smart_gain or {}).get("gain_db"),
                payload=config,
            ))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o640)
        temporary.replace(output)
        if smart_gain is not None:
            gain_status_temporary = gain_status_path.with_suffix(".json.tmp")
            gain_status_temporary.write_text(json.dumps({
                "mode_id": plan["mode_id"],
                "gain_db": smart_gain["gain_db"],
                "probed_channels": smart_gain["probed_channels"],
                "measurement": smart_gain.get("measurement"),
            }, indent=2) + "\n", encoding="utf-8")
            os.chmod(gain_status_temporary, 0o640)
            gain_status_temporary.replace(gain_status_path)
            measurement = smart_gain.get("measurement") or {}
            print(
                "SDRCC Smart Gain selected a fixed "
                f"{float(smart_gain['gain_db']):.1f} dB gain "
                f"after probing {int(smart_gain['probed_channels'])} channel(s); "
                f"measured SNR {float(measurement.get('snr_db', 0.0)):.1f} dB.",
                flush=True,
            )
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
