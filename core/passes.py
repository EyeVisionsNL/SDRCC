#!/usr/bin/env python3
"""Orbital pass calculation for SDRCC.

v0.28.0a introduces a generic target-aware pass engine while preserving the
existing public weather-pass API. Existing callers can continue to use
``get_passes()`` and ``get_next_pass()`` unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from skyfield.api import EarthSatellite, load, wgs84

from core.config import get_enabled_satellites, load_station, load_yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TLE_FILE = PROJECT_ROOT / "data" / "tle" / "weather.tle"
ISS_TLE_FILE = PROJECT_ROOT / "data" / "tle" / "iss.tle"
VOICE_TARGETS_CONFIG = PROJECT_ROOT / "config" / "voice_targets.yaml"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

WEATHER_MISSION_TYPE = "WEATHER"
WEATHER_TARGET_GROUP = "weather"
VOICE_MISSION_TYPE = "VOICE"
VOICE_TARGET_GROUP = "voice"


def _load_station_location():
    cfg = load_station()
    station = cfg.get("station", {})

    latitude = float(station.get("latitude"))
    longitude = float(station.get("longitude"))
    altitude_m = float(station.get("altitude_m", 0))

    return wgs84.latlon(latitude, longitude, elevation_m=altitude_m)


def _load_tle_blocks(tle_file: Path = DEFAULT_TLE_FILE) -> dict[str, tuple[str, str]]:
    """Load three-line TLE blocks from *tle_file* keyed by target name."""
    if not tle_file.exists():
        return {}

    lines = [
        line.strip()
        for line in tle_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    blocks: dict[str, tuple[str, str]] = {}

    for index in range(0, len(lines), 3):
        if index + 2 >= len(lines):
            continue
        blocks[lines[index]] = (lines[index + 1], lines[index + 2])

    return blocks


def _fmt_local(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_targets(
    targets: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for name, config in (targets or {}).items():
        if not isinstance(config, Mapping):
            continue
        normalized[str(name)] = dict(config)
    return normalized


def get_target_passes(
    targets: Mapping[str, Mapping[str, Any]],
    *,
    tle_file: Path = DEFAULT_TLE_FILE,
    hours_ahead: float = 48,
    mission_type: str = WEATHER_MISSION_TYPE,
    target_group: str = WEATHER_TARGET_GROUP,
) -> list[dict[str, Any]]:
    """Calculate passes for an arbitrary configured target collection.

    The returned dictionaries retain all fields used by existing WEATHER
    callers and add ``mission_type`` and ``target_group`` metadata. This is the
    extension point for later ISS Voice, packet and scanner mission providers.
    """
    station_location = _load_station_location()
    configured_targets = _normalize_targets(targets)
    tle_blocks = _load_tle_blocks(Path(tle_file))

    ts = load.timescale()
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=float(hours_ahead))

    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(future)

    candidates: list[dict[str, Any]] = []

    for target_name, target_config in configured_targets.items():
        tle = tle_blocks.get(target_name)
        if tle is None:
            continue

        line1, line2 = tle
        satellite = EarthSatellite(line1, line2, target_name, ts)
        minimum_elevation = float(target_config.get("min_elevation", 30))

        times, events = satellite.find_events(
            station_location,
            t0,
            t1,
            altitude_degrees=minimum_elevation,
        )

        for index in range(len(events) - 2):
            if not (
                events[index] == 0
                and events[index + 1] == 1
                and events[index + 2] == 2
            ):
                continue

            start_time = times[index]
            maximum_time = times[index + 1]
            end_time = times[index + 2]

            topocentric = (satellite - station_location).at(maximum_time)
            altitude, azimuth, _distance = topocentric.altaz()

            candidates.append(
                {
                    "name": target_name,
                    "start": start_time.utc_datetime(),
                    "maximum": maximum_time.utc_datetime(),
                    "end": end_time.utc_datetime(),
                    "max_elevation": round(altitude.degrees, 1),
                    "azimuth": round(azimuth.degrees, 1),
                    "frequency": target_config.get("frequency"),
                    "sample_rate": target_config.get("sample_rate"),
                    "pipeline": target_config.get("pipeline"),
                    "mode": target_config.get("mode"),
                    "decoder": target_config.get("decoder"),
                    "min_elevation": minimum_elevation,
                    "priority": target_config.get("priority", 1),
                    "mission_type": str(mission_type).upper(),
                    "target_group": str(target_group).lower(),
                }
            )

    candidates.sort(key=lambda item: item["start"])
    return candidates


def merge_pass_sources(*sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge independently calculated pass sources into one time-ordered queue."""
    merged = [item for source in sources for item in source]
    merged.sort(key=lambda item: item["start"])
    return merged


