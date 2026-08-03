#!/usr/bin/env python3
"""ISS Voice pass provider using the shared SDRCC pass-window calculation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from skyfield.api import load

from core import passes as pass_prediction
from core import tle, weather_planning

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "iss_voice.yaml"
TLE_FILE = ROOT / "data" / "tle" / "iss.tle"


def _read_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    root = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    config = root.get("iss_voice", {}) if isinstance(root, dict) else {}
    return config if isinstance(config, dict) else {}


def _load_tle() -> tuple[str, str, str] | None:
    config = _read_config()
    catalog = int(config.get("norad_id", 25544))
    name = str(config.get("satellite_name") or tle.REQUIRED_ISS.get(catalog) or "ISS (ZARYA)")
    try:
        blocks = tle.load_file(TLE_FILE, expected_catalogs={catalog: name})
    except (FileNotFoundError, ValueError, OSError):
        return None
    block = blocks[catalog]
    return block["name"], block["line1"], block["line2"]


def tle_age_hours() -> float | None:
    status = tle.file_status(TLE_FILE, expected_catalogs=tle.REQUIRED_ISS)
    value = status.get("age_hours")
    return float(value) if value is not None else None


def get_status() -> dict[str, Any]:
    config = _read_config()
    file_state = tle.file_status(TLE_FILE, expected_catalogs=tle.REQUIRED_ISS)
    enabled = bool(config.get("enabled", False))
    planner_enabled = bool(config.get("planner_enabled", False))
    if not enabled:
        state, detail = "disabled", "ISS Voice plugin is disabled."
    elif not planner_enabled:
        state, detail = "planner_disabled", "ISS Voice pass planning is disabled."
    elif not file_state["valid"]:
        state, detail = "tle_invalid", file_state.get("error") or "ISS TLE is invalid."
    elif file_state["stale"]:
        state, detail = "tle_stale", "ISS Voice planning uses the last valid stale TLE."
    else:
        state, detail = "active", "ISS Voice pass prediction is active."
    return {
        "state": state,
        "detail": detail,
        "tle_file": str(TLE_FILE),
        "tle_present": bool(file_state["valid"]),
        "tle_valid": bool(file_state["valid"]),
        "tle_stale": bool(file_state["stale"]),
        "tle_age_hours": file_state.get("age_hours"),
        "norad_id": int(config.get("norad_id", 25544)),
        "tle_catalogs": file_state.get("catalogs", []),
    }


def get_passes(hours_ahead: int = 48) -> list[dict[str, Any]]:
    config = _read_config()
    if not bool(config.get("enabled", False)) or not bool(config.get("planner_enabled", False)):
        return []
    catalog = int(config.get("norad_id", 25544))
    satellite_name = str(config.get("satellite_name") or "ISS (ZARYA)")
    try:
        blocks = tle.load_file(TLE_FILE, expected_catalogs={catalog: satellite_name})
    except (FileNotFoundError, ValueError, OSError):
        return []
    block = blocks[catalog]
    planning = weather_planning.get_profile("iss_voice")
    ts = load.timescale()
    station = pass_prediction._load_station_location()
    return pass_prediction.predict_satellite_passes(
        name=satellite_name,
        line1=block["line1"],
        line2=block["line2"],
        station=station,
        planning=planning,
        hours_ahead=max(1, min(int(hours_ahead), 168)),
        timescale=ts,
        metadata={
            "frequency": int(config.get("downlink_frequency_hz", 437_800_000)),
            "sample_rate": int(config.get("rf_sample_rate_hz", 240_000)),
            "pipeline": str(config.get("capture_strategy", "wideband_iq")),
            "mode": str(config.get("modulation", "NFM")),
            "decoder": "offline_fm",
            "planning_profile_id": "iss_voice",
            "norad_id": catalog,
            "tle_source": tle.SOURCE_NAME,
            "tle_epoch": block["epoch_iso"],
            "tle_sha256": block["sha256"],
        },
    )
