#!/usr/bin/env python3

"""Receiver assignment authority, verification and transaction coordinator.

``config/station.yaml:assignments`` is the only persistent role authority.
Receiver Registry remains the immutable identity/serial authority. This module
does not manage reservations and never starts a mission. It observes external
service configuration/runtime and coordinates assignment changes through the
existing privileged service-configuration adapter supplied by the dashboard.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Any, Callable

from core import config, receiver_registry


VERSION = "0.54.0a"
AUTHORITY = "config/station.yaml:assignments"
READSB_CONFIG = Path("/etc/default/readsb")
AIS_CONFIG = Path("/etc/AIS-catcher/aiscatcher.json")
SERVICE_ROLES = {
    "ais": "ais-catcher.service",
    "adsb": "readsb.service",
}

_READSB_DEVICE_RE = re.compile(
    r"(?P<prefix>(?:^|[ \t\"'])--device(?:=|[ \t]+))"
    r"(?P<serial>[^ \t\r\n\"']+)"
)
_AIS_RUNTIME_RE = re.compile(r"Searching for device with SN\s+([^\s]+)", re.IGNORECASE)
_snapshot_lock = threading.RLock()
_transaction_lock = threading.RLock()
_snapshot_cache: tuple[float, dict[str, Any] | None] = (0.0, None)

PrivilegedApply = Callable[[str, str], dict[str, Any]]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def invalidate_cache() -> None:
    global _snapshot_cache
    with _snapshot_lock:
        _snapshot_cache = (0.0, None)


def _run(command: list[str], timeout: float = 2.0) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _service_state(service: str) -> dict[str, Any]:
    active = _run(["systemctl", "is-active", service])
    state = (active.stdout.strip() if active else "") or "unknown"
    pid_result = _run(["systemctl", "show", service, "--property=MainPID", "--value"])
    try:
        pid = int((pid_result.stdout if pid_result else "0").strip() or "0")
    except ValueError:
        pid = 0
    return {
        "service": service,
        "active": bool(active and active.returncode == 0 and state == "active"),
        "state": state,
        "pid": pid,
        "observed": active is not None,
    }


def _read_readsb_config_serial() -> tuple[str | None, str | None]:
    try:
        text = READSB_CONFIG.read_text(encoding="utf-8")
    except OSError as error:
        return None, str(error)
    matches = [
        match
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
        for match in _READSB_DEVICE_RE.finditer(line)
    ]
    if not matches:
        return None, "--device ontbreekt"
    if len(matches) != 1:
        return None, f"verwacht één actieve --device-optie, gevonden {len(matches)}"
    return matches[0].group("serial").strip(), None


def _read_ais_config_serial() -> tuple[str | None, str | None]:
    try:
        payload = json.loads(AIS_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        return None, str(error)
    receivers = payload.get("receiver") if isinstance(payload, dict) else None
    if not isinstance(receivers, list):
        return None, "receiver-lijst ontbreekt"
    candidates = []
    for item in receivers:
        if not isinstance(item, dict):
            continue
        if str(item.get("input") or "").strip().upper() != "RTLSDR":
            continue
        if item.get("active") is False:
            continue
        serial = str(item.get("serial") or "").strip()
        if serial:
            candidates.append(serial)
    if len(candidates) != 1:
        return None, f"verwacht één actieve RTLSDR-configuratie, gevonden {len(candidates)}"
    return candidates[0], None


def _read_process_cmdline(pid: int) -> list[str]:
    if pid <= 0:
        return []
    try:
        data = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in data.split(b"\0") if part]


def _readsb_runtime_serial(pid: int) -> tuple[str | None, str | None]:
    args = _read_process_cmdline(pid)
    for index, value in enumerate(args):
        if value == "--device" and index + 1 < len(args):
            return args[index + 1].strip(), None
        if value.startswith("--device="):
            return value.split("=", 1)[1].strip(), None
    return None, "--device niet gevonden in actieve readsb-opdracht"


def _ais_runtime_serial(pid: int) -> tuple[str | None, str | None]:
    if pid <= 0:
        return None, "AIS MainPID ontbreekt"
    result = _run([
        "journalctl",
        f"_PID={pid}",
        "--grep=Searching for device with SN",
        "-n",
        "1",
        "--no-pager",
        "-o",
        "cat",
    ], timeout=2.0)
    if result is None or result.returncode != 0:
        return None, "AIS-runtimejournal niet leesbaar"
    matches = _AIS_RUNTIME_RE.findall(result.stdout or "")
    return (matches[-1].strip(".,;"), None) if matches else (
        None,
        "AIS-runtimejournal bevat geen bevestigd serienummer",
    )


def _identity(receiver_id: Any) -> dict[str, Any] | None:
    try:
        return receiver_registry.identity(receiver_id)
    except (OSError, ValueError, TypeError):
        return None


def _identity_for_serial(serial: Any) -> dict[str, Any] | None:
    value = str(serial or "").strip().casefold()
    if not value:
        return None
    try:
        for receiver in receiver_registry.get_receivers():
            if str(receiver.get("serial") or "").strip().casefold() == value:
                return receiver_registry.identity(receiver.get("id"))
    except (OSError, ValueError, TypeError):
        return None
    return None


def _runtime_payloads() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        from core import iss_voice_runtime, live_rf, mission_engine
        mission = mission_engine.get_mission_status() or {}
        weather = live_rf.get_status() or {}
        iss = iss_voice_runtime.get_status() or {}
        return mission, weather, iss
    except Exception:
        return {}, {}, {}


def _mission_role(
    role: str,
    configured_receiver: str | None,
    mission: dict[str, Any],
    weather: dict[str, Any],
    iss: dict[str, Any],
) -> dict[str, Any]:
    expected = _identity(configured_receiver)
    active_job = mission.get("active_job") if isinstance(mission, dict) else None
    active_job = active_job if isinstance(active_job, dict) else {}

    if role == "weather":
        active = bool(active_job) or weather.get("active") is True
        runtime_receiver = (
            weather.get("receiver_id")
            or active_job.get("receiver_id")
            or active_job.get("receiver")
        )
        runtime_serial = weather.get("serial") or active_job.get("receiver_serial")
    else:
        active = bool(iss.get("active"))
        runtime_receiver = iss.get("receiver_id")
        runtime_serial = iss.get("receiver_serial")

    actual = _identity_for_serial(runtime_serial) or _identity(runtime_receiver)
    if actual and not runtime_serial:
        runtime_serial = actual.get("serial")
    expected_serial = (expected or {}).get("serial")
    verified = bool(
        active
        and actual
        and expected
        and actual.get("canonical_id") == expected.get("canonical_id")
        and str(runtime_serial or "") == str(expected_serial or "")
    )
    drift = []
    if active and not actual:
        drift.append("runtime_receiver_unverified")
    elif active and not verified:
        drift.append("runtime_receiver_mismatch")

    return {
        "role": role,
        "kind": "mission",
        "service": None,
        "configured_receiver": configured_receiver,
        "configured_receiver_canonical": (expected or {}).get("canonical_id"),
        "expected_serial": expected_serial,
        "service_active": False,
        "runtime_active": active,
        "service_config_serial": None,
        "runtime_serial": runtime_serial,
        "verified_runtime_receiver": (actual or {}).get("runtime_id"),
        "verified_runtime_receiver_canonical": (actual or {}).get("canonical_id"),
        "runtime_verified": verified,
        "verification": "VERIFIED" if verified else "UNVERIFIED" if active else "INACTIVE",
        "configuration_drift": bool(drift),
        "drift": drift,
    }


def _service_role(
    role: str,
    configured_receiver: str | None,
    service: dict[str, Any],
) -> dict[str, Any]:
    expected = _identity(configured_receiver)
    expected_serial = (expected or {}).get("serial")
    if role == "adsb":
        configured_serial, config_error = _read_readsb_config_serial()
        runtime_serial, runtime_error = (
            _readsb_runtime_serial(int(service.get("pid") or 0))
            if service.get("active")
            else (None, None)
        )
    else:
        configured_serial, config_error = _read_ais_config_serial()
        runtime_serial, runtime_error = (
            _ais_runtime_serial(int(service.get("pid") or 0))
            if service.get("active")
            else (None, None)
        )

    actual = _identity_for_serial(runtime_serial)
    drift = []
    if config_error:
        drift.append("service_config_unreadable")
    elif configured_serial != expected_serial:
        drift.append("service_config_serial_mismatch")
    if service.get("active"):
        if runtime_error or not actual:
            drift.append("runtime_receiver_unverified")
        elif runtime_serial != expected_serial:
            drift.append("runtime_receiver_mismatch")

    runtime_verified = bool(
        service.get("active")
        and actual
        and expected
        and runtime_serial == expected_serial
        and actual.get("canonical_id") == expected.get("canonical_id")
    )
    if drift:
        verification = "DRIFT" if any("mismatch" in item for item in drift) else "UNVERIFIED"
    else:
        verification = "VERIFIED" if service.get("active") else "CONFIGURED"

    return {
        "role": role,
        "kind": "service",
        "service": SERVICE_ROLES[role],
        "configured_receiver": configured_receiver,
        "configured_receiver_canonical": (expected or {}).get("canonical_id"),
        "expected_serial": expected_serial,
        "service_state": service.get("state"),
        "service_pid": service.get("pid"),
        "service_active": bool(service.get("active")),
        "runtime_active": bool(service.get("active")),
        "service_config_serial": configured_serial,
        "service_config_error": config_error,
        "runtime_serial": runtime_serial,
        "runtime_error": runtime_error,
        "verified_runtime_receiver": (actual or {}).get("runtime_id"),
        "verified_runtime_receiver_canonical": (actual or {}).get("canonical_id"),
        "runtime_verified": runtime_verified,
        "verification": verification,
        "configuration_drift": bool(drift),
        "drift": drift,
    }


def get_snapshot(
    *,
    service_states: dict[str, dict[str, Any]] | None = None,
    mission_status: dict[str, Any] | None = None,
    weather_runtime: dict[str, Any] | None = None,
    iss_runtime: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return a read-only configured-versus-verified authority snapshot."""
    global _snapshot_cache
    if use_cache and all(value is None for value in (
        service_states, mission_status, weather_runtime, iss_runtime
    )):
        with _snapshot_lock:
            cached_at, cached = _snapshot_cache
            if cached is not None and time.monotonic() - cached_at < 1.0:
                return deepcopy(cached)

    assignments = config.get_receiver_assignments()
    if mission_status is None or weather_runtime is None or iss_runtime is None:
        observed_mission, observed_weather, observed_iss = _runtime_payloads()
        mission_status = mission_status if mission_status is not None else observed_mission
        weather_runtime = weather_runtime if weather_runtime is not None else observed_weather
        iss_runtime = iss_runtime if iss_runtime is not None else observed_iss

    states = service_states or {}
    roles = {
        "weather": _mission_role(
            "weather", assignments.get("weather"), mission_status, weather_runtime, iss_runtime
        ),
        "ais": _service_role(
            "ais", assignments.get("ais"), states.get("ais") or _service_state(SERVICE_ROLES["ais"])
        ),
        "adsb": _service_role(
            "adsb", assignments.get("adsb"), states.get("adsb") or _service_state(SERVICE_ROLES["adsb"])
        ),
        "iss_voice": _mission_role(
            "iss_voice", assignments.get("iss_voice"), mission_status, weather_runtime, iss_runtime
        ),
    }

    drift = []
    unverified = []
    for role, item in roles.items():
        for drift_type in item.get("drift", []):
            drift.append({
                "role": role,
                "type": drift_type,
                "configured_receiver": item.get("configured_receiver"),
                "expected_serial": item.get("expected_serial"),
                "service_config_serial": item.get("service_config_serial"),
                "runtime_serial": item.get("runtime_serial"),
                "verified_runtime_receiver": item.get("verified_runtime_receiver"),
            })
        if item.get("runtime_active") and not item.get("runtime_verified"):
            unverified.append(role)

    mismatch = any("mismatch" in str(item.get("type")) for item in drift)
    status = "DRIFT" if mismatch else "UNVERIFIED" if unverified or drift else "IN_SYNC"
    snapshot = {
        "ok": not mismatch,
        "version": VERSION,
        "read_only": True,
        "assignment_authority": AUTHORITY,
        "identity_authority": "config/receivers.yaml",
        "runtime_authority": "receiver_manager",
        "service_configuration": "derived",
        "status": status,
        "configuration_drift": bool(drift),
        "configured_assignments": assignments,
        "verified_runtime_assignments": {
            role: item.get("verified_runtime_receiver")
            for role, item in roles.items()
            if item.get("runtime_verified")
        },
        "unverified_active_roles": unverified,
        "roles": roles,
        "drift": drift,
        "updated_at": _now(),
    }
    if use_cache and service_states is None:
        with _snapshot_lock:
            _snapshot_cache = (time.monotonic(), deepcopy(snapshot))
    return snapshot


