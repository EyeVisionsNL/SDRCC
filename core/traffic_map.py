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
# AIS-Catcher retains moored vessel positions beyond the live correlation window.
# Keep bounded historical positions on the MAP ONLY; Emergency Monitor/ATIS
# still enforce their existing strict freshness and validation requirements.
AIS_LIVE_MAX_AGE = receiver_monitor.AIS_VESSEL_MAX_AGE_SECONDS
AIS_DISPLAY_MAX_AGE = 24 * 60 * 60  # Last reported position, up to one day old.
# readsb/tar1090 can show an aircraft for up to a minute after its last position.
ADSB_MAX_AGE = 60.0
ADSB_FILE_MAX_AGE = 30.0
ADSB_HTTP_URLS = ("http://127.0.0.1/tar1090/data/aircraft.json",)
DEFAULT_CENTER = [4.35, 51.91]  # Rotterdam/Rijnmond prototype only
# These are conservative display hints only; do not alter AIS/ATIS alerts.
_WTG_NAME_RE = re.compile(r"^(?:WTG|WIND[ -]?TURBINE)(?=$|[\s#._/-]|\d)", re.I)
_PLATFORM_CODE_RE = re.compile(r"^(?:P|L|K|Q)[ -]?\d{1,3}(?:[-/][A-Z0-9]+)?$", re.I)
_PLATFORM_NAME_RE = re.compile(
    r"^(?:(?:OFFSHORE[ -]+)?(?:OIL[ -]+|GAS[ -]+)?PLATFORM|"
    r"(?:DRILLING[ -]+)?RIG)(?:\b|[- #])", re.I,
)
# Shiptype 52=tug; 31/32=towing; navstatus 11/12=towing/pushing.
_TUG_NAME_RE = re.compile(
    r"(?:^|[\s._/-])(?:TUG|TUGBOAT|SLEPER|SLEEPBOOT)(?:$|[\s._/-]|\d)"
    r"|^MULTRATUG(?:$|[\s._/-]|\d)|^SMIT(?:$|[\s._/-])", re.I,
)
_TUG_STATUS_RE = re.compile(r"\b(?:TUGGING|TOWING|PUSHING|TOWED|PUSHED)\b", re.I)
TRACK_WINDOW_SECONDS = 3600
TRACK_POINT_LIMIT = 300
TRACK_URL_PREFIXES = ("http://127.0.0.1:8119/api/path.geojson?",
                      "http://localhost:8119/api/path.geojson?")


