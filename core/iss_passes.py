#!/usr/bin/env python3
"""ISS Voice pass prediction provider.

Planning-only orbital calculations for NORAD 25544. This module does not
claim receivers, control services, or execute captures.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml
from skyfield.api import EarthSatellite, load, wgs84

from core.config import load_station

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "iss_voice.yaml"
TLE_FILE = ROOT / "data" / "tle" / "iss.tle"


def _read_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    root = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    config = root.get("iss_voice", {}) if isinstance(root, dict) else {}
    return config if isinstance(config, dict) else {}


def _station_location():
    station = (load_station() or {}).get("station", {})
    return wgs84.latlon(
        float(station["latitude"]),
        float(station["longitude"]),
        elevation_m=float(station.get("altitude_m", 0)),
    )


def _load_tle() -> tuple[str, str, str] | None:
    if not TLE_FILE.exists():
        return None
    lines = [line.strip() for line in TLE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 3:
        return None
    name, line1, line2 = lines[:3]
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        return None
    return name, line1, line2


def tle_age_hours() -> float | None:
    if not TLE_FILE.exists():
        return None
    age = datetime.now(timezone.utc).timestamp() - TLE_FILE.stat().st_mtime
    return round(max(0.0, age) / 3600.0, 1)


def get_status() -> dict[str, Any]:
    config = _read_config()
    tle = _load_tle()
    enabled = bool(config.get("enabled", False))
    planner_enabled = bool(config.get("planner_enabled", False))
    if not enabled:
        state, detail = "disabled", "ISS Voice plugin is disabled."
    elif not planner_enabled:
        state, detail = "planner_disabled", "ISS Voice pass planning is disabled."
    elif tle is None:
        state, detail = "tle_missing", "ISS TLE is missing or invalid."
    else:
        state, detail = "active", "ISS Voice pass prediction is active; execution remains disabled."
    return {
        "state": state,
        "detail": detail,
        "tle_file": str(TLE_FILE),
        "tle_present": tle is not None,
        "tle_age_hours": tle_age_hours(),
        "norad_id": int(config.get("norad_id", 25544)),
    }


def get_passes(hours_ahead: int = 48) -> list[dict[str, Any]]:
    config = _read_config()
    if not bool(config.get("enabled", False)) or not bool(config.get("planner_enabled", False)):
        return []
    tle = _load_tle()
    if tle is None:
        return []

    tle_name, line1, line2 = tle
    ts = load.timescale()
    satellite_name = str(config.get("satellite_name") or tle_name or "ISS (ZARYA)")
    satellite = EarthSatellite(line1, line2, satellite_name, ts)
    station = _station_location()
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=max(1, min(int(hours_ahead), 168)))
    minimum_elevation = float(config.get("minimum_elevation", 20.0))

    times, events = satellite.find_events(
        station,
        ts.from_datetime(now),
        ts.from_datetime(future),
        altitude_degrees=minimum_elevation,
    )

    candidates: list[dict[str, Any]] = []
    for index in range(len(events) - 2):
        if events[index:index + 3].tolist() != [0, 1, 2]:
            continue
        start_time, maximum_time, end_time = times[index:index + 3]
        topocentric = (satellite - station).at(maximum_time)
        altitude, azimuth, _distance = topocentric.altaz()
        candidates.append(
            {
                "name": satellite_name,
                "start": start_time.utc_datetime(),
                "maximum": maximum_time.utc_datetime(),
                "end": end_time.utc_datetime(),
                "max_elevation": round(float(altitude.degrees), 1),
                "azimuth": round(float(azimuth.degrees), 1),
                "frequency": int(config.get("downlink_frequency_hz", 437_800_000)),
                "sample_rate": int(config.get("rf_sample_rate_hz", 240_000)),
                "pipeline": str(config.get("capture_strategy", "wideband_iq")),
                "mode": str(config.get("modulation", "NFM")),
                "decoder": "offline_fm",
                "min_elevation": minimum_elevation,
                "norad_id": int(config.get("norad_id", 25544)),
            }
        )

    candidates.sort(key=lambda item: item["start"])
    return candidates
