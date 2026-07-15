"""Receiver Monitor status providers for SDRCC.

The monitor is deliberately read-only. It combines receiver assignments, service
state and locally available decoder JSON without controlling any receiver.
Missing metric sources are reported as unavailable instead of failing the API.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


READSB_AIRCRAFT_FILES = (
    Path("/run/readsb/aircraft.json"),
    Path("/var/run/readsb/aircraft.json"),
    Path("/run/dump1090-fa/aircraft.json"),
)

AIS_SHIPS_URLS = (
    "http://127.0.0.1:8100/ships.json",
    "http://localhost:8100/ships.json",
)

_rate_lock = threading.RLock()
_rate_state: dict[str, tuple[float, int]] = {}
_ais_journal_cache: tuple[float, float | None] = (0.0, None)
_AIS_RATE_RE = re.compile(r"rate:\s*([0-9]+(?:\.[0-9]+)?)\s*msg/s", re.IGNORECASE)


def _read_json_file(paths: tuple[Path, ...]) -> tuple[Any | None, str | None]:
    for path in paths:
        try:
            if not path.is_file():
                continue
            return json.loads(path.read_text(encoding="utf-8")), str(path)
        except (OSError, ValueError, TypeError):
            continue
    return None, None


def _read_json_url(urls: tuple[str, ...], timeout: float = 0.45) -> tuple[Any | None, str | None]:
    for url in urls:
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": "SDRCC/ReceiverMonitor"})
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - localhost-only candidates
                payload = response.read(8 * 1024 * 1024)
            return json.loads(payload.decode("utf-8")), url
        except (OSError, URLError, ValueError, TypeError, UnicodeDecodeError):
            continue
    return None, None


def _safe_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _ais_journal_message_rate() -> float | None:
    """Return a smoothed recent AIS-catcher message rate from journald.

    AIS-catcher writes one Challenger rate sample roughly every three seconds.
    We average the five newest samples from the last 30 seconds to keep the
    Receiver Monitor readable and avoid a rapidly jumping value.
    """

    global _ais_journal_cache

    now = time.monotonic()
    cached_at, cached_value = _ais_journal_cache
    if now - cached_at < 2.0:
        return cached_value

    try:
        completed = subprocess.run(
            [
                "journalctl",
                "-u",
                "ais-catcher.service",
                "--since",
                "30 seconds ago",
                "-n",
                "40",
                "--no-pager",
                "-o",
                "cat",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        _ais_journal_cache = (now, None)
        return None

    rates: list[float] = []
    if completed.returncode == 0:
        for line in completed.stdout.splitlines():
            match = _AIS_RATE_RE.search(line)
            if match:
                rates.append(float(match.group(1)))

    recent = rates[-5:]
    value = round(sum(recent) / len(recent), 1) if recent else None
    _ais_journal_cache = (now, value)
    return value


def _message_rate(key: str, total: Any) -> float | None:
    count_number = _safe_number(total)
    if count_number is None:
        return None
    count = int(count_number)
    now = time.monotonic()
    with _rate_lock:
        previous = _rate_state.get(key)
        _rate_state[key] = (now, count)
    if not previous:
        return None
    elapsed = now - previous[0]
    delta = count - previous[1]
    if elapsed <= 0 or delta < 0:
        return None
    return round(delta / elapsed, 1)


def _extract_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            return [item for item in value.values() if isinstance(item, dict)]
    # Some AIS-catcher versions expose an MMSI-keyed object directly.
    if payload and all(isinstance(value, dict) for value in payload.values()):
        return list(payload.values())
    return []


def _first_number(item: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _safe_number(item.get(name))
        if value is not None:
            return value
    return None


def get_ais_metrics(service_active: bool) -> dict[str, Any]:
    result = {
        "available": False,
        "service_active": bool(service_active),
        "targets": 0,
        "messages_per_second": None,
        "max_range_nm": None,
        "source": None,
        "detail": "AIS-catcher metrics niet beschikbaar",
    }
    if not service_active:
        result["detail"] = "AIS-service staat uit"
        return result

    payload, source = _read_json_url(AIS_SHIPS_URLS)
    if payload is None:
        result["detail"] = "AIS-service actief; ships.json niet bereikbaar op poort 8100"
        return result

    ships = _extract_list(payload, ("ships", "vessels", "targets", "data"))
    ranges: list[float] = []
    for ship in ships:
        distance = _first_number(ship, ("distance_nm", "distance", "range_nm", "distanceNmi"))
        if distance is not None and 0 <= distance < 10000:
            ranges.append(distance)

    total_messages = payload.get("messages") if isinstance(payload, dict) else None
    journal_rate = _ais_journal_message_rate()
    messages_per_second = journal_rate
    rate_source = "journalctl:ais-catcher.service" if journal_rate is not None else None
    if messages_per_second is None:
        messages_per_second = _message_rate("ais", total_messages)
        if messages_per_second is not None:
            rate_source = source

    result.update({
        "available": True,
        "targets": len(ships),
        "messages_per_second": messages_per_second,
        "message_rate_source": rate_source,
        "max_range_nm": round(max(ranges), 1) if ranges else None,
        "source": source,
        "detail": f"{len(ships)} schepen in lokale AIS-catcher viewer",
    })
    return result


def get_adsb_metrics(service_active: bool) -> dict[str, Any]:
    result = {
        "available": False,
        "service_active": bool(service_active),
        "targets": 0,
        "with_position": 0,
        "messages_per_second": None,
        "max_range_nm": None,
        "source": None,
        "detail": "readsb metrics niet beschikbaar",
    }
    if not service_active:
        result["detail"] = "ADS-B-service staat uit"
        return result

    payload, source = _read_json_file(READSB_AIRCRAFT_FILES)
    if not isinstance(payload, dict):
        result["detail"] = "ADS-B-service actief; aircraft.json niet gevonden"
        return result

    aircraft = _extract_list(payload, ("aircraft",))
    active_aircraft = []
    for item in aircraft:
        seen = _safe_number(item.get("seen"))
        if seen is None or seen <= 60:
            active_aircraft.append(item)

    with_position = sum(
        1 for item in active_aircraft
        if _safe_number(item.get("lat")) is not None and _safe_number(item.get("lon")) is not None
    )
    ranges = []
    for item in active_aircraft:
        distance = _first_number(item, ("r_dst", "distance", "range"))
        if distance is not None and 0 <= distance < 10000:
            ranges.append(distance)

    result.update({
        "available": True,
        "targets": len(active_aircraft),
        "with_position": with_position,
        "messages_per_second": _message_rate("adsb", payload.get("messages")),
        "max_range_nm": round(max(ranges), 1) if ranges else None,
        "source": source,
        "detail": f"{len(active_aircraft)} vliegtuigen gezien in de laatste 60 seconden",
    })
    return result


def _device_number(device: dict[str, Any], fallback_index: int) -> str:
    name = str(device.get("name") or device.get("id") or "").upper().replace(" ", "")
    if name.startswith("SDR") and name[3:].isdigit():
        return name
    return f"SDR{fallback_index + 1}"


def get_snapshot(
    *,
    devices: list[dict[str, Any]],
    assignments: dict[str, str],
    ais_service: dict[str, Any],
    adsb_service: dict[str, Any],
    mission: dict[str, Any],
    live_rf: dict[str, Any],
) -> dict[str, Any]:
    ais_metrics = get_ais_metrics(bool(ais_service.get("active")))
    adsb_metrics = get_adsb_metrics(bool(adsb_service.get("active")))

    active_job = mission.get("active_job") or {}
    weather_active = bool(active_job) or live_rf.get("active") is True
    weather_receiver_id = str(active_job.get("receiver_id") or assignments.get("weather") or "")

    receiver_rows = []
    for index, raw_device in enumerate(devices or []):
        device = dict(raw_device)
        device_id = str(device.get("id") or "")
        number = _device_number(device, index)
        role = "IDLE"
        status = "AVAILABLE"
        metrics: dict[str, Any] = {}
        frequency_hz = None
        detail = "Receiver is vrij"

        if weather_active and device_id == weather_receiver_id:
            role = "WEATHER"
            status = str(live_rf.get("state") or mission.get("state") or "ACTIVE").upper()
            frequency_hz = live_rf.get("frequency_hz") or active_job.get("frequency")
            detail = str(live_rf.get("detail") or active_job.get("satellite") or "Actieve satellietmissie")
            metrics = {
                "satellite": live_rf.get("satellite") or active_job.get("satellite"),
                "snr_db": live_rf.get("snr_db"),
                "peak_snr_db": live_rf.get("peak_snr_db"),
                "frames": int(live_rf.get("frames") or 0),
                "images": int(live_rf.get("image_count") or 0),
            }
        elif assignments.get("ais") == device_id and ais_service.get("active"):
            role = "AIS"
            status = "RUNNING"
            frequency_hz = 161_975_000
            detail = ais_metrics["detail"]
            metrics = ais_metrics
        elif assignments.get("adsb") == device_id and adsb_service.get("active"):
            role = "ADS-B"
            status = "RUNNING"
            frequency_hz = 1_090_000_000
            detail = adsb_metrics["detail"]
            metrics = adsb_metrics

        receiver_rows.append({
            "id": device_id,
            "number": number,
            "name": device.get("name") or device_id,
            "serial": device.get("serial"),
            "role": role,
            "status": status,
            "frequency_hz": frequency_hz,
            "detail": detail,
            "metrics": metrics,
        })

    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "receivers": receiver_rows,
        "providers": {
            "ais": ais_metrics,
            "adsb": adsb_metrics,
        },
    }