def service_serials(assignments: dict[str, str | None]) -> tuple[str, str]:
    serials = {}
    for role in ("ais", "adsb"):
        identity = _identity(assignments.get(role))
        if not identity or not identity.get("serial"):
            raise ValueError(f"{role.upper()} heeft geen geldige receiver/serial")
        serials[role] = str(identity["serial"])
    if serials["ais"] == serials["adsb"]:
        raise ValueError("AIS en ADS-B kunnen niet dezelfde receiver gebruiken")
    return serials["ais"], serials["adsb"]


def _blocking_drift(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item for item in snapshot.get("drift", [])
        if item.get("role") in SERVICE_ROLES
        and item.get("type") in {
            "service_config_serial_mismatch",
            "runtime_receiver_mismatch",
        }
    ]


def apply_assignments(
    changes: dict[str, Any],
    *,
    privileged_apply: PrivilegedApply,
) -> dict[str, Any]:
    """Apply, synchronize, verify and roll back one assignment transaction."""
    with _transaction_lock:
        normalized, candidate = config.validate_assignment_changes(changes)
        previous = config.get_receiver_assignments()
        desired_ais, desired_adsb = service_serials(candidate)
        previous_ais, previous_adsb = service_serials(previous)
        persisted = False
        external_attempted = False
        try:
            config.set_plugin_assignments(normalized)
            persisted = True
            external_attempted = True
            adapter = privileged_apply(desired_ais, desired_adsb)
            if not isinstance(adapter, dict) or not adapter.get("ok"):
                message = (adapter or {}).get("message") if isinstance(adapter, dict) else None
                raise RuntimeError(message or "Serviceconfiguratie synchroniseren mislukt")
            invalidate_cache()
            verification = get_snapshot(use_cache=False)
            blocking = _blocking_drift(verification)
            if blocking:
                raise RuntimeError("Runtimeverificatie vond configuratiedrift")
            return {
                "ok": True,
                "changed": candidate != previous or bool(adapter.get("changed")),
                "version": VERSION,
                "assignment_authority": AUTHORITY,
                "previous_assignments": previous,
                "assignments": candidate,
                "adapter": adapter,
                "verification": verification,
                "rollback_performed": False,
            }
        except Exception as error:
            rollback_errors = []
            if persisted:
                try:
                    config.set_plugin_assignments(previous)
                except Exception as rollback_error:
                    rollback_errors.append(f"assignment authority: {rollback_error}")
            if external_attempted:
                try:
                    restored = privileged_apply(previous_ais, previous_adsb)
                    if not restored.get("ok"):
                        rollback_errors.append(
                            "serviceconfiguratie: " + str(restored.get("message") or "mislukt")
                        )
                except Exception as rollback_error:
                    rollback_errors.append(f"serviceconfiguratie: {rollback_error}")
            invalidate_cache()
            return {
                "ok": False,
                "changed": False,
                "version": VERSION,
                "assignment_authority": AUTHORITY,
                "message": str(error),
                "previous_assignments": previous,
                "candidate_assignments": candidate,
                "assignments": config.get_receiver_assignments(),
                "rollback_performed": persisted or external_attempted,
                "rollback_ok": not rollback_errors,
                "rollback_errors": rollback_errors,
            }
