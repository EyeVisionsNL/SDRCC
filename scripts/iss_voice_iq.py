#!/usr/bin/env python3
"""Inspect or explicitly run one bounded ISS Voice IQ capture."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from core import iss_voice
from core.wideband_iq_recorder import build_spec, describe_capture, execute_capture, validate_runtime
from core.device_manager import get_assigned_device

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission-id", default="iss-voice-dry-run")
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--services-confirmed-stopped", action="store_true")
    args = parser.parse_args()
    validation = iss_voice.validate_config()
    if not validation["ok"]:
        print(json.dumps(validation, indent=2)); return 2
    config = validation["config"]
    receiver = get_assigned_device("iss_voice")
    if not receiver:
        print("ISS Voice receiver assignment ontbreekt", file=sys.stderr); return 2
    spec = build_spec(mission_id=args.mission_id, receiver_serial=receiver["serial"],
                      frequency_hz=config["downlink_frequency_hz"],
                      sample_rate_hz=config["rf_sample_rate_hz"],
                      duration_seconds=args.duration)
    payload = {"runtime": validate_runtime(), "capture": describe_capture(spec), "execute_requested": args.execute}
    if args.execute:
        payload["result"] = execute_capture(spec, services_confirmed_stopped=args.services_confirmed_stopped)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
