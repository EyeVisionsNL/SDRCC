"""Optional, read-only Map Lab indicators from SDRCC's existing observers.

Does not decode ATIS, classify emergency vessels independently, change SDR
ownership, send notifications, or move the map camera.
"""
from __future__ import annotations

import math
import re

from core import emergency_monitor, receiver_monitor, traffic_voice_atis, traffic_voice_audio


def _emergency_rows(payload: object) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return []
    rows = payload.get("vessels")
    if not isinstance(rows, list):
        return []
    results = []
    for row in rows[:80]:
        if not isinstance(row, dict):
            continue
        mmsi = str(row.get("mmsi") or "").strip()
        category = str(row.get("category") or "")
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            remaining = float(row["remaining_seconds"])
        except (TypeError, ValueError, KeyError):
            continue
        if (not re.fullmatch(r"\d{9}", mmsi)
                or category not in ("knrm", "waterpolitie")
                or not all(math.isfinite(n) for n in (lat, lon, remaining))
                or not -90 <= lat <= 90 or not -180 <= lon <= 180
                or not 0 < remaining <= 300):
            continue
        results.append({
            "mmsi": mmsi, "category": category,
            "latitude": lat, "longitude": lon,
            "remaining_seconds": remaining,
        })
    return results


def _atis_event(status: object, matcher=receiver_monitor.match_ais_atis) -> dict | None:
    """Only a fresh validated decoder result with one exact AIS match is marked."""
    if not isinstance(status, dict):
        return None
    latest = status.get("latest")
    if not isinstance(latest, dict) or latest.get("fresh") is not True:
        return None
    # No historical ATIS event, no non-marine audio and no longer-lived match.
    if latest.get("mode_id") != "marine_ais":
        return None
    code = str(latest.get("atis_code") or "").strip()
    event_time = str(latest.get("received_at") or "").strip()
    try:
        age = float(latest.get("age_seconds"))
    except (ValueError, TypeError):
        return None
    if (not re.fullmatch(r"9\d{9}", code) or not event_time
            or not math.isfinite(age) or not 0 <= age < 30):
        return None
    match = matcher(code)
    if not isinstance(match, dict) or match.get("matched") is not True:
        return None
    mmsi = str(match.get("mmsi") or "").strip()
    try:
        lat, lon = float(match["latitude"]), float(match["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if (not re.fullmatch(r"\d{9}", mmsi)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return {
        "mmsi": mmsi, "atis_code": code,
        "event_id": (code + "|" + event_time)[:100],
        "latitude": lat, "longitude": lon,
        "remaining_seconds": round(30 - age, 1),
        "match_method": str(match.get("match_method") or "")[:40],
    }


def snapshot() -> dict:
    try:
        emergency = _emergency_rows(emergency_monitor.map_highlights())
    except Exception:
        emergency = []
    try:
        # The Marine Voice status route starts the shared UDP audio observer.
        # Standalone Map Lab must also initialize it to receive decoded ATIS.
        # This does not claim or open SDR hardware.
        traffic_voice_audio.ensure_listener()
        atis = _atis_event(traffic_voice_atis.get_status())
    except Exception:
        atis = None
    return {
        "ok": True, "read_only": True, "emergency_vessels": emergency,
        "atis_match": atis, "refresh_seconds": 10,
    }