def get_weather_passes(hours_ahead: float = 48) -> list[dict[str, Any]]:
    """Return enabled WEATHER satellite passes."""
    return get_target_passes(
        get_enabled_satellites(),
        tle_file=DEFAULT_TLE_FILE,
        hours_ahead=hours_ahead,
        mission_type=WEATHER_MISSION_TYPE,
        target_group=WEATHER_TARGET_GROUP,
    )


def get_enabled_voice_targets() -> dict[str, dict[str, Any]]:
    """Return enabled voice targets from config/voice_targets.yaml."""
    if not VOICE_TARGETS_CONFIG.exists():
        return {}

    data = load_yaml(VOICE_TARGETS_CONFIG) or {}
    targets = data.get("voice_targets", {})
    if not isinstance(targets, Mapping):
        return {}

    return {
        str(name): dict(config)
        for name, config in targets.items()
        if isinstance(config, Mapping) and bool(config.get("enabled", False))
    }


def get_iss_passes(hours_ahead: float = 48) -> list[dict[str, Any]]:
    """Return configured ISS Voice passes without adding them to automation."""
    return get_target_passes(
        get_enabled_voice_targets(),
        tle_file=ISS_TLE_FILE,
        hours_ahead=hours_ahead,
        mission_type=VOICE_MISSION_TYPE,
        target_group=VOICE_TARGET_GROUP,
    )


def get_plannable_passes(hours_ahead: float = 48) -> list[dict[str, Any]]:
    """Return WEATHER and VOICE passes for future planner/UI integration.

    Existing automation deliberately continues to call ``get_passes()``, which
    remains WEATHER-only until receiver reservation and voice execution exist.
    """
    return merge_pass_sources(
        get_weather_passes(hours_ahead),
        get_iss_passes(hours_ahead),
    )


def get_passes(hours_ahead: float = 48) -> list[dict[str, Any]]:
    """Backward-compatible WEATHER pass API used by SDRCC v0.27.x callers."""
    return get_weather_passes(hours_ahead)


def get_next_pass(hours_ahead: float = 48) -> dict[str, Any] | None:
    passes = get_passes(hours_ahead)
    return passes[0] if passes else None


def _print_pass(pass_data: Mapping[str, Any]) -> None:
    duration = pass_data["end"] - pass_data["start"]
    minutes = int(duration.total_seconds() // 60)
    seconds = int(duration.total_seconds() % 60)

    print(pass_data["name"])
    print()
    print("Start      :", _fmt_local(pass_data["start"]), "lokale tijd")
    print("Maximum    :", _fmt_local(pass_data["maximum"]), "lokale tijd")
    print("End        :", _fmt_local(pass_data["end"]), "lokale tijd")
    print("Duration   :", f"{minutes}m {seconds}s")
    print("Max Elev   :", f"{pass_data['max_elevation']}°")
    print("Azimuth    :", f"{pass_data['azimuth']}°")

    frequency = pass_data.get("frequency")
    print("Frequency  :", f"{frequency / 1e6:.3f} MHz" if frequency else "-")
    print("Mode       :", pass_data.get("mode") or "-")
    print("Decoder    :", pass_data.get("decoder") or "-")


def print_next_pass() -> None:
    next_pass = get_next_pass()

    print("Next pass")
    print("-----------------------------")

    if next_pass is None:
        print("Geen geschikte passage gevonden.")
        return

    _print_pass(next_pass)


def print_schedule(hours_ahead: float = 24) -> None:
    upcoming = get_passes(hours_ahead)

    print(f"Schedule next {hours_ahead} hours")
    print("-----------------------------")

    if not upcoming:
        print("Geen geschikte passages gevonden.")
        return

    for item in upcoming:
        frequency = item.get("frequency")
        frequency_label = f"{frequency / 1e6:.3f} MHz" if frequency else "-"
        print(
            f"{_fmt_local(item['start'])} | "
            f"{item['name']} | "
            f"max {item['max_elevation']}° | "
            f"{frequency_label}"
        )
