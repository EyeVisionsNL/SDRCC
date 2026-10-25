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
# An AIS Aid-to-Navigation can be named "Q13A-A PLATFORM", rather than
# beginning with PLATFORM. Only match this suffix on fixed/AtoN evidence.
_PLATFORM_AID_WORD_RE = re.compile(r"\bPLATFORM\b", re.I)
_RPA_NAME_RE = re.compile(r"^RPA(?:[ -]?(\d{1,2})|[ -]+ZERO)(?:$|[\s./-])", re.I)
# Confirmed Port of Rotterdam craft. The original RPA12 profile/model is reused.
# Named RPA fleet members (including RPA 8 and RPA ZERO) also match above.
# IMPORTANT: 246537000 was formerly police vessel P5; a stale P5 name must
# not override the police-boat profile merely because its MMSI is on this list.
_RPA_FLEET_MMSI = {
    "246537000": 6,   # RPA 6, ex-P5
    "244050426": 10,  # RPA 10
    "244100055": 11,  # RPA 11
    "244050469": 12,  # RPA 12
    "244757000": 16,  # RPA 16
}
# Verified approximate overall dimensions (metres), NOT AIS antenna offsets.
# AIS dimensions always take precedence. Only use these values with a matching
# MMSI and matching RPA name, plus a usable AIS heading/course.
_RPA_PUBLISHED_DIMENSIONS = {
    "246537000": (26.0, 6.0),
    "244050426": (29.0, 8.0),
    "244100055": (28.0, 8.0),
    "244050469": (28.78, 8.20),
    "244757000": (31.33, 8.22),
}
_POLICE_NAME_RE = re.compile(r"\b(?:WATERPOLITIE|POLITIE|POLICE)\b", re.I)
_POLICE_P_NUMBER_RE = re.compile(r"^P[ -]?\d{1,2}(?:$|[ -])", re.I)
# MSTX 12, MSTX12, MSTX-13 are local high-speed water taxis.
_WATERTAXI_NAME_RE = re.compile(r"^MSTX(?=$|[\s._/-]|\d)", re.I)
# Koninklijke Roeiers Vereeniging Eendracht: KRVE 65 / K.R.V.E. 62.
# Their HSC craft differ from MSTX water taxis in cabin and fender shape.
_KRVE_NAME_RE = re.compile(r"^K\.?R\.?V\.?E\.?(?=$|[\s._/-]|\d)", re.I)
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
# Native AIS-Catcher collection endpoint, not an artificial browser-local trail.
TRACK_ALL_URLS = ("http://127.0.0.1:8119/api/allpath.geojson",
                  "http://localhost:8119/api/allpath.geojson")
TRACK_ALL_MAX_SHIPS = 1200
TRACK_ALL_POINT_LIMIT = 150
TRACK_ALL_TOTAL_POINTS = 45000