def display_profile(name: str, shiptype: int | None, shipclass: int | None,
                    nav_status: Any = None) -> str:
    """Illustrative rendering profile; never changes received AIS or alerts."""
    label = str(name or "").strip()
    if _WTG_NAME_RE.search(label):
        return "offshore_wtg"
    if _PLATFORM_CODE_RE.fullmatch(label) or _PLATFORM_NAME_RE.match(label):
        return "offshore_platform"
    status = str(nav_status or "").strip()
    if (shiptype in (31, 32, 52) or _TUG_NAME_RE.search(label)
            or status in ("11", "12") or _TUG_STATUS_RE.search(status)):
        return "tug"
    if (shiptype is not None and 80 <= shiptype <= 89) or shipclass == 6:
        return "tanker"
    if (shiptype is not None and 70 <= shiptype <= 79) or shipclass == 2:
        return "cargo"
    return "vessel"



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
    """Identified AIS-Catcher positions, including clearly marked old fixes."""
    ships = receiver_monitor._extract_list(payload, ("ships", "vessels", "targets", "data"))
    selected = []
    seen = set()
    for item in ships:
        mmsi = str(item.get("mmsi") or "").strip().removesuffix(".0")
        if not re.fullmatch(r"[0-9]{9}", mmsi) or mmsi in seen:
            continue
        pos = _position(item, ("lat", "latitude"), ("lon", "longitude"))
        if pos is None:
            continue
        validated = _num(item.get("validated"))
        # Map display is not an ATIS/alert match: include uncertain positions
        # but label them clearly, never silently call them validated.
        validation_state = ("verified" if validated == 1 else
                            "unverified" if validated is not None else "unknown")
        age = next((v for k in ("last_signal", "last_signal_seconds", "age")
                    if (v := _num(item.get(k))) is not None), None)
        if age is not None and not 0 <= age <= AIS_DISPLAY_MAX_AGE:
            continue
        position_stale = age is not None and age > AIS_LIVE_MAX_AGE
        seen.add(mmsi)
        speed = next((v for k in ("speed", "sog") if (v := _num(item.get(k))) is not None), None)
        if speed is not None and not 0 <= speed < 102.3:
            speed = None
        course = _direction(item, ("cog", "course", "heading"))
        # AIS-Catcher ships.json includes type and offsets from the antenna.
        # Render real-size hulls only with all four plausible dimensions.
        # Unlike a course over ground, true heading can position a moored hull.
        raw_dims = [_num(item.get(key)) for key in
                    ("to_bow", "to_stern", "to_port", "to_starboard")]
        to_bow = to_stern = to_port = to_starboard = None
        length = _num(item.get("length"))
        if all(value is not None for value in raw_dims):
            bow, stern, port, starboard = raw_dims
            if (bow > 0 and stern >= 0 and port >= 0 and starboard >= 0
                    and 5 <= bow + stern <= 450
                    and 2 <= port + starboard <= 90):
                to_bow, to_stern, to_port, to_starboard = (
                    bow, stern, port, starboard)
                length = bow + stern
        if length is None or not 5 <= length <= 450:
            length = None
        heading = _direction(item, ("heading",))
        # A 511/unknown AIS heading must not be treated as north.
        hull_heading = heading if heading is not None else (
            course if speed is not None and speed > 0.5 else None)
        has_hull = to_bow is not None and hull_heading is not None
        shipclass = _num(item.get("shipclass"))
        shiptype = _num(item.get("shiptype"))
        beam = to_port + to_starboard if to_port is not None else _num(item.get("width"))
        if beam is not None and not 0 < beam <= 90:
            beam = None
        draught = _num(item.get("draught"))
        if draught is not None and not 0 <= draught <= 25:
            draught = None
        name = _label(item, ("shipname", "name"), 70) or mmsi
        normalized_type = int(shiptype) if shiptype is not None and 0 <= shiptype <= 9999 else None
        normalized_class = int(shipclass) if shipclass is not None and 0 <= shipclass <= 13 else None
        nav_status = _label(item, ("status","nav_status","navigation_status"), 40)
        profile = display_profile(name, normalized_type, normalized_class, nav_status)
        if profile.startswith("offshore_"):
            has_hull = False
        selected.append({
            "type": "ais", "id": mmsi, "name": name,
            "render_profile": profile,
            "is_offshore_structure": profile.startswith("offshore_"),
            "callsign": _label(item, ("callsign",), 24), "lon": pos[0], "lat": pos[1],
            "validation_state": validation_state,
            "position_stale": position_stale,
            "course": course,
            "heading": heading,
            "hull_heading": hull_heading if has_hull else None,
            "to_bow": to_bow, "to_stern": to_stern,
            "to_port": to_port, "to_starboard": to_starboard,
            "hull_available": has_hull,
            "length_m": round(length, 1) if length is not None else None,
            "shipclass": normalized_class,
            "shiptype": normalized_type,
            "imo": _label(item, ("imo",), 15),
            "eni": _label(item, ("eni",), 15),
            "destination": _label(item, ("destination",), 90),
            "country": _label(item, ("country",), 45),
            "nav_status": nav_status,
            "beam_m": round(beam, 1) if beam is not None else None,
            "draught_m": round(draught, 1) if draught is not None else None,
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
        # readsb prefixes non-ICAO addresses with ~ (e.g. TIS-B).
        if not re.fullmatch(r"~?[0-9a-f]{6}", ident) or ident in seen:
            continue
        position_data = item
        pos = _position(item, ("lat",), ("lon",))
        # tar1090 may retain the last known position in lastPosition.
        if pos is None and isinstance(item.get("lastPosition"), dict):
            position_data = item["lastPosition"]
            pos = _position(position_data, ("lat",), ("lon",))
        age = _num(position_data.get("seen_pos"))
        if age is None:
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
            "registration": _label(item, ("r", "registration"), 20),
            "aircraft_type": _label(item, ("t", "type"), 20),
            "description": _label(item, ("desc",), 80),
            "operator": _label(item, ("ownOp", "operator"), 80),
            "squawk": _label(item, ("squawk",), 6),
            "category": _label(item, ("category",), 12),
            "baro_rate": round(rate) if (rate := _num(item.get("baro_rate"))) is not None and -10000 <= rate <= 10000 else None,
            "speed_knots": round(speed, 1) if speed is not None and 0 <= speed <= 2000 else None,
            "altitude_ft": round(altitude) if altitude is not None and -2000 <= altitude <= 70000 else None,
            "age_seconds": round(age, 1),
        })
        if len(selected) >= MAX_TARGETS:
            break
    return selected


