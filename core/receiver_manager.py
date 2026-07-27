#!/usr/bin/env python3

"""Central receiver assignment and runtime reservation state.

Persistent runtime state uses canonical Receiver Registry IDs. Existing API
consumers keep receiving compatibility maps keyed by runtime aliases.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json

from core import event_bus
from core.device_manager import get_assigned_device, get_device, get_devices
from core.receiver_registry import resolve_id, resolve_runtime_id

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "receiver_manager.json"
_LOCK = RLock()

DEFAULT_STATE: dict[str, Any] = {"reservations": {}, "last_releases": {}}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _canonical_id(receiver_id: str | None) -> str | None:
    return resolve_id(receiver_id)


def _runtime_id(receiver_id: str | None) -> str | None:
    return resolve_runtime_id(receiver_id)


def _normalise_entry(receiver_id: str, value: dict[str, Any], *, released: bool = False):
    canonical = _canonical_id(value.get("receiver_id") or receiver_id)
    if canonical is None:
        return None, None
    item = deepcopy(value)
    item["receiver_id"] = canonical
    item["registry_id"] = canonical
    item["runtime_id"] = _runtime_id(canonical)
    if released:
        item["status"] = "RELEASED"
    return canonical, item


def _normalise_state(data: Any) -> dict[str, Any]:
    """Return canonical multi-reservation state and migrate legacy aliases."""
    state = deepcopy(DEFAULT_STATE)
    if not isinstance(data, dict):
        return state

    reservations = data.get("reservations")
    if isinstance(reservations, dict):
        for receiver_id, reservation in reservations.items():
            if isinstance(receiver_id, str) and isinstance(reservation, dict):
                canonical, item = _normalise_entry(receiver_id, reservation)
                if canonical and item:
                    state["reservations"][canonical] = item
    else:
        legacy = data.get("reservation")
        if isinstance(legacy, dict) and legacy.get("receiver_id"):
            canonical, item = _normalise_entry(str(legacy["receiver_id"]), legacy)
            if canonical and item:
                state["reservations"][canonical] = item

    last_releases = data.get("last_releases")
    if isinstance(last_releases, dict):
        for receiver_id, released in last_releases.items():
            if isinstance(receiver_id, str) and isinstance(released, dict):
                canonical, item = _normalise_entry(receiver_id, released, released=True)
                if canonical and item:
                    state["last_releases"][canonical] = item
    else:
        legacy = data.get("last_release")
        if isinstance(legacy, dict) and legacy.get("receiver_id"):
            canonical, item = _normalise_entry(str(legacy["receiver_id"]), legacy, released=True)
            if canonical and item:
                state["last_releases"][canonical] = item
    return state


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    try:
        return _normalise_state(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    except Exception:
        return deepcopy(DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    normalised = _normalise_state(state)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(normalised, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _device_summary(device_id: str | None) -> dict[str, Any] | None:
    if not device_id:
        return None
    device = get_device(device_id)
    if device is None:
        return {"id": device_id, "number": str(device_id).upper(), "missing": True}
    return {
        "id": device["id"],
        "runtime_id": device["runtime_id"],
        "registry_id": device["registry_id"],
        "canonical_id": device["canonical_id"],
        "number": device["number"],
        "name": device["name"],
        "serial": device["serial"],
    }


def _decorate_reservation(reservation: dict[str, Any] | None):
    if not isinstance(reservation, dict):
        return None
    item = deepcopy(reservation)
    canonical = _canonical_id(item.get("receiver_id"))
    item["receiver_id"] = canonical
    item["registry_id"] = canonical
    item["runtime_id"] = _runtime_id(canonical)
    item["device"] = _device_summary(canonical)
    return item


def _compatibility_map(canonical_map: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for canonical, value in canonical_map.items():
        runtime = _runtime_id(canonical)
        if runtime:
            result[runtime] = value
    return result


def get_status() -> dict[str, Any]:
    configured = get_assigned_device("weather")
    configured_runtime = configured.get("runtime_id") if configured else None
    configured_canonical = configured.get("registry_id") if configured else None
    with _LOCK:
        state = _load_state()

    canonical_reservations = {
        canonical: _decorate_reservation(reservation)
        for canonical, reservation in state.get("reservations", {}).items()
        if isinstance(reservation, dict)
    }
    canonical_last_releases = {
        canonical: _decorate_reservation(released)
        for canonical, released in state.get("last_releases", {}).items()
        if isinstance(released, dict)
    }
    reservations = _compatibility_map(canonical_reservations)
    last_releases = _compatibility_map(canonical_last_releases)

    receivers = {}
    canonical_receivers = {}
    for device in get_devices():
        runtime = device["runtime_id"]
        canonical = device["registry_id"]
        reservation = canonical_reservations.get(canonical)
        entry = {
            "device": _device_summary(canonical),
            "reservation": reservation,
            "last_release": canonical_last_releases.get(canonical),
            "available": reservation is None,
        }
        receivers[runtime] = entry
        canonical_receivers[canonical] = entry

    configured_reservation = canonical_reservations.get(configured_canonical)
    configured_last_release = canonical_last_releases.get(configured_canonical)
    return {
        "ok": True,
        "version": "0.49.0c1",
        "identity_authority": "receiver_registry",
        "state_identity": "canonical",
        "configured_receiver": _device_summary(configured_canonical or configured_runtime),
        "reservation": configured_reservation,
        "last_release": configured_last_release,
        "available": configured_reservation is None,
        # Existing compatibility contract.
        "receivers": receivers,
        "reservations": reservations,
        "last_releases": last_releases,
        "available_receivers": [rid for rid, entry in receivers.items() if entry["available"]],
        # Canonical contract for new consumers.
        "canonical_receivers": canonical_receivers,
        "canonical_reservations": canonical_reservations,
        "canonical_last_releases": canonical_last_releases,
        "available_registry_receivers": [rid for rid, entry in canonical_receivers.items() if entry["available"]],
    }


def is_available(receiver_id: str, *, mission_key: str | None = None) -> bool:
    canonical = _canonical_id(receiver_id)
    if canonical is None:
        return False
    with _LOCK:
        reservation = _load_state().get("reservations", {}).get(canonical)
    return reservation is None or bool(mission_key and reservation.get("mission_key") == mission_key)


def reserve(receiver_id: str, *, mission_key: str, mission_id: str | None = None, reason: str = "weather mission") -> dict[str, Any]:
    device = get_device(receiver_id)
    if device is None:
        raise ValueError(f"Onbekende receiver: {receiver_id}")
    canonical = device["registry_id"]
    runtime = device["runtime_id"]
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")

    with _LOCK:
        state = _load_state()
        reservations = state["reservations"]
        current = reservations.get(canonical)
        for other_receiver, other in reservations.items():
            if other_receiver != canonical and other.get("mission_key") == key:
                raise RuntimeError("De missie is al aan een andere receiver gekoppeld")
        if current and current.get("mission_key") != key:
            raise RuntimeError(f"{device['number']} is al gereserveerd voor {current.get('mission_key', '-')}")
        reservation = current or {
            "receiver_id": canonical,
            "registry_id": canonical,
            "runtime_id": runtime,
            "mission_key": key,
            "reserved_at": _now(),
            "status": "RESERVED",
            "reason": str(reason),
        }
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        reservations[canonical] = reservation
        _save_state(state)

    event_data = deepcopy(reservation)
    event_data.update({"receiver_number": device["number"], "receiver_name": device["name"], "receiver_serial": device["serial"], "previous_status": "AVAILABLE", "current_status": "RESERVED"})
    event_bus.publish_receiver("INFO", "Receiver gereserveerd", f"{device['number']}: AVAILABLE → RESERVED · owner {key} · {reservation.get('reason', '-')}", data=event_data)
    return get_status()


def _find_reservation_by_mission(reservations: dict[str, dict[str, Any]], mission_key: str):
    for receiver_id, reservation in reservations.items():
        if reservation.get("mission_key") == mission_key:
            return receiver_id, reservation
    return None, None


def activate(*, mission_key: str, mission_id: str | None = None) -> dict[str, Any]:
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")
    with _LOCK:
        state = _load_state()
        canonical, reservation = _find_reservation_by_mission(state["reservations"], key)
        if reservation is None or canonical is None:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["status"] = "ACTIVE"
        reservation["activated_at"] = _now()
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        state["reservations"][canonical] = reservation
        _save_state(state)

    device = get_device(canonical)
    event_data = deepcopy(reservation)
    event_data.update({"receiver_number": device["number"] if device else canonical.upper(), "receiver_name": device["name"] if device else canonical, "receiver_serial": device["serial"] if device else None, "previous_status": "RESERVED", "current_status": "ACTIVE"})
    event_bus.publish_receiver("INFO", "Receiver missie actief", f"{event_data['receiver_number']}: RESERVED → ACTIVE · owner {key}", data=event_data)
    return get_status()


def release(*, mission_key: str | None = None, detail: str = "Missie afgerond") -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        reservations = state["reservations"]
        if not reservations:
            return get_status()
        if mission_key:
            canonical, reservation = _find_reservation_by_mission(reservations, str(mission_key))
            if reservation is None or canonical is None:
                raise RuntimeError("Geen receiver-reservering voor deze missie gevonden")
        elif len(reservations) == 1:
            canonical, reservation = next(iter(reservations.items()))
        else:
            raise RuntimeError("Meerdere receiver-reserveringen actief; mission_key is verplicht")
        released = deepcopy(reservation)
        released["released_at"] = _now()
        released["release_detail"] = str(detail)
        released["status"] = "RELEASED"
        state["last_releases"][canonical] = released
        reservations.pop(canonical, None)
        _save_state(state)

    device = get_device(canonical)
    event_data = deepcopy(released)
    event_data.update({"receiver_number": device["number"] if device else canonical.upper(), "receiver_name": device["name"] if device else canonical, "receiver_serial": device["serial"] if device else None, "previous_status": str(reservation.get("status") or "RESERVED").upper(), "current_status": "RELEASED"})
    event_bus.publish_receiver("INFO", "Receiver vrijgegeven", f"{event_data['receiver_number']}: {event_data['previous_status']} → RELEASED · owner {released.get('mission_key', '-')} · {detail}", data=event_data)
    return get_status()
