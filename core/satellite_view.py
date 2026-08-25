#!/usr/bin/env python3
"""Read-only orbital geometry for the Radio View satellite map.

Mission planning remains owned by ``mission_planner`` and ``mission_queue``.
This module only projects the validated TLE inventory at the current time for
presentation in the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import asin, atan2, cos, degrees, pi, radians, sin
from threading import RLock
from typing import Any

from core import tle
from core.config import load_station


AUTHORITY = "read_only_tle_observer"
CACHE_SECONDS = 20
TRACK_PAST_MINUTES = 45
TRACK_FUTURE_MINUTES = 75
TRACK_STEP_MINUTES = 2
EARTH_RADIUS_KM = 6371.0

_CACHE_LOCK = RLock()
_CACHE: dict[str, Any] = {"epoch": 0.0, "snapshot": None}


def _normalize_longitude(value: float) -> float:
    return ((float(value) + 180.0) % 360.0) - 180.0


def _split_dateline(points: list[list[float]]) -> list[list[list[float]]]:
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    previous_longitude: float | None = None
    for longitude, latitude in points:
        longitude = _normalize_longitude(longitude)
        point = [round(longitude, 4), round(float(latitude), 4)]
        if previous_longitude is not None and abs(longitude - previous_longitude) > 180.0:
            if len(current) > 1:
                segments.append(current)
            current = []
        current.append(point)
        previous_longitude = longitude
    if len(current) > 1:
        segments.append(current)
    return segments


def _footprint_segments(
    latitude_deg: float,
    longitude_deg: float,
    altitude_km: float,
) -> tuple[list[list[list[float]]], float]:
    altitude_km = max(0.0, float(altitude_km))
    angular_radius = 0.0
    if altitude_km > 0.0:
        angular_radius = atan2(
            (altitude_km * (2.0 * EARTH_RADIUS_KM + altitude_km)) ** 0.5,
            EARTH_RADIUS_KM,
        )
    latitude = radians(float(latitude_deg))
    longitude = radians(float(longitude_deg))
    points: list[list[float]] = []
    for bearing_index in range(73):
        bearing = 2.0 * pi * bearing_index / 72.0
        target_latitude = asin(
            sin(latitude) * cos(angular_radius)
            + cos(latitude) * sin(angular_radius) * cos(bearing)
        )
        target_longitude = longitude + atan2(
            sin(bearing) * sin(angular_radius) * cos(latitude),
            cos(angular_radius) - sin(latitude) * sin(target_latitude),
        )
        points.append([
            _normalize_longitude(degrees(target_longitude)),
            degrees(target_latitude),
        ])
    return _split_dateline(points), EARTH_RADIUS_KM * angular_radius


def _track_points(satellite, timescale, wgs84, moments: list[datetime]) -> list[list[float]]:
    """Project moments efficiently, with a compatibility fallback for Skyfield."""
    try:
        positions = satellite.at(timescale.from_datetimes(moments))
        latitudes, longitudes = wgs84.latlon_of(positions)
        return [
            [float(longitude), float(latitude)]
            for longitude, latitude in zip(longitudes.degrees, latitudes.degrees)
        ]
    except (AttributeError, TypeError):
        points = []
        for moment in moments:
            latitude, longitude = wgs84.latlon_of(
                satellite.at(timescale.from_datetime(moment))
            )
            points.append([
                float(longitude.degrees),
                float(latitude.degrees),
            ])
        return points


def _load_blocks() -> tuple[list[dict[str, Any]], list[str]]:
    blocks: list[dict[str, Any]] = []
    errors: list[str] = []
    for path, expected in (
        (tle.TLE_FILE, tle.REQUIRED_WEATHER),
        (tle.ISS_TLE_FILE, tle.REQUIRED_ISS),
    ):
        try:
            blocks.extend(tle.load_file(path, expected_catalogs=expected).values())
        except (FileNotFoundError, OSError, ValueError) as error:
            errors.append(str(error))
    return blocks, errors


def _satellite_key(catalog_number: int) -> str:
    return {
        25544: "iss",
        57166: "meteor_m2_3",
        59051: "meteor_m2_4",
    }.get(int(catalog_number), f"norad_{int(catalog_number)}")


def _build_snapshot(now: datetime) -> dict[str, Any]:
    from skyfield.api import EarthSatellite, load, wgs84

    station_root = load_station() or {}
    station_config = station_root.get("station", {})
    station_latitude = float(station_config["latitude"])
    station_longitude = float(station_config["longitude"])
    station_altitude_m = float(station_config.get("altitude_m", 0.0))
    station = wgs84.latlon(
        station_latitude,
        station_longitude,
        elevation_m=station_altitude_m,
    )
    timescale = load.timescale()
    current_time = timescale.from_datetime(now)
    blocks, errors = _load_blocks()
    satellites = []

    past_offsets = list(range(-TRACK_PAST_MINUTES, 1, TRACK_STEP_MINUTES))
    if not past_offsets or past_offsets[-1] != 0:
        past_offsets.append(0)
    future_offsets = list(range(0, TRACK_FUTURE_MINUTES + 1, TRACK_STEP_MINUTES))
    if future_offsets[-1] != TRACK_FUTURE_MINUTES:
        future_offsets.append(TRACK_FUTURE_MINUTES)

    for block in blocks:
        satellite = EarthSatellite(
            block["line1"],
            block["line2"],
            block["name"],
            timescale,
        )
        geocentric = satellite.at(current_time)
        latitude, longitude = wgs84.latlon_of(geocentric)
        height = wgs84.height_of(geocentric)
        topocentric = (satellite - station).at(current_time)
        elevation, azimuth, distance = topocentric.altaz()
        altitude_km = float(height.km)

        past_moments = [now + timedelta(minutes=value) for value in past_offsets]
        future_moments = [now + timedelta(minutes=value) for value in future_offsets]
        past_track = _split_dateline(
            _track_points(satellite, timescale, wgs84, past_moments)
        )
        future_track = _split_dateline(
            _track_points(satellite, timescale, wgs84, future_moments)
        )
        footprint, footprint_radius_km = _footprint_segments(
            float(latitude.degrees),
            float(longitude.degrees),
            altitude_km,
        )
        satellites.append({
            "key": _satellite_key(int(block["catalog_number"])),
            "name": block["name"],
            "norad_id": int(block["catalog_number"]),
            "position": {
                "latitude": round(float(latitude.degrees), 4),
                "longitude": round(float(longitude.degrees), 4),
                "altitude_km": round(altitude_km, 1),
            },
            "observer": {
                "elevation_deg": round(float(elevation.degrees), 1),
                "azimuth_deg": round(float(azimuth.degrees), 1),
                "range_km": round(float(distance.km), 1),
                "above_horizon": float(elevation.degrees) >= 0.0,
            },
            "ground_track": {
                "past": past_track,
                "future": future_track,
                "past_minutes": TRACK_PAST_MINUTES,
                "future_minutes": TRACK_FUTURE_MINUTES,
            },
            "footprint": {
                "segments": footprint,
                "radius_km": round(footprint_radius_km),
            },
            "tle": {
                "epoch": block["epoch_iso"],
                "sha256": block["sha256"],
            },
        })

    satellites.sort(key=lambda item: (item["key"] != "iss", item["name"]))
    inventory = tle.get_status()
    return {
        "ok": bool(satellites),
        "authority": AUTHORITY,
        "projection": "equirectangular",
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_epoch": int(now.timestamp()),
        "station": {
            "name": str(station_config.get("name") or "SDRCC"),
            "location": str(station_config.get("location") or "Home"),
            "latitude": station_latitude,
            "longitude": station_longitude,
            "altitude_m": station_altitude_m,
        },
        "tle": {
            "source": inventory.get("source"),
            "state": inventory.get("state"),
            "valid": bool(inventory.get("valid")),
            "stale": bool(inventory.get("stale")),
        },
        "satellites": satellites,
        "errors": errors,
    }



def invalidate_cache() -> None:
    """Discard observer-only orbital presentation data after station changes."""
    with _CACHE_LOCK:
        _CACHE["epoch"] = 0.0
        _CACHE["snapshot"] = None


def get_snapshot(*, now: datetime | None = None, force: bool = False) -> dict[str, Any]:
    """Return a short-lived cached presentation snapshot of all required TLEs."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    epoch = current.timestamp()
    with _CACHE_LOCK:
        cached = _CACHE.get("snapshot")
        if not force and cached is not None and epoch - float(_CACHE.get("epoch", 0.0)) < CACHE_SECONDS:
            return cached
        snapshot = _build_snapshot(current)
        _CACHE["epoch"] = epoch
        _CACHE["snapshot"] = snapshot
        return snapshot
