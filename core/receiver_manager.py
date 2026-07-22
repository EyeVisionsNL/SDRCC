#!/usr/bin/env python3

"""Central receiver assignment and runtime reservation state."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any
import json

from core import event_bus
from core.device_manager import get_device, get_devices, get_weather_device

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "receiver_manager.json"
_LOCK = RLock()

DEFAULT_STATE: dict[str, Any] = {
    "reservations": {},
    "last_releases": {},
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalise_state(data: Any) -> dict[str, Any]:
    """Return the v0.31 multi-reservation state, migrating legacy data."""
    state = deepcopy(DEFAULT_STATE)
    if not isinstance(data, dict):
        return state

    reservations = data.get("reservations")
    if isinstance(reservations, dict):
        for receiver_id, reservation in reservations.items():
            if isinstance(receiver_id, str) and isinstance(reservation, dict):
                item = deepcopy(reservation)
                item.setdefault("receiver_id", receiver_id)
                state["reservations"][receiver_id] = item
    else:
        legacy = data.get("reservation")
        if isinstance(legacy, dict) and legacy.get("receiver_id"):
            receiver_id = str(legacy["receiver_id"])
            state["reservations"][receiver_id] = deepcopy(legacy)

    last_releases = data.get("last_releases")
    if isinstance(last_releases, dict):
        for receiver_id, released in last_releases.items():
            if isinstance(receiver_id, str) and isinstance(released, dict):
                item = deepcopy(released)
                item.setdefault("receiver_id", receiver_id)
                item["status"] = "RELEASED"
                state["last_releases"][receiver_id] = item
    else:
        legacy = data.get("last_release")
        if isinstance(legacy, dict) and legacy.get("receiver_id"):
            receiver_id = str(legacy["receiver_id"])
            item = deepcopy(legacy)
            item["status"] = "RELEASED"
            state["last_releases"][receiver_id] = item

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
    temp.write_text(
        json.dumps(normalised, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
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


def _decorate_reservation(reservation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(reservation, dict):
        return None
    item = deepcopy(reservation)
    item["device"] = _device_summary(item.get("receiver_id"))
    return item


def get_status() -> dict[str, Any]:
    configured = get_weather_device()
    configured_id = configured.get("id") if configured else None
    with _LOCK:
        state = _load_state()

    raw_reservations = state.get("reservations", {})
    raw_releases = state.get("last_releases", {})
    reservations = {
        receiver_id: _decorate_reservation(reservation)
        for receiver_id, reservation in raw_reservations.items()
        if isinstance(reservation, dict)
    }
    last_releases = {}
    for receiver_id, released in raw_releases.items():
        if not isinstance(released, dict):
            continue
        item = deepcopy(released)
        item["status"] = "RELEASED"
        item["device"] = _device_summary(item.get("receiver_id") or receiver_id)
        last_releases[receiver_id] = item

    device_ids = [device["id"] for device in get_devices()]
    receivers = {}
    for receiver_id in device_ids:
        reservation = reservations.get(receiver_id)
        receivers[receiver_id] = {
            "device": _device_summary(receiver_id),
            "reservation": reservation,
            "last_release": last_releases.get(receiver_id),
            "available": reservation is None,
        }

    configured_reservation = reservations.get(configured_id) if configured_id else None
    configured_last_release = last_releases.get(configured_id) if configured_id else None

    return {
        "ok": True,
        "configured_receiver": _device_summary(configured_id),
        # Compatibility fields for existing single-runtime consumers.
        "reservation": configured_reservation,
        "last_release": configured_last_release,
        "available": configured_reservation is None,
        # Multi-receiver foundation fields.
        "receivers": receivers,
        "reservations": reservations,
        "last_releases": last_releases,
        "available_receivers": [
            receiver_id for receiver_id in device_ids
            if receiver_id not in reservations
        ],
    }


def is_available(receiver_id: str, *, mission_key: str | None = None) -> bool:
    receiver_id = str(receiver_id or "").strip()
    with _LOCK:
        reservation = _load_state().get("reservations", {}).get(receiver_id)
    if reservation is None:
        return True
    return bool(mission_key and reservation.get("mission_key") == mission_key)


def reserve(
    receiver_id: str,
    *,
    mission_key: str,
    mission_id: str | None = None,
    reason: str = "weather mission",
) -> dict[str, Any]:
    device = get_device(receiver_id)
    if device is None:
        raise ValueError(f"Onbekende receiver: {receiver_id}")
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")

    with _LOCK:
        state = _load_state()
        reservations = state["reservations"]
        current = reservations.get(receiver_id)

        for other_receiver, other in reservations.items():
            if other_receiver != receiver_id and other.get("mission_key") == key:
                raise RuntimeError("De missie is al aan een andere receiver gekoppeld")

        if current and current.get("mission_key") != key:
            raise RuntimeError(
                f"{receiver_id.upper()} is al gereserveerd "
                f"voor {current.get('mission_key', '-')}"
            )

        reservation = current or {
            "receiver_id": receiver_id,
            "mission_key": key,
            "reserved_at": _now(),
            "status": "RESERVED",
            "reason": str(reason),
        }
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        reservations[receiver_id] = reservation
        _save_state(state)

    event_data = deepcopy(reservation)
    event_data.update({
        "receiver_number": device["number"],
        "receiver_name": device["name"],
        "receiver_serial": device["serial"],
        "previous_status": "AVAILABLE",
        "current_status": "RESERVED",
    })
    event_bus.publish_receiver(
        "INFO",
        "Receiver gereserveerd",
        (
            f"{device['number']}: AVAILABLE → RESERVED · "
            f"owner {key} · {reservation.get('reason', '-')}"
        ),
        data=event_data,
    )
    return get_status()


def _find_reservation_by_mission(
    reservations: dict[str, dict[str, Any]], mission_key: str
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
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
        receiver_id, reservation = _find_reservation_by_mission(
            state["reservations"], key
        )
        if reservation is None or receiver_id is None:
            raise RuntimeError("Geen passende receiver-reservering gevonden")
        reservation["status"] = "ACTIVE"
        reservation["activated_at"] = _now()
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        state["reservations"][receiver_id] = reservation
        _save_state(state)

    device = get_device(receiver_id)
    event_data = deepcopy(reservation)
    event_data.update({
        "receiver_number": device["number"] if device else receiver_id.upper(),
        "receiver_name": device["name"] if device else receiver_id,
        "receiver_serial": device["serial"] if device else None,
        "previous_status": "RESERVED",
        "current_status": "ACTIVE",
    })
    event_bus.publish_receiver(
        "INFO",
        "Receiver missie actief",
        (
            f"{event_data['receiver_number']}: RESERVED → ACTIVE · "
            f"owner {key}"
        ),
        data=event_data,
    )
    return get_status()


def release(*, mission_key: str | None = None, detail: str = "Missie afgerond") -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        reservations = state["reservations"]
        if not reservations:
            return get_status()

        if mission_key:
            receiver_id, reservation = _find_reservation_by_mission(
                reservations, str(mission_key)
            )
            if reservation is None or receiver_id is None:
                raise RuntimeError("Geen receiver-reservering voor deze missie gevonden")
        elif len(reservations) == 1:
            receiver_id, reservation = next(iter(reservations.items()))
        else:
            raise RuntimeError(
                "Meerdere receiver-reserveringen actief; mission_key is verplicht"
            )

        released = deepcopy(reservation)
        released["released_at"] = _now()
        released["release_detail"] = str(detail)
        released["status"] = "RELEASED"
        state["last_releases"][receiver_id] = released
        reservations.pop(receiver_id, None)
        _save_state(state)

    device = get_device(receiver_id)
    event_data = deepcopy(released)
    event_data.update({
        "receiver_number": device["number"] if device else receiver_id.upper(),
        "receiver_name": device["name"] if device else receiver_id,
        "receiver_serial": device["serial"] if device else None,
        "previous_status": str(reservation.get("status") or "RESERVED").upper(),
        "current_status": "RELEASED",
    })
    event_bus.publish_receiver(
        "INFO",
        "Receiver vrijgegeven",
        (
            f"{event_data['receiver_number']}: "
            f"{event_data['previous_status']} → RELEASED · "
            f"owner {released.get('mission_key', '-')} · {detail}"
        ),
        data=event_data,
    )
    return get_status()
