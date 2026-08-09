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
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from core import iss_voice_runtime, receiver_authority, receiver_registry


READSB_AIRCRAFT_FILES = (
    Path("/run/readsb/aircraft.json"),
    Path("/var/run/readsb/aircraft.json"),
    Path("/run/dump1090-fa/aircraft.json"),
)

READSB_STATS_FILES = (
    Path("/run/readsb/stats.json"),
    Path("/var/run/readsb/stats.json"),
    Path("/run/dump1090-fa/stats.json"),
)

READSB_AIRCRAFT_MAX_AGE_SECONDS = 5.0
READSB_STATS_MAX_AGE_SECONDS = 15.0

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


def _runtime_file_observation(
    source: str | None,
    *,
    max_age_seconds: float,
    service_started_epoch: float | None,
) -> dict[str, Any]:
    """Describe whether one decoder file belongs to the current live runtime."""
    result = {
        "source": source,
        "exists": False,
        "age_seconds": None,
        "fresh": False,
        "updated_after_service_start": None,
    }
    if not source:
        return result

    try:
        modified = Path(source).stat().st_mtime
    except OSError:
        return result

    age = max(0.0, time.time() - modified)
    updated_after_start = (
        None
        if service_started_epoch is None
        else modified + 1.0 >= float(service_started_epoch)
    )
    result.update({
        "exists": True,
        "age_seconds": round(age, 1),
        "fresh": age <= max_age_seconds and updated_after_start is not False,
        "updated_after_service_start": updated_after_start,
    })
    return result


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




def _readsb_window_message_rate(payload: Any, window: str = "last1min") -> float | None:
    """Return readsb's own average message rate for a statistics window.

    readsb already publishes a bounded counter with explicit start and end
    timestamps. Using that window avoids false zero values when readsb or SDRCC
    restarts and the cumulative counter in aircraft.json resets.
    """

    if not isinstance(payload, dict):
        return None
    sample = payload.get(window)
    if not isinstance(sample, dict):
        return None

    messages = _safe_number(sample.get("messages"))
    start = _safe_number(sample.get("start"))
    end = _safe_number(sample.get("end"))
    if messages is None or start is None or end is None:
        return None
    elapsed = end - start
    if elapsed <= 0 or messages < 0:
        return None
    return round(messages / elapsed, 1)


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


def get_adsb_metrics(
    service_active: bool,
    *,
    service_started_epoch: float | None = None,
) -> dict[str, Any]:
    result = {
        "available": False,
        "service_active": bool(service_active),
        "targets": 0,
        "with_position": 0,
        "messages_per_second": None,
        "max_range_nm": None,
        "source": None,
        "runtime_files": {},
        "runtime_files_fresh": False,
        "runtime_ready": False,
        "detail": "readsb metrics niet beschikbaar",
    }
    if not service_active:
        result["detail"] = "ADS-B-service staat uit"
        return result

    payload, source = _read_json_file(READSB_AIRCRAFT_FILES)
    stats_payload, stats_source = _read_json_file(READSB_STATS_FILES)
    runtime_files = {
        "aircraft": _runtime_file_observation(
            source,
            max_age_seconds=READSB_AIRCRAFT_MAX_AGE_SECONDS,
            service_started_epoch=service_started_epoch,
        ),
        "statistics": _runtime_file_observation(
            stats_source,
            max_age_seconds=READSB_STATS_MAX_AGE_SECONDS,
            service_started_epoch=service_started_epoch,
        ),
    }
    result["runtime_files"] = runtime_files
    result["runtime_files_fresh"] = all(
        item.get("fresh") is True for item in runtime_files.values()
    )
    if not isinstance(payload, dict):
        result["detail"] = "ADS-B-service actief; aircraft.json niet gevonden"
        return result

    messages_per_second = _readsb_window_message_rate(stats_payload)
    message_rate_source = stats_source if messages_per_second is not None else None
    if messages_per_second is None:
        messages_per_second = _message_rate("adsb", payload.get("messages"))
        if messages_per_second is not None:
            message_rate_source = source

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
        "messages_per_second": messages_per_second,
        "message_rate_source": message_rate_source,
        "max_range_nm": round(max(ranges), 1) if ranges else None,
        "source": source,
        "stats_source": stats_source,
        "runtime_ready": bool(result["runtime_files_fresh"]),
        "detail": f"{len(active_aircraft)} vliegtuigen gezien in de laatste 60 seconden",
    })
    return result