def track_snapshot(mmsi: str) -> dict:
    """Read a bounded native AIS-Catcher vessel track; no fabricated history.

    AIS-Catcher already collects tracks independently of the Map Lab viewer.
    Never modifies its settings, services, receivers or hardware.
    """
    ident = str(mmsi or "")
    empty = {"type": "FeatureCollection", "features": []}
    if not re.fullmatch(r"[0-9]{9}", ident):
        return {"ok": False, "available": False, "mmsi": ident[:20],
                "point_count": 0, "geojson": empty}
    urls = tuple(prefix + ident for prefix in TRACK_URL_PREFIXES)
    payload, _ = receiver_monitor._read_json_url(urls, timeout=0.75)
    if not isinstance(payload, dict) or payload.get("type") != "Feature":
        return {"ok": True, "available": False, "mmsi": ident,
                "point_count": 0, "geojson": empty}
    geometry, props = payload.get("geometry"), payload.get("properties")
    if (not isinstance(geometry, dict) or geometry.get("type") != "LineString"
            or not isinstance(props, dict) or str(props.get("mmsi")) != ident):
        return {"ok": True, "available": False, "mmsi": ident,
                "point_count": 0, "geojson": empty}
    coords, times = geometry.get("coordinates"), props.get("timestamps_start")
    if not isinstance(coords, list) or not isinstance(times, list):
        return {"ok": True, "available": False, "mmsi": ident,
                "point_count": 0, "geojson": empty}
    now = time.time()
    samples = []
    for point, ts in zip(coords[:20000], times[:20000]):
        if not isinstance(point, list) or len(point) < 2:
            continue
        lon, lat, recorded = _num(point[0]), _num(point[1]), _num(ts)
        if (lon is None or lat is None or recorded is None
                or not -180 <= lon <= 180 or not -90 <= lat <= 90
                or not now - TRACK_WINDOW_SECONDS <= recorded <= now + 60):
            continue
        samples.append((recorded, [round(lon, 6), round(lat, 6)]))
    samples = sorted(samples, key=lambda row: row[0])[-TRACK_POINT_LIMIT:]
    features, segment, previous = [], [], None
    def flush():
        if len(segment) >= 2:
            features.append({"type": "Feature",
                             "geometry": {"type": "LineString", "coordinates": segment[:]},
                             "properties": {"mmsi": ident}})
    for ts, point in samples:
        if previous:
            last_ts, last_point = previous
            if (ts - last_ts > 900 or abs(point[0]-last_point[0]) > 0.3
                    or abs(point[1]-last_point[1]) > 0.3):
                flush()
                segment = []
            if point == last_point:
                previous = (ts, point)
                continue
        segment.append(point)
        previous = (ts, point)
    flush()
    return {"ok": True, "available": True, "mmsi": ident,
            "point_count": sum(len(f["geometry"]["coordinates"]) for f in features),
            "geojson": {"type": "FeatureCollection", "features": features}}


def snapshot() -> dict:
    """One bounded, read-only snapshot with explicit per-source availability."""
    center = list(DEFAULT_CENTER)
    station = None
    try:
        home = config.get_home_position()
        if home.get("configured"):
            pos = _position(home, ("latitude",), ("longitude",))
            if pos is not None:
                center = list(pos)
                name = _label(home, ("name",), 64) or "My station"
                altitude = _num(home.get("altitude_m"))
                station = {
                    "name": name, "lon": pos[0], "lat": pos[1],
                    "altitude_m": round(altitude, 1) if altitude is not None else None,
                    "source": "SDRCC Home Position",
                }
    except (OSError, ValueError, TypeError, KeyError):
        pass

    ais_payload, _ = receiver_monitor._read_ais_ships()
    ais_rows = receiver_monitor._extract_list(ais_payload, ("ships", "vessels", "targets", "data"))
    ships = vessels(ais_payload) if ais_payload is not None else []

    adsb_payload, adsb_source = receiver_monitor._read_json_file(receiver_monitor.READSB_AIRCRAFT_FILES)
    adsb_live = isinstance(adsb_payload, dict) and _fresh_adsb_file(adsb_source)
    planes = aircraft(adsb_payload) if adsb_live else []
    # tar1090 can serve current readsb data while its disk file is absent, stale,
    # or lacks a usable position. This is a loopback-only READ; no service changes.
    if not planes:
        http_payload, http_source = receiver_monitor._read_json_url(ADSB_HTTP_URLS)
        generated_at = _num(http_payload.get("now")) if isinstance(http_payload, dict) else None
        http_live = (generated_at is not None
                     and 0 <= time.time() - generated_at <= ADSB_FILE_MAX_AGE)
        if http_live:
            http_planes = aircraft(http_payload)
            if http_planes or not adsb_live:
                adsb_payload, adsb_source = http_payload, http_source
                adsb_live, planes = True, http_planes
    adsb_rows = receiver_monitor._extract_list(adsb_payload, ("aircraft",)) if adsb_live else []
    return {
        "ok": True, "read_only": True, "center": center, "station": station,
        "ais": {"available": ais_payload is not None, "count": len(ships),
                "source_count": len(ais_rows),
                "unverified_count": sum(ship["validation_state"] == "unverified" for ship in ships),
                "targets": ships},
        "adsb": {"available": adsb_live, "count": len(planes),
                 "source_count": len(adsb_rows), "source": adsb_source if adsb_live else None,
                 "targets": planes},
        "refresh_seconds": 10,
    }
