#!/usr/bin/env python3
"""Deterministic v0.54.0w METEOR sample-rate contract checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import satdump


METEOR_NAMES = ("METEOR-M2 3", "METEOR-M2 4")
TARGET_SAMPLE_RATE = 1_024_000

if os.environ.get("FAKE_METEOR_SAMPLE_RATE_FAIL") == "1":
    raise AssertionError("injected METEOR sample-rate validation failure")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


document = yaml.safe_load((ROOT / "config" / "satellites.yaml").read_text(encoding="utf-8")) or {}
satellites = document.get("satellites") or {}
check(all(name in satellites for name in METEOR_NAMES), "both METEOR profiles exist")
check(
    all(satellites[name].get("sample_rate") == TARGET_SAMPLE_RATE for name in METEOR_NAMES),
    "both METEOR profiles use exactly 1024000 S/s",
)
check(
    all(satellites[name].get("pipeline") == "meteor_m2-x_lrpt" for name in METEOR_NAMES),
    "METEOR pipeline ownership remains unchanged",
)
check(
    all(satellites[name].get("decoder") == "satdump" and satellites[name].get("mode") == "LRPT" for name in METEOR_NAMES),
    "METEOR decoder and mode remain unchanged",
)

passes_source = (ROOT / "core" / "passes.py").read_text(encoding="utf-8")
satdump_source = (ROOT / "core" / "satdump.py").read_text(encoding="utf-8")
operations_source = (ROOT / "core" / "mission_operations.py").read_text(encoding="utf-8")
operations_js = (ROOT / "dashboard" / "static" / "js" / "mission_recordings.js").read_text(encoding="utf-8")
check('"sample_rate": sat_cfg.get("sample_rate")' in passes_source, "pass prediction reads the central sample rate")
check('str(next_pass["sample_rate"])' in satdump_source, "SatDump receives the planned sample rate without conversion")
check('"sample_rate_hz": summary.get("sample_rate") if active else None' in operations_source,
      "Mission Operations exposes the active sample rate unchanged")
check('Number(rfConsole.sample_rate_hz) / 1000' in operations_js and '.toFixed(0)} kS/s' in operations_js,
      "Mission Operations renders 1024000 S/s as 1024 kS/s")

original_allowed = satdump.check_recording_allowed
original_device = satdump.get_assigned_device
original_rf = satdump.config_core.get_weather_rf_config
try:
    satdump.check_recording_allowed = lambda: (True, "OK")
    satdump.get_assigned_device = lambda role: {
        "id": "receiver01", "serial": "TEST-SERIAL", "number": 1,
    }
    satdump.config_core.get_weather_rf_config = lambda: {
        "lna_agc": True,
        "gain_mode": "auto",
        "gain_db": 0.0,
        "dc_block": True,
        "iq_swap": False,
        "fill_missing": True,
        "rs_usecheck": True,
    }
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    for name in METEOR_NAMES:
        profile = satellites[name]
        planned = {
            "name": name,
            "frequency": profile["frequency"],
            "sample_rate": profile["sample_rate"],
            "pipeline": profile["pipeline"],
            "mode": profile["mode"],
            "start": start,
            "maximum": start + timedelta(minutes=5),
            "end": start + timedelta(minutes=10),
        }
        record = satdump.build_record_command(planned)
        command = record["command"]
        check(command[command.index("--samplerate") + 1] == "1024000",
              f"{name} launches SatDump with --samplerate 1024000")
        context = satdump.build_event_context(record)
        check(context.get("sample_rate") == TARGET_SAMPLE_RATE,
              f"{name} runtime telemetry retains 1024000 S/s")
finally:
    satdump.check_recording_allowed = original_allowed
    satdump.get_assigned_device = original_device
    satdump.config_core.get_weather_rf_config = original_rf

print("VALIDATION PASS: v0.54.0w METEOR sample-rate correction")
