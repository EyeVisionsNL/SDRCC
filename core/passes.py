#!/usr/bin/env python3
"""Shared Skyfield pass-window prediction for every satellite mission."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from skyfield.api import EarthSatellite, load, wgs84

from core import tle, weather_planning
from core.config import get_enabled_satellites, load_station

TLE_FILE = Path(__file__).resolve().parent.parent / "data" / "tle" / "weather.tle"
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")


def _load_station_location():
    cfg = load_station()
    station = cfg.get("station", {})
    return wgs84.latlon(
        float(station.get("latitude")),
        float(station.get("longitude")),
        elevation_m=float(station.get("altitude_m", 0)),
    )


def _load_tle_blocks() -> dict[str, tuple[str, str]]:
    """Backward-compatible name lookup backed by catalog validation."""
    try:
        blocks = tle.load_file(TLE_FILE, expected_catalogs=tle.REQUIRED_WEATHER)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return {
        block["name"]: (block["line1"], block["line2"])
        for block in blocks.values()
    }


def _fmt_local(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _event_triplets(satellite, station, t0, t1, altitude_degrees: float):
    times, events = satellite.find_events(
        station,
        t0,
        t1,
        altitude_degrees=float(altitude_degrees),
    )
    values = [int(value) for value in events]
    triplets = []
    for index in range(len(values) - 2):
        if values[index:index + 3] == [0, 1, 2]:
            triplets.append((times[index], times[index + 1], times[index + 2]))
    return triplets


def predict_satellite_passes(
    *,
    name: str,
    line1: str,
    line2: str,
    station,
    planning: dict[str, Any],
    hours_ahead: int = 48,
    start_time: datetime | None = None,
    timescale=None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return windows bounded by independent rising and falling elevations."""
    ts = timescale or load.timescale()
    now = start_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    future = now + timedelta(hours=max(1, min(int(hours_ahead), 168)))
    begin_elevation = float(planning["begin_elevation"])
    close_elevation = float(planning["close_elevation"])
    satellite = EarthSatellite(line1, line2, str(name), ts)
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(future)

    rising_windows = _event_triplets(satellite, station, t0, t1, begin_elevation)
    falling_windows = (
        rising_windows
        if close_elevation == begin_elevation
        else _event_triplets(satellite, station, t0, t1, close_elevation)
    )

    candidates: list[dict[str, Any]] = []
    used_falling: set[int] = set()
    for rising_start, rising_maximum, _rising_end in rising_windows:
        maximum_epoch = rising_maximum.utc_datetime().timestamp()
        matches = [
            (abs(maximum_epoch - candidate[1].utc_datetime().timestamp()), index, candidate)
            for index, candidate in enumerate(falling_windows)
            if index not in used_falling
        ]
        if not matches:
            continue
        difference, match_index, (_falling_start, falling_maximum, falling_end) = min(matches)
        if difference > 120.0:
            continue
        used_falling.add(match_index)
        maximum_time = rising_maximum if difference <= 1.0 else falling_maximum
        start_dt = rising_start.utc_datetime()
        maximum_dt = maximum_time.utc_datetime()
        end_dt = falling_end.utc_datetime()
        if end_dt <= start_dt:
            continue
        topocentric = (satellite - station).at(maximum_time)
        altitude, azimuth, _distance = topocentric.altaz()
        candidates.append({
            "name": str(name),
            "start": start_dt,
            "maximum": maximum_dt,
            "end": end_dt,
            "max_elevation": round(float(altitude.degrees), 1),
            "azimuth": round(float(azimuth.degrees), 1),
            "minimum_peak_elevation": float(planning["minimum_peak_elevation"]),
            "begin_elevation": begin_elevation,
            "close_elevation": close_elevation,
            "min_elevation": float(planning["minimum_peak_elevation"]),
            **dict(metadata or {}),
        })
    candidates.sort(key=lambda item: item["start"])
    return candidates


def get_passes(hours_ahead: int = 48) -> list[dict[str, Any]]:
    station_location = _load_station_location()
    enabled = get_enabled_satellites()
    try:
        blocks = tle.load_file(TLE_FILE, expected_catalogs=tle.REQUIRED_WEATHER)
    except (FileNotFoundError, ValueError, OSError):
        return []
    ts = load.timescale()
    candidates: list[dict[str, Any]] = []

    catalog_by_name = {name: catalog for catalog, name in tle.REQUIRED_WEATHER.items()}
    for sat_name, sat_cfg in enabled.items():
        catalog = catalog_by_name.get(str(sat_name))
        if catalog is None or catalog not in blocks:
            continue
        block = blocks[catalog]
        planning = weather_planning.get_profile(str(sat_name))
        metadata = {
            "frequency": sat_cfg.get("frequency"),
            "sample_rate": sat_cfg.get("sample_rate"),
            "pipeline": sat_cfg.get("pipeline"),
            "mode": sat_cfg.get("mode"),
            "decoder": sat_cfg.get("decoder"),
            "planning_profile_id": planning["profile_id"],
            "norad_id": catalog,
            "tle_source": tle.SOURCE_NAME,
            "tle_epoch": block["epoch_iso"],
            "tle_sha256": block["sha256"],
        }
        candidates.extend(predict_satellite_passes(
            name=str(sat_name),
            line1=block["line1"],
            line2=block["line2"],
            station=station_location,
            planning=planning,
            hours_ahead=hours_ahead,
            timescale=ts,
            metadata=metadata,
        ))

    candidates.sort(key=lambda item: item["start"])
    return candidates


def get_next_pass(hours_ahead: int = 48):
    upcoming = get_passes(hours_ahead)
    return upcoming[0] if upcoming else None


def _print_pass(pass_data: dict[str, Any]) -> None:
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
    print("Window     :", f"{pass_data['begin_elevation']}° → {pass_data['close_elevation']}°")
    print("Azimuth    :", f"{pass_data['azimuth']}°")
    print("Frequency  :", f"{pass_data['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", pass_data["mode"])
    print("Decoder    :", pass_data["decoder"])


def print_next_pass() -> None:
    next_pass = get_next_pass()
    print("Next pass")
    print("-----------------------------")
    if next_pass is None:
        print("Geen geschikte passage gevonden.")
        return
    _print_pass(next_pass)


def print_schedule(hours_ahead: int = 24) -> None:
    upcoming = get_passes(hours_ahead)
    print(f"Schedule next {hours_ahead} hours")
    print("-----------------------------")
    if not upcoming:
        print("Geen geschikte passages gevonden.")
        return
    for item in upcoming:
        print(
            f"{_fmt_local(item['start'])} | {item['name']} | "
            f"max {item['max_elevation']}° | {item['frequency'] / 1e6:.3f} MHz"
        )
