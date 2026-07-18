#!/usr/bin/env python3

"""Central receiver assignment and runtime reservation state.

The manager stores generic reservation metadata only. Stopping and starting
system services remains the responsibility of the mission runtime, which keeps
this module safe to use for WEATHER, VOICE and future mission types.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json

from core import event_bus
from core.device_manager import get_device, get_receiver_context, get_weather_device

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "receiver_manager.json"
_LOCK = RLock()

DEFAULT_STATE: dict[str, Any] = {
    "reservation": None,
    "last_release": None,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return deepcopy(DEFAULT_STATE)
        state = deepcopy(DEFAULT_STATE)
        state.update(data)
        return state
    except Exception:
        return deepcopy(DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _device_summary(device_id: str | None) -> dict[str, Any] | None:
    if not device_id:
        return None
    device = get_device(device_id)
    if device is None:
        return {"id": device_id, "number": device_id.upper(), "missing": True}
    return {
        "id": device["id"],
        "number": device["number"],
        "name": device["name"],
        "serial": device["serial"],
    }


def get_status() -> dict[str, Any]:
    configured = get_weather_device()
    with _LOCK:
        state = _load_state()
    reservation = deepcopy(state.get("reservation"))
    if reservation:
        reservation["device"] = _device_summary(reservation.get("receiver_id"))
    last_release = deepcopy(state.get("last_release"))
    if isinstance(last_release, dict) and last_release.get("released_at"):
        last_release["status"] = "RELEASED"

    return {
        "ok": True,
        "configured_receiver": _device_summary(configured.get("id") if configured else None),
        "reservation": reservation,
        "last_release": last_release,
        "available": reservation is None,
    }


def is_available(receiver_id: str, *, mission_key: str | None = None) -> bool:
    with _LOCK:
        reservation = _load_state().get("reservation")
    if reservation is None:
        return True
    return bool(
        reservation.get("receiver_id") == receiver_id
        and mission_key
        and reservation.get("mission_key") == mission_key
    )


def reserve(
    receiver_id: str,
    *,
    mission_key: str,
    mission_id: str | None = None,
    reason: str = "mission",
    mission_type: str = "WEATHER",
    target: str | None = None,
) -> dict[str, Any]:
    device = get_device(receiver_id)
    if device is None:
        raise ValueError(f"Onbekende receiver: {receiver_id}")
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")

    context = get_receiver_context(receiver_id) or {}
    normalized_type = str(mission_type or "MISSION").strip().upper()

    with _LOCK:
        state = _load_state()
        current = state.get("reservation")
        if current and current.get("mission_key") != key:
            raise RuntimeError(
                f"{current.get('receiver_id', '-').upper()} is al gereserveerd "
                f"voor {current.get('mission_key', '-')}"
            )
        if current and current.get("receiver_id") != receiver_id:
            raise RuntimeError("De missie is al aan een andere receiver gekoppeld")

        reservation = current or {
            "receiver_id": receiver_id,
            "mission_key": key,
            "reserved_at": _now(),
            "status": "RESERVED",
            "reason": str(reason),
            "mission_type": normalized_type,
            "previous_role": context.get("previous_role", "manual"),
            "conflicting_service": context.get("conflicting_service"),
            "service_was_active": None,
            "service_stopped": False,
            "restore_required": False,
            "restore_status": "NOT_REQUIRED",
        }
        reservation.setdefault("mission_type", normalized_type)
        reservation.setdefault("previous_role", context.get("previous_role", "manual"))
        reservation.setdefault("conflicting_service", context.get("conflicting_service"))
        reservation.setdefault("service_was_active", None)
        reservation.setdefault("service_stopped", False)
        reservation.setdefault("restore_required", False)
        reservation.setdefault("restore_status", "NOT_REQUIRED")
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        if target:
            reservation["target"] = str(target)
        state["reservation"] = reservation
        _save_state(state)

    event_bus.publish_receiver(
        "INFO",
        "Receiver gereserveerd",
        f"{device['number']} is gereserveerd voor {key}",
        data=deepcopy(reservation),
    )
    return get_status()


def set_service_snapshot(
    *,
    mission_key: str,
    service_was_active: bool,
    service_stopped: bool = False,
) -> dict[str, Any]:
    """Store the pre-mission service state after the runtime inspected it."""
    key = str(mission_key or "").strip()
    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None or reservation.get("mission_key") != key:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["service_was_active"] = bool(service_was_active)
        reservation["service_stopped"] = bool(service_stopped)
        reservation["restore_required"] = bool(service_was_active)
        reservation["restore_status"] = (
            "PENDING" if service_was_active else "NOT_REQUIRED"
        )
        reservation["service_snapshot_at"] = _now()
        state["reservation"] = reservation
        _save_state(state)
    return get_status()



def set_service_group_snapshot(
    *,
    mission_key: str,
    service_group: dict[str, Any],
    service_snapshot: dict[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Store a complete service-group inspection for a reserved receiver.

    This records observed state and the intended handover plan. It performs no
    systemd changes. The existing single-service fields remain populated for
    backwards compatibility with v0.28.0d.
    """
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")
    group = deepcopy(service_group or {})
    snapshot = deepcopy(service_snapshot or {})
    services = snapshot.get("services", {})
    any_active = any(bool(item.get("was_active")) for item in services.values())

    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None or reservation.get("mission_key") != key:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["service_group"] = group
        reservation["service_snapshot"] = snapshot
        reservation["handover_mode"] = "DRY_RUN" if dry_run else "LIVE"
        reservation["handover_status"] = "INSPECTED"
        reservation["handover_inspected_at"] = _now()
        reservation["service_was_active"] = any_active
        reservation["service_stopped"] = False
        reservation["restore_required"] = any_active
        reservation["restore_status"] = "PENDING" if any_active else "NOT_REQUIRED"
        state["reservation"] = reservation
        _save_state(state)
    return get_status()

def mark_service_stopped(*, mission_key: str) -> dict[str, Any]:
    key = str(mission_key or "").strip()
    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None or reservation.get("mission_key") != key:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["service_stopped"] = True
        reservation["service_stopped_at"] = _now()
        state["reservation"] = reservation
        _save_state(state)
    return get_status()


def mark_restore_result(
    *,
    mission_key: str,
    success: bool,
    detail: str | None = None,
) -> dict[str, Any]:
    key = str(mission_key or "").strip()
    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None or reservation.get("mission_key") != key:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["restore_status"] = "RESTORED" if success else "FAILED"
        reservation["restored_at"] = _now()
        if detail:
            reservation["restore_detail"] = str(detail)
        state["reservation"] = reservation
        _save_state(state)
    return get_status()


def activate(*, mission_key: str, mission_id: str | None = None) -> dict[str, Any]:
    key = str(mission_key or "").strip()
    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None or reservation.get("mission_key") != key:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["status"] = "ACTIVE"
        reservation["activated_at"] = _now()
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        state["reservation"] = reservation
        _save_state(state)
    return get_status()


def release(*, mission_key: str | None = None, detail: str = "Missie afgerond") -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        reservation = state.get("reservation")
        if reservation is None:
            return get_status()
        if mission_key and reservation.get("mission_key") != mission_key:
            raise RuntimeError("Receiver-reservering hoort bij een andere missie")
        released = deepcopy(reservation)
        released["released_at"] = _now()
        released["release_detail"] = str(detail)
        released["status"] = "RELEASED"
        state["last_release"] = released
        state["reservation"] = None
        _save_state(state)

    event_bus.publish_receiver(
        "INFO",
        "Receiver vrijgegeven",
        str(detail),
        data=released,
    )
    return get_status()