def display_profile(name: str, shiptype: int | None, shipclass: int | None,
                    nav_status: Any = None, *, mmsi: str = "",
                    callsign: str = "", speed_knots: float | None = None,
                    destination: str = "") -> str:
    """Conservative AIS-based display hint; never changes alerts or AIS records.

    AIS-Catcher: class 11 = base station, class 12 = Aid-to-Navigation.
    Type 55 = law-enforcement vessel. A 'P15' name alone proves neither
    a fixed platform nor a police boat.
    """
    label = str(name or "").strip()
    callsign = str(callsign or "").strip()
    is_station = shipclass in (11, 12)
    is_aton_mmsi = str(mmsi or "").startswith("99")
    fixed_evidence = is_station or is_aton_mmsi
    # Port of Rotterdam Authority (RPA) vessels are separate from the police.
    # Recognize the known fleet by MMSI even if a receiver lacks the ship name,
    # but never override an explicit former police P-number/identity.
    rpa_name = _RPA_NAME_RE.match(label) or _RPA_NAME_RE.match(callsign)
    former_police_identity = (_POLICE_P_NUMBER_RE.match(label)
                              or _POLICE_P_NUMBER_RE.match(callsign)
                              or _POLICE_NAME_RE.search(label))
    known_rpa = (str(mmsi or "") in _RPA_FLEET_MMSI
                 and not former_police_identity
                 and not (shiptype is not None and
                          (70 <= shiptype <= 89 or shiptype in (30, 32))))
    if not fixed_evidence and (rpa_name or known_rpa):
        return "port_authority"
    # A real ship's reported type takes priority over suggestive short names.
    if shiptype == 55 and not is_station:
        return "police"
    if not fixed_evidence:
        is_hsc = (shipclass == 7 or shiptype == 1900
                  or (shiptype is not None and 40 <= shiptype <= 49))
        if is_hsc and (_KRVE_NAME_RE.match(label)
                       or _KRVE_NAME_RE.match(callsign)):
            return "krve"
        if shiptype != 55 and (_WATERTAXI_NAME_RE.match(label)
                               or _WATERTAXI_NAME_RE.match(callsign)):
            return "watertaxi"
        if _POLICE_NAME_RE.search(label) or _POLICE_NAME_RE.search(callsign):
            return "police"
        # P1/P15 identifiers are common for Rijnmond police boats, but
        # require the AIS special-ship class, NOT a bare name match.
        if shipclass == 5 and (_POLICE_P_NUMBER_RE.match(label)
                               or _POLICE_P_NUMBER_RE.match(callsign)):
            return "police"
    # AIS-Catcher class 10 is an AIS helicopter/AIS-SART aircraft target,
    # not a marine hull. MMSI 111205511 (PILOT SERVICES SV) reports this.
    if shipclass == 10 and not fixed_evidence:
        return "ais_helicopter"
    if fixed_evidence and _WTG_NAME_RE.search(label):
        return "offshore_wtg"
    if fixed_evidence and (_PLATFORM_CODE_RE.fullmatch(label)
                           or _PLATFORM_NAME_RE.match(label)
                           or _PLATFORM_AID_WORD_RE.search(label)):
        return "offshore_platform"
    status = str(nav_status or "").strip()
    # PLATFORM P15 C is an actual offshore installation reporting AIS
    # shiptype 99 (Other), MMSI 245453000, navstatus 6 and zero speed.
    # Do not classify vessel names like P15 or underway police boats here.
    steady_object = "STEADY OBJECT" in str(destination or "").upper()
    if (_PLATFORM_NAME_RE.match(label) and shiptype == 99
            and speed_knots is not None and 0 <= speed_knots <= 0.5
            and (status in ("5", "6") or steady_object)):
        return "offshore_platform"
    # No moving vessel may be interpreted as a fixed installation by name.
    if (shiptype in (31, 32, 52) or _TUG_NAME_RE.search(label)
            or status in ("11", "12") or _TUG_STATUS_RE.search(status)):
        return "tug"
    # AIS types 60-69 are passenger vessels. Retain special service profiles
    # resolved above and do not mistake generic Class B for a passenger ship.
    if (shiptype is not None and 60 <= shiptype <= 69) or shipclass == 4:
        return "passenger"
    if (shiptype is not None and 80 <= shiptype <= 89) or shipclass == 6:
        return "tanker"
    if (shiptype is not None and 70 <= shiptype <= 79) or shipclass == 2:
        return "cargo"
    # ONLY ordinary Class B recreation targets; Class B is a transponder
    # class, not proof of recreational use. Retain all known professional
    # vessel classifications, including tug, police and cargo, above.
    # 36=sailing, 37=pleasure craft; some Class B units omit static type.
    if (not fixed_evidence and shipclass == 3
            and shiptype in (None, 0, 36, 37, 99)
            and not (_KRVE_NAME_RE.match(label) or _KRVE_NAME_RE.match(callsign))
            and not (_POLICE_P_NUMBER_RE.match(label)
                     or _POLICE_P_NUMBER_RE.match(callsign))):
        return "pleasure"
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
        callsign = _label(item, ("callsign",), 24)
        destination = _label(item, ("destination",), 90)
        profile = display_profile(
            name, normalized_type, normalized_class, nav_status,
            mmsi=mmsi, callsign=callsign, speed_knots=speed,
            destination=destination or "")
        if profile.startswith("offshore_") or profile == "ais_helicopter":
            has_hull = False
        # When live AIS reports no full offsets, a verified fleet member may
        # use its OWN published length/beam for a clearly approximate 3D hull.
        # Do not apply this to a P5 police vessel using the former RPA6 MMSI,
        # an unrelated RPA number, or any other ship with the same name.
        hull_geometry_source = "AIS dimensions"
        hull_bearing_approximate = False
        published = _RPA_PUBLISHED_DIMENSIONS.get(mmsi)
        rpa_match = _RPA_NAME_RE.match(name)
        matching_name = (rpa_match is not None
                         and rpa_match.group(1) is not None
                         and int(rpa_match.group(1)) == _RPA_FLEET_MMSI.get(mmsi))
        if (profile == "port_authority" and published is not None
                and matching_name and not has_hull):
            if hull_heading is None and course is not None:
                hull_heading = course
            if hull_heading is not None:
                hull_bearing_approximate = heading is None
                if to_bow is None:
                    fallback_length, fallback_beam = published
                    to_bow = to_stern = fallback_length / 2
                    to_port = to_starboard = fallback_beam / 2
                    length = fallback_length
                    beam = fallback_beam
                    hull_geometry_source = (
                        "Published dimensions; approximate AIS position offset")
                has_hull = True
        # Scoped Class B pleasure-craft illustration. Other ship types
        # retain precisely their pre-existing geometry and fallback rules.
        if profile == "pleasure" and not has_hull:
            if to_bow is None:
                # Overall length/beam may be reported even without the
                # four antenna offsets; preserve plausible figures.
                sketch_length = length if length is not None and 5 <= length <= 45 else 11.0
                sketch_beam = beam if beam is not None and 2 <= beam <= 12 else 3.2
                to_bow = to_stern = sketch_length / 2
                to_port = to_starboard = sketch_beam / 2
                length, beam = sketch_length, sketch_beam
                hull_geometry_source = (
                    "Illustrative Class B pleasure hull; antenna offsets unavailable")
            if hull_heading is None:
                hull_heading = 0.0  # explicit neutral north-up drawing
            hull_bearing_approximate = heading is None
            has_hull = True
        # Passenger ferries sometimes provide a valid AIS class/type but no
        # dimensions (for example SPES). Draw an explicitly illustrative hull
        # instead of leaving only a small AIS arrow at close 3D zoom.
        if profile == "passenger" and not has_hull:
            if to_bow is None:
                sketch_length = length if length is not None and 12 <= length <= 120 else 26.0
                sketch_beam = beam if beam is not None and 3 <= beam <= 24 else 7.0
                to_bow = to_stern = sketch_length / 2
                to_port = to_starboard = sketch_beam / 2
                length, beam = sketch_length, sketch_beam
                hull_geometry_source = (
                    "Illustrative passenger hull; AIS antenna offsets unavailable")
            if hull_heading is None:
                hull_heading = course if course is not None else 0.0
            hull_bearing_approximate = heading is None
            has_hull = True
        selected.append({
            "type": "ais", "id": mmsi, "name": name,
            "render_profile": profile,
            "is_offshore_structure": profile.startswith("offshore_"),
            "callsign": callsign, "lon": pos[0], "lat": pos[1],
            "validation_state": validation_state,
            "position_stale": position_stale,
            "course": course,
            "heading": heading,
            "hull_heading": hull_heading if has_hull else None,
            "to_bow": to_bow, "to_stern": to_stern,
            "to_port": to_port, "to_starboard": to_starboard,
            "hull_available": has_hull,
            "hull_geometry_source": hull_geometry_source if has_hull else None,
            "hull_bearing_approximate": hull_bearing_approximate,
            "length_m": round(length, 1) if length is not None else None,
            "shipclass": normalized_class,
            "shiptype": normalized_type,
            "imo": _label(item, ("imo",), 15),
            "eni": _label(item, ("eni",), 15),
            "destination": destination,
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


def _is_helicopter(item: dict) -> bool:
    """Helicopter using ADS-B category, ICAO type and type description only."""
    category = str(item.get("category") or "").strip().upper()
    desc = str(item.get("desc") or "").strip().upper()
    typ = str(item.get("t") or item.get("type") or "").strip().upper()
    return (
        category == "A7"
        or bool(re.match(r"^H[0-9][A-Z]$", desc))
        or "HELICOPTER" in desc or "ROTORCRAFT" in desc
        or bool(re.match(
            r"^(?:H1\d\d|H5\d\d|H60|EC\d\d|AS\d\d|AW\d{2,3}|"
            r"R(?:22|44|66)|B0[56]|B4(?:07|12|29)|S(?:76|92)|"
            r"MD5\d|NH90|CH47|UH1|MI8|G2CA)$", typ))
    )


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
            # readsb's "type" is the message/source kind ("adsb_icao"),
            # never the ICAO aircraft designator. That is the "t" field.
            "aircraft_type": _label(item, ("t",), 20),
            "description": _label(item, ("desc",), 80),
            "is_helicopter": _is_helicopter(item),
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


def all_tracks_snapshot(minutes: int = 15) -> dict:
    """Read and bound genuine historical paths for all currently displayed ships.

    The AIS-Catcher endpoint is read-only and tracks are shown only for vessels
    present in our AIS map snapshot. Named fixed installations never get trails.
    Gaps and implausible jumps are split rather than joined by false segments.
    """
    # 1–60 minutes, bounded even when called outside the Flask route.
    window_seconds = max(60, min(TRACK_WINDOW_SECONDS, int(minutes) * 60))
    empty = {"type": "FeatureCollection", "features": []}
    payload, _ = receiver_monitor._read_json_url(TRACK_ALL_URLS, timeout=1.0)
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        return {"ok": True, "available": False, "track_count": 0,
                "point_count": 0, "geojson": empty}
    paths = payload.get("features")
    if not isinstance(paths, list):
        return {"ok": True, "available": False, "track_count": 0,
                "point_count": 0, "geojson": empty}
    ais_payload, _ = receiver_monitor._read_ais_ships()
    allowed = {}
    if ais_payload is not None:
        for ship in vessels(ais_payload):
            if not ship["is_offshore_structure"]:
                allowed[ship["id"]] = ship
    now = time.time()
    features, drawn, used_points = [], set(), 0
    for feature in paths[:MAX_TARGETS * 2]:
        if len(drawn) >= TRACK_ALL_MAX_SHIPS or used_points >= TRACK_ALL_TOTAL_POINTS:
            break
        if not isinstance(feature, dict):
            continue
        properties, geometry = feature.get("properties"), feature.get("geometry")
        if not isinstance(properties, dict) or not isinstance(geometry, dict):
            continue
        if geometry.get("type") != "LineString":
            continue
        ident = str(properties.get("mmsi", ""))
        ship = allowed.get(ident)
        if ship is None or ident in drawn:
            continue
        coords, times = geometry.get("coordinates"), properties.get("timestamps_start")
        if not isinstance(coords, list) or not isinstance(times, list):
            continue
        # AIS-Catcher writes its path newest-first; retain only a bounded hour.
        samples = []
        for point, ts in zip(coords[:6000], times[:6000]):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            lon, lat, stamp = _num(point[0]), _num(point[1]), _num(ts)
            if (lon is None or lat is None or stamp is None
                    or not -180 <= lon <= 180 or not -90 <= lat <= 90
                    or not now - window_seconds <= stamp <= now + 60):
                continue
            samples.append((stamp, [round(lon, 6), round(lat, 6)]))
        samples.sort(key=lambda v: v[0])
        limit = min(TRACK_ALL_POINT_LIMIT, TRACK_ALL_TOTAL_POINTS - used_points)
        samples = samples[-limit:]
        lines, segment, previous = [], [], None
        for stamp, point in samples:
            if previous is not None:
                last_stamp, last_point = previous
                if (stamp-last_stamp > 900
                        or abs(point[0]-last_point[0]) > .3
                        or abs(point[1]-last_point[1]) > .3):
                    if len(segment) >= 2:
                        lines.append(segment)
                    segment = []
                if point == last_point:
                    previous = (stamp, point)
                    continue
            segment.append(point)
            previous = (stamp, point)
        if len(segment) >= 2:
            lines.append(segment)
        if not lines:
            continue
        points = sum(len(line) for line in lines)
        used_points += points
        drawn.add(ident)
        for line in lines:
            features.append({"type": "Feature",
                "geometry": {"type": "LineString", "coordinates": line},
                "properties": {"mmsi": ident, "shipclass": ship["shipclass"] or 1}})
    return {"ok": True, "available": True, "track_count": len(drawn),
            "point_count": used_points,
            "geojson": {"type": "FeatureCollection", "features": features}}


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
