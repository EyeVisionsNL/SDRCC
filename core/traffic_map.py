"""Read-only live traffic snapshot for the experimental combined 2D/3D map.

Reuses existing receiver monitor sources; does not open SDR hardware, start
services, claim receiver roles, or change AIS/ADS-B decoder settings.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import time
from typing import Any

from core import config, receiver_monitor

MAX_TARGETS = 2000
AIS_MAX_AGE = 180.0
ADSB_MAX_AGE = 30.0
ADSB_FILE_MAX_AGE = 30.0
DEFAULT_CENTER = [4.35, 51.91]  # Rotterdam/Rijnmond prototype only


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _position(item: dict, latitude: tuple[str, ...], longitude: tuple[str, ...]):
    lat = next((n for key in latitude if (n := _num(item.get(key))) is not None), None)
    lon = next((n for key in longitude if (n := _num(item.get(key))) is not None), None)
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    return round(lon, 6), round(lat, 6)


def _label(item: dict, names: tuple[str, ...], limit: int = 72) -> str:
    for key in names:
        label = str(item.get(key) or "").strip()
        if label:
            return label[:limit]
    return ""


def _direction(item: dict, names: tuple[str, ...]) -> float | None:
    value = next((n for key in names if (n := _num(item.get(key))) is not None), None)
    return round(value, 1) if value is not None and 0 <= value < 360 else None


def _fresh_adsb_file(source: str | None) -> bool:
    if not source:
        return False
    try:
        return 0 <= time.time() - Path(source).stat().st_mtime <= ADSB_FILE_MAX_AGE
    except OSError:
        return False


def vessels(payload: Any) -> list[dict]:
    """Only identified vessels with plausible recent AIS positions."""
    ships = receiver_monitor._extract_list(payload, ("ships", "vessels", "targets", "data"))
    selected = []
    seen = set()
    for item in ships:
        mmsi = str(item.get("mmsi") or "").strip()
        if not re.fullmatch(r"[0-9]{9}", mmsi) or mmsi in seen:
            continue
        pos = _position(item, ("lat", "latitude"), ("lon", "longitude"))
        if pos is None:
            continue
        validated = _num(item.get("validated"))
        if validated is not None and validated != 1:
            continue
        age = next((v for k in ("last_signal", "last_signal_seconds", "age")
                    if (v := _num(item.get(k))) is not None), None)
        if age is not None and not 0 <= age <= AIS_MAX_AGE:
            continue
        seen.add(mmsi)
        speed = next((v for k in ("speed", "sog") if (v := _num(item.get(k))) is not None), None)
        if speed is not None and not 0 <= speed < 102.3:
            speed = None
        selected.append({
            "type": "ais", "id": mmsi, "name": _label(item, ("shipname", "name"), 70) or mmsi,
            "callsign": _label(item, ("callsign",), 24), "lon": pos[0], "lat": pos[1],
            "course": _direction(item, ("cog", "course", "heading")),
            "speed_knots": round(speed, 1) if speed is not None else None,
            "age_seconds": round(age, 1) if age is not None else None,
        })
        if len(selected) >= MAX_TARGETS:
            break
    return selected


def aircraft(payload: Any) -> list[dict]:
    """Readsb observations younger than 30 seconds, with valid positions."""
    planes = receiver_monitor._extract_list(payload, ("aircraft",))
    selected = []
    seen = set()
    for item in planes:
        ident = str(item.get("hex") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{6}", ident) or ident in seen:
            continue
        pos = _position(item, ("lat",), ("lon",))
        age = _num(item.get("seen_pos"))
        if age is None:
            age = _num(item.get("seen"))
        if pos is None or age is None or not 0 <= age <= ADSB_MAX_AGE:
            continue
        seen.add(ident)
        altitude = next((n for k in ("alt_geom", "alt_baro")
                         if (n := _num(item.get(k))) is not None), None)
        speed = _num(item.get("gs"))
        selected.append({
            "type": "adsb", "id": ident, "name": _label(item, ("flight",), 20) or ident.upper(),
            "lon": pos[0], "lat": pos[1],
            "course": _direction(item, ("track",)),
            "speed_knots": round(speed, 1) if speed is not None and 0 <= speed <= 2000 else None,
            "altitude_ft": round(altitude) if altitude is not None and -2000 <= altitude <= 70000 else None,
            "age_seconds": round(age, 1),
        })
        if len(selected) >= MAX_TARGETS:
            break
    return selected


def snapshot() -> dict:
    """One bounded, read-only snapshot with explicit per-source availability."""
    center = list(DEFAULT_CENTER)
    try:
        home = config.get_home_position()
        if home.get("configured"):
            pos = _position(home, ("latitude",), ("longitude",))
            if pos is not None:
                center = list(pos)
    except (OSError, ValueError, TypeError, KeyError):
        pass

    ais_payload, _ = receiver_monitor._read_ais_ships()
    adsb_payload, adsb_source = receiver_monitor._read_json_file(receiver_monitor.READSB_AIRCRAFT_FILES)
    adsb_live = isinstance(adsb_payload, dict) and _fresh_adsb_file(adsb_source)
    ships = vessels(ais_payload) if ais_payload is not None else []
    planes = aircraft(adsb_payload) if adsb_live else []
    return {
        "ok": True, "read_only": True, "center": center,
        "ais": {"available": ais_payload is not None, "count": len(ships), "targets": ships},
        "adsb": {"available": adsb_live, "count": len(planes), "targets": planes},
        "refresh_seconds": 10,
    }