def _device_number(device: dict[str, Any], fallback_index: int) -> str:
    name = str(device.get("name") or device.get("id") or "").upper().replace(" ", "")
    if name.startswith("SDR") and name[3:].isdigit():
        return name
    return f"SDR{fallback_index + 1}"


def _same_receiver(left: Any, right: Any) -> bool:
    """Compare receiver identities through the central Receiver Registry.

    Runtime components may expose either a compatibility alias (``sdr1``) or
    the canonical registry identity (``receiver01``). The monitor is a
    read-only consumer and must not require every provider to expose the same
    representation. Unknown identities retain exact-match compatibility.
    """

    left_value = str(left or "").strip().lower()
    right_value = str(right or "").strip().lower()
    if not left_value or not right_value:
        return False
    if left_value == right_value:
        return True

    try:
        left_id = receiver_registry.resolve_id(left_value)
        right_id = receiver_registry.resolve_id(right_value)
    except (OSError, ValueError, TypeError):
        return False
    return bool(left_id and right_id and left_id == right_id)


def get_snapshot(
    *,
    devices: list[dict[str, Any]],
    assignments: dict[str, str],
    ais_service: dict[str, Any],
    adsb_service: dict[str, Any],
    mission: dict[str, Any],
    live_rf: dict[str, Any],
    authority_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ais_metrics = get_ais_metrics(bool(ais_service.get("active")))
    adsb_metrics = get_adsb_metrics(bool(adsb_service.get("active")))

    iss_runtime = iss_voice_runtime.get_status()

    active_job = mission.get("active_job") or {}
    authority = authority_snapshot or receiver_authority.get_snapshot(
        service_states={"ais": ais_service, "adsb": adsb_service},
        mission_status=mission,
        weather_runtime=live_rf,
        iss_runtime=iss_runtime,
        use_cache=False,
    )
    authority_roles = authority.get("roles") if isinstance(authority, dict) else {}
    if not isinstance(authority_roles, dict):
        authority_roles = {}
    weather_observation = authority_roles.get("weather") or {}
    ais_observation = authority_roles.get("ais") or {}
    adsb_observation = authority_roles.get("adsb") or {}
    iss_observation = authority_roles.get("iss_voice") or {}

    def roles_for_device(device_id: str, field: str) -> list[str]:
        roles = []
        for candidate_role, observation in authority_roles.items():
            if not isinstance(observation, dict):
                continue
            if _same_receiver(device_id, observation.get(field)):
                roles.append(str(candidate_role))
        return roles

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
        configured_roles = roles_for_device(device_id, "configured_receiver")
        verified_runtime_roles = roles_for_device(device_id, "verified_runtime_receiver")
        relevant_observations = [
            observation
            for observation in authority_roles.values()
            if isinstance(observation, dict)
            and (
                _same_receiver(device_id, observation.get("configured_receiver"))
                or _same_receiver(device_id, observation.get("verified_runtime_receiver"))
            )
        ]
        configuration_drift = any(
            bool(observation.get("configuration_drift"))
            for observation in relevant_observations
        )
        active_unverified = [
            observation
            for observation in relevant_observations
            if observation.get("runtime_active")
            and not observation.get("verified_runtime_receiver")
        ]

        if (
            iss_observation.get("runtime_active")
            and iss_observation.get("verified_runtime_receiver")
            and _same_receiver(
                device_id,
                iss_observation.get("verified_runtime_receiver"),
            )
        ):
            role = "ISS VOICE"
            status = (
                "DRIFT"
                if iss_observation.get("configuration_drift")
                else str(iss_runtime.get("phase") or "ACTIVE").upper()
            )
            frequency_hz = iss_runtime.get("frequency_hz")
            detail = str(iss_runtime.get("detail") or "ISS Voice capture active")
            iq_path = iss_runtime.get("iq_path")
            iq_bytes = None
            if iq_path:
                try:
                    iq_bytes = Path(str(iq_path)).stat().st_size
                except OSError:
                    iq_bytes = iss_runtime.get("iq_bytes")
            started_at = iss_runtime.get("started_at")
            elapsed_seconds = None
            if started_at:
                try:
                    elapsed_seconds = max(0, int(time.time() - datetime.fromisoformat(str(started_at)).timestamp()))
                except (TypeError, ValueError):
                    elapsed_seconds = None
            metrics = {
                "satellite": iss_runtime.get("satellite"),
                "sample_rate_hz": iss_runtime.get("sample_rate_hz"),
                "mode": iss_runtime.get("mode"),
                "elapsed_seconds": elapsed_seconds,
                "duration_seconds": iss_runtime.get("duration_seconds"),
                "iq_bytes": iq_bytes,
                "recording": Path(str(iq_path)).name if iq_path else None,
            }
        elif (
            weather_observation.get("runtime_active")
            and weather_observation.get("verified_runtime_receiver")
            and _same_receiver(
                device_id,
                weather_observation.get("verified_runtime_receiver"),
            )
        ):
            role = "WEATHER"
            status = (
                "DRIFT"
                if weather_observation.get("configuration_drift")
                else str(live_rf.get("state") or mission.get("state") or "ACTIVE").upper()
            )
            frequency_hz = live_rf.get("frequency_hz") or active_job.get("frequency")
            detail = str(live_rf.get("detail") or active_job.get("satellite") or "Actieve satellietmissie")
            metrics = {
                "satellite": live_rf.get("satellite") or active_job.get("satellite"),
                "pipeline": live_rf.get("pipeline") or active_job.get("pipeline"),
                "snr_db": live_rf.get("snr_db"),
                "peak_snr_db": live_rf.get("peak_snr_db"),
                "ber": live_rf.get("ber"),
                "frames": int(live_rf.get("frames") or 0),
                "cadu_bytes": int(live_rf.get("cadu_bytes") or 0),
                "images": int(live_rf.get("image_count") or 0),
                "remaining_seconds": live_rf.get("remaining_seconds"),
                "gain_db": live_rf.get("gain_db"),
                "gain_mode": live_rf.get("gain_mode"),
                "viterbi": live_rf.get("viterbi"),
                "deframer": live_rf.get("deframer"),
            }
        elif (
            ais_observation.get("service_active")
            and _same_receiver(device_id, ais_observation.get("verified_runtime_receiver"))
        ):
            role = "AIS"
            status = "DRIFT" if ais_observation.get("configuration_drift") else "RUNNING"
            frequency_hz = 161_975_000
            detail = (
                f"{ais_metrics['detail']} · geverifieerd op {number}"
                + (
                    f", geconfigureerd voor {str(ais_observation.get('configured_receiver') or '-').upper()}"
                    if ais_observation.get("configuration_drift") else ""
                )
            )
            metrics = ais_metrics
        elif (
            adsb_observation.get("service_active")
            and _same_receiver(device_id, adsb_observation.get("verified_runtime_receiver"))
        ):
            role = "ADS-B"
            status = "DRIFT" if adsb_observation.get("configuration_drift") else "RUNNING"
            frequency_hz = 1_090_000_000
            detail = (
                f"{adsb_metrics['detail']} · geverifieerd op {number}"
                + (
                    f", geconfigureerd voor {str(adsb_observation.get('configured_receiver') or '-').upper()}"
                    if adsb_observation.get("configuration_drift") else ""
                )
            )
            metrics = adsb_metrics

        if role == "IDLE" and active_unverified:
            status = "UNVERIFIED"
            affected = ", ".join(
                str(observation.get("role") or "service").upper()
                for observation in active_unverified
            )
            detail = f"{affected} is actief, maar de gebruikte receiver is niet geverifieerd"
        elif role == "IDLE" and configuration_drift:
            status = "DRIFT"
            detail = "Configuratiedrift: configured en verified runtime komen niet overeen"

        display_metrics: list[dict[str, Any]] = []

        # Every active provider exposes the tuned frequency in the same way.
        # Provider-specific metrics remain flexible and may differ per task.
        if role != "IDLE":
            display_metrics.append({
                "key": "frequency",
                "label": "Frequentie",
                "value": frequency_hz,
                "format": "frequency_hz",
            })

        if role == "ISS VOICE":
            display_metrics.extend([
                {"key": "satellite", "label": "Satellite", "value": metrics.get("satellite"), "format": "text"},
                {"key": "mode", "label": "Mode", "value": metrics.get("mode"), "format": "text"},
                {"key": "sample_rate_hz", "label": "Sample rate", "value": metrics.get("sample_rate_hz"), "format": "frequency_hz"},
                {"key": "elapsed_seconds", "label": "Elapsed", "value": metrics.get("elapsed_seconds"), "format": "duration"},
                {"key": "duration_seconds", "label": "Planned", "value": metrics.get("duration_seconds"), "format": "duration"},
                {"key": "iq_bytes", "label": "IQ written", "value": metrics.get("iq_bytes"), "format": "bytes"},
                {"key": "recording", "label": "Recording", "value": metrics.get("recording"), "format": "text"},
            ])
        elif role == "AIS":
            display_metrics.extend([
                {"key": "targets", "label": "Schepen", "value": metrics.get("targets"), "format": "integer"},
                {"key": "messages_per_second", "label": "Berichten/s", "value": metrics.get("messages_per_second"), "format": "decimal_1"},
                {"key": "max_range_nm", "label": "Max. bereik", "value": metrics.get("max_range_nm"), "format": "distance_nm"},
            ])
        elif role == "ADS-B":
            display_metrics.extend([
                {"key": "targets", "label": "Vliegtuigen", "value": metrics.get("targets"), "format": "integer"},
                {"key": "with_position", "label": "Met positie", "value": metrics.get("with_position"), "format": "integer"},
                {"key": "messages_per_second", "label": "Berichten/s", "value": metrics.get("messages_per_second"), "format": "decimal_1"},
                {"key": "max_range_nm", "label": "Max. bereik", "value": metrics.get("max_range_nm"), "format": "distance_nm"},
            ])
        elif role == "WEATHER":
            display_metrics.extend([
                {"key": "satellite", "label": "Satelliet", "value": metrics.get("satellite"), "format": "text"},
                {"key": "pipeline", "label": "Pipeline", "value": metrics.get("pipeline"), "format": "text"},
                {"key": "snr_db", "label": "SNR", "value": metrics.get("snr_db"), "format": "db_2"},
                {"key": "peak_snr_db", "label": "Peak SNR", "value": metrics.get("peak_snr_db"), "format": "db_2"},
                {"key": "ber", "label": "BER", "value": metrics.get("ber"), "format": "decimal_4"},
                {"key": "frames", "label": "Frames", "value": metrics.get("frames"), "format": "integer"},
                {"key": "cadu_bytes", "label": "CADU", "value": metrics.get("cadu_bytes"), "format": "bytes"},
                {"key": "images", "label": "Beelden", "value": metrics.get("images"), "format": "integer"},
                {"key": "remaining_seconds", "label": "Resterend", "value": metrics.get("remaining_seconds"), "format": "duration"},
            ])
        else:
            display_metrics.extend([
                {"key": "task", "label": "Taak", "value": device.get("current_task") or "Vrij", "format": "text"},
                {"key": "source", "label": "Bron", "value": device.get("active_detail") or "-", "format": "text"},
            ])

        receiver_rows.append({
            "id": device_id,
            "number": number,
            "name": device.get("name") or device_id,
            "serial": device.get("serial"),
            "role": role,
            "profile": str(device.get("current_task") or role).lower(),
            "status": status,
            "frequency_hz": frequency_hz,
            "detail": detail,
            "metrics": metrics,
            "display_metrics": display_metrics,
            "configured_roles": configured_roles,
            "verified_runtime_roles": verified_runtime_roles,
            "configuration_drift": configuration_drift,
            "authority_status": (
                "DRIFT" if configuration_drift
                else "UNVERIFIED" if active_unverified
                else "VERIFIED" if verified_runtime_roles
                else "CONFIGURED"
            ),
        })

    return {
        "ok": True,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "receivers": receiver_rows,
        "providers": {
            "ais": ais_metrics,
            "adsb": adsb_metrics,
            "iss_voice": iss_runtime,
        },
        "assignment_authority": authority.get("assignment_authority"),
        "authority_status": authority.get("status"),
        "configuration_drift": bool(authority.get("configuration_drift")),
        "drift": authority.get("drift", []),
    }
