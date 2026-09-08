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
from typing import Any, Callable, Iterable
import json
import time

from core import event_bus
from core.device_manager import get_assigned_device, get_device, get_devices
from core.receiver_registry import resolve_id, resolve_runtime_id

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "receiver_manager.json"
_LOCK = RLock()

DEFAULT_STATE: dict[str, Any] = {"reservations": {}, "last_releases": {}}

VERSION = "0.54.0b"
ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, int], bool]


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

    state["hardware_recovery"] = deepcopy(data.get("hardware_recovery") or {})
    state["binding_transaction"] = deepcopy(data.get("binding_transaction"))
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


def _validate_state_document(data: Any) -> None:
    """Reject malformed persisted ownership instead of silently dropping it."""
    if not isinstance(data, dict):
        raise ValueError("top-level state moet een object zijn")
    for plural, singular in (
        ("reservations", "reservation"),
        ("last_releases", "last_release"),
    ):
        if plural in data:
            values = data[plural]
            if not isinstance(values, dict):
                raise ValueError(f"{plural} moet een object zijn")
            entries = list(values.items())
        elif singular in data:
            value = data[singular]
            if value is None or value == {}:
                entries = []
            elif isinstance(value, dict):
                entries = [(str(value.get("receiver_id") or ""), value)]
            else:
                raise ValueError(f"{singular} moet een object zijn")
        else:
            entries = []
        for receiver_id, entry in entries:
            if not isinstance(receiver_id, str) or not receiver_id:
                raise ValueError(f"{plural} bevat een ongeldige receiver-id")
            if not isinstance(entry, dict):
                raise ValueError(f"{plural}.{receiver_id} moet een object zijn")
            identity = entry.get("receiver_id") or receiver_id
            if _canonical_id(str(identity)) is None:
                raise ValueError(f"{plural}.{receiver_id} heeft een onbekende receiver")
            if (
                "handover" in entry
                and entry.get("handover") is not None
                and not isinstance(entry.get("handover"), dict)
            ):
                raise ValueError(f"{plural}.{receiver_id}.handover moet een object zijn")


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    try:
        document = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        _validate_state_document(document)
        return _normalise_state(document)
    except Exception as error:
        raise RuntimeError(
            f"Receiver Manager state is onleesbaar: {STATE_FILE}: {error}"
        ) from error


def _save_state(state: dict[str, Any]) -> None:
    normalised = _normalise_state(state)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(normalised, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _result_ok(result: Any) -> bool:
    if result is True:
        return True
    if isinstance(result, dict):
        if "ok" in result:
            return bool(result.get("ok"))
        return int(result.get("returncode", 1)) == 0
    return int(getattr(result, "returncode", 1)) == 0


def _result_error(result: Any) -> str:
    if isinstance(result, dict):
        return str(
            result.get("message")
            or result.get("stderr")
            or result.get("error")
            or "service action failed"
        ).strip()
    return str(getattr(result, "stderr", "") or "service action failed").strip()


def _normalise_services(services: Iterable[str] | None) -> list[str]:
    result: list[str] = []
    for value in services or ():
        service = str(value or "").strip()
        if not service or service in result:
            continue
        if not service.endswith(".service") or "/" in service:
            raise ValueError(f"Ongeldige handover-service: {value!r}")
        result.append(service)
    return result


def _reservation_for_mission(
    state: dict[str, Any], mission_key: str,
) -> tuple[str | None, dict[str, Any] | None]:
    return _find_reservation_by_mission(state.get("reservations", {}), mission_key)


def _update_handover(
    mission_key: str,
    updater: Callable[[dict[str, Any], dict[str, Any]], None],
) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
        canonical, reservation = _reservation_for_mission(state, mission_key)
        if canonical is None or reservation is None:
            raise RuntimeError("Geen passende receiver-handover gevonden")
        handover = reservation.get("handover")
        if not isinstance(handover, dict):
            raise RuntimeError("Receiver-reservering bevat geen handovercontext")
        updater(reservation, handover)
        handover["updated_at"] = _now()
        reservation["handover"] = handover
        state["reservations"][canonical] = reservation
        _save_state(state)
        return deepcopy(reservation)


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
        "presence": device.get("presence", "UNKNOWN"),
        "present": device.get("present", False),
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
            "available": reservation is None and hardware_ready(canonical),
        }
        receivers[runtime] = entry
        canonical_receivers[canonical] = entry

    configured_reservation = canonical_reservations.get(configured_canonical)
    configured_last_release = canonical_last_releases.get(configured_canonical)
    return {
        "ok": True,
        "version": VERSION,
        "identity_authority": "receiver_registry",
        "handover_authority": "receiver_manager",
        "handover_state_file": str(STATE_FILE),
        "state_identity": "canonical",
        "configured_receiver": _device_summary(configured_canonical or configured_runtime),
        "reservation": configured_reservation,
        "last_release": configured_last_release,
        "available": configured_reservation is None and hardware_ready(configured_canonical),
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
        "attention_required": any(
            str(item.get("status") or "").upper() == "ATTENTION"
            for item in canonical_reservations.values()
        ),
    }


def is_available(receiver_id: str, *, mission_key: str | None = None) -> bool:
    canonical = _canonical_id(receiver_id)
    if canonical is None or not hardware_ready(canonical):
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
        if not hardware_ready(canonical):
            raise RuntimeError("Receiver hardware is missing, unbound or requires recovery")
        state = _load_state()
        reservations = state["reservations"]
        current = reservations.get(canonical)
        for other_receiver, other in reservations.items():
            if other_receiver != canonical and other.get("mission_key") == key:
                raise RuntimeError("De missie is al aan een andere receiver gekoppeld")
        if current and current.get("mission_key") != key:
            raise RuntimeError(f"{device['number']} is al gereserveerd voor {current.get('mission_key', '-')}")
        created = current is None
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

    if created:
        event_data = deepcopy(reservation)
        event_data.update({"receiver_number": device["number"], "receiver_name": device["name"], "receiver_serial": device["serial"], "previous_status": "AVAILABLE", "current_status": "RESERVED"})
        event_bus.publish_receiver("INFO", "Receiver reserved", f"{device['number']}: AVAILABLE → RESERVED · owner {key} · {reservation.get('reason', '-')}", data=event_data)
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
        previous_status = str(reservation.get("status") or "RESERVED").upper()
        if not hardware_ready(canonical):
            raise RuntimeError("Receiver hardware disappeared before activation")
        reservation["status"] = "ACTIVE"
        reservation["activated_at"] = _now()
        if isinstance(reservation.get("handover"), dict):
            reservation["handover"]["status"] = "ACTIVE"
            reservation["handover"]["activated_at"] = reservation["activated_at"]
            reservation["handover"]["updated_at"] = reservation["activated_at"]
        if mission_id:
            reservation["mission_id"] = str(mission_id)
        state["reservations"][canonical] = reservation
        _save_state(state)

    if previous_status != "ACTIVE":
        device = get_device(canonical)
        event_data = deepcopy(reservation)
        event_data.update({"receiver_number": device["number"] if device else canonical.upper(), "receiver_name": device["name"] if device else canonical, "receiver_serial": device["serial"] if device else None, "previous_status": previous_status, "current_status": "ACTIVE"})
        event_bus.publish_receiver("INFO", "Receiver mission active", f"{event_data['receiver_number']}: {previous_status} → ACTIVE · owner {key}", data=event_data)
    return get_status()


def begin_handover(
    receiver_id: str,
    *,
    mission_key: str,
    mission_id: str | None = None,
    reason: str = "receiver handover",
    services: Iterable[str] | None,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
    previous_profile: str | None = None,
    release_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    """Reserve a receiver and persist exactly what SDRCC stops.

    Service control remains injected by the existing privileged caller.  The
    Receiver Manager owns ordering, durable intent and the restore decision.
    """
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")
    ordered_services = _normalise_services(services)
    device = get_device(receiver_id)
    if device is None:
        raise ValueError(f"Onbekende receiver: {receiver_id}")

    reserve(
        device["id"],
        mission_key=key,
        mission_id=mission_id,
        reason=reason,
    )

    with _LOCK:
        state = _load_state()
        canonical, reservation = _reservation_for_mission(state, key)
        if canonical is None or reservation is None:
            raise RuntimeError("Receiver-reservering ontbreekt na reserve")
        existing = reservation.get("handover")
        if isinstance(existing, dict):
            status = str(existing.get("status") or "").upper()
            if status in {"READY", "ACTIVE"}:
                return get_status()
            if status not in {"RESTORED"}:
                raise RuntimeError(
                    f"Receiver-handover vereist aandacht ({status or 'UNKNOWN'})"
                )

        reservation["handover"] = {
            "version": VERSION,
            "status": "OBSERVING",
            "started_at": _now(),
            "updated_at": _now(),
            "receiver_id": reservation.get("receiver_id"),
            "runtime_id": reservation.get("runtime_id"),
            "mission_key": key,
            "mission_id": mission_id or reservation.get("mission_id"),
            "reason": str(reason),
            "previous_profile": str(previous_profile).strip() if previous_profile else None,
            "stop_order": list(ordered_services),
            "restore_order": list(reversed(ordered_services)),
            "services": [],
            "receiver_release_verified": False,
            "restore_errors": [],
        }
        reservation["status"] = "HANDOVER"
        state["reservations"][canonical] = reservation
        _save_state(state)

    observations: list[dict[str, Any]] = []
    try:
        for index, service in enumerate(ordered_services):
            observed = service_state(service)
            if not isinstance(observed, dict) or "active" not in observed:
                raise RuntimeError(f"Status van {service} kon niet worden vastgesteld")
            observations.append({
                "service": service,
                "stop_order": index + 1,
                "restore_order": len(ordered_services) - index,
                "original_state": str(observed.get("state") or "unknown"),
                "was_active": bool(observed.get("active")),
                "stopped_by_sdrcc": False,
                "stop_status": "PENDING" if observed.get("active") else "NOT_REQUIRED",
                "restore_status": "PENDING" if observed.get("active") else "NOT_REQUIRED",
            })

        def initialise(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
            handover["status"] = "STOPPING"
            handover["services"] = deepcopy(observations)
            reservation["status"] = "HANDOVER"

        _update_handover(key, initialise)

        for service in ordered_services:
            entry = next(item for item in observations if item["service"] == service)
            if not entry["was_active"]:
                continue

            def record_stop_intent(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
                item = next(
                    value for value in handover["services"]
                    if value["service"] == service
                )
                item["stop_status"] = "STOPPING"
                item["stop_requested_at"] = _now()
                reservation["status"] = "HANDOVER"

            _update_handover(key, record_stop_intent)
            result = service_action("stop", service)
            inactive = bool(wait_for_service(service, "inactive", 15))

            def record_stop(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
                item = next(
                    value for value in handover["services"]
                    if value["service"] == service
                )
                item["stopped_by_sdrcc"] = inactive
                item["stop_status"] = "STOPPED" if inactive else "FAILED"
                item["stopped_at"] = _now() if inactive else None
                if not _result_ok(result):
                    item["stop_error"] = _result_error(result)
                reservation["status"] = "HANDOVER"

            _update_handover(key, record_stop)
            if not _result_ok(result) or not inactive:
                raise RuntimeError(
                    f"{service} kon niet veilig worden gestopt"
                    + (f": {_result_error(result)}" if not _result_ok(result) else "")
                )

        time.sleep(max(0.0, float(release_delay_seconds)))
        for service in ordered_services:
            current = service_state(service)
            original = next(item for item in observations if item["service"] == service)
            if bool(current.get("active")):
                raise RuntimeError(f"{service} claimt de receiver opnieuw na stop")

        def mark_ready(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
            handover["status"] = "READY"
            handover["receiver_release_verified"] = True
            handover["receiver_release_verified_at"] = _now()
            reservation["status"] = "RESERVED"

        _update_handover(key, mark_ready)
        event_bus.publish_receiver(
            "SUCCESS",
            "Receiver handover ready",
            f"{device['number']} was safely released for {key}",
            data={
                "receiver_id": device["id"],
                "mission_key": key,
                "stopped_services": [
                    item["service"] for item in observations if item["was_active"]
                ],
            },
        )
        return get_status()
    except Exception as error:
        try:
            def mark_failed(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
                handover["status"] = "ATTENTION"
                handover["error"] = str(error)
                reservation["status"] = "ATTENTION"

            _update_handover(key, mark_failed)
        except Exception:
            pass
        recovery = restore_handover(
            mission_key=key,
            service_state=service_state,
            service_action=service_action,
            wait_for_service=wait_for_service,
            detail="Handover preparation failed",
        )
        if not recovery.get("ok"):
            raise RuntimeError(
                f"{error}; herstel vereist aandacht: "
                + "; ".join(recovery.get("errors") or [])
            ) from error
        raise


def restore_handover(
    *,
    mission_key: str,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
    detail: str = "Receiver context restored",
) -> dict[str, Any]:
    """Restore only services observed active and stopped by SDRCC."""
    key = str(mission_key or "").strip()
    if not key:
        raise ValueError("mission_key ontbreekt")
    with _LOCK:
        state = _load_state()
        canonical, reservation = _reservation_for_mission(state, key)
        if canonical is None or reservation is None:
            released = next((
                item for item in state.get("last_releases", {}).values()
                if isinstance(item, dict) and item.get("mission_key") == key
            ), None)
            return {
                "ok": released is not None,
                "already_restored": released is not None,
                "released": deepcopy(released),
                "errors": [] if released is not None else ["handover not found"],
            }
        handover = reservation.get("handover")
        if not isinstance(handover, dict):
            return {"ok": False, "errors": ["reservation has no handover context"]}
        services = deepcopy(handover.get("services") or [])
        previous_profile = handover.get("previous_profile")

    device = get_device(canonical)
    if device and device.get("presence") == "MISSING":
        with _LOCK:
            stored = _load_state()
            pending = stored.setdefault("hardware_recovery", {}).setdefault(canonical, {"services": [], "status": "WAITING"})
            for item in services:
                if item.get("was_active") and (item.get("stopped_by_sdrcc") or item.get("stop_status") in {"STOPPING", "STOPPED"}):
                    if item["service"] not in pending["services"]:
                        pending["services"].append(item["service"])
            stored["reservations"][canonical]["handover"]["status"] = "DEFERRED_HARDWARE"
            _save_state(stored)
        release(mission_key=key, detail="Executor stopped; service restoration deferred until hardware returns")
        return {"ok": True, "released": True, "deferred": True, "errors": []}

    def mark_restoring(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
        handover["status"] = "RESTORING"
        handover["restore_started_at"] = _now()
        reservation["status"] = "RESTORING"

    _update_handover(key, mark_restoring)
    errors: list[str] = []
    restore_blocked = False

    for item in sorted(services, key=lambda value: int(value.get("restore_order") or 0)):
        restore_intent = bool(item.get("stopped_by_sdrcc")) or str(
            item.get("stop_status") or ""
        ).upper() in {"STOPPING", "STOPPED"}
        if not item.get("was_active") or not restore_intent:
            continue
        service = str(item.get("service") or "")
        if restore_blocked:
            errors.append(f"{service}: geblokkeerd na eerdere herstelfout")

            def record_blocked(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
                stored = next(
                    value for value in handover["services"]
                    if value["service"] == service
                )
                stored["restore_status"] = "BLOCKED"
                stored["restore_error"] = errors[-1]

            _update_handover(key, record_blocked)
            continue
        current = service_state(service)
        already_active = bool(current.get("active"))
        result = True if already_active else service_action("start", service)
        active = already_active or bool(wait_for_service(service, "active", 15))
        ok = _result_ok(result) and active
        if not ok:
            errors.append(f"{service}: {_result_error(result) if not _result_ok(result) else 'werd niet actief'}")
            restore_blocked = True

        def record_restore(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
            stored = next(
                value for value in handover["services"]
                if value["service"] == service
            )
            stored["restore_status"] = (
                "ALREADY_ACTIVE" if already_active and ok else
                "RESTORED" if ok else "FAILED"
            )
            stored["restored_at"] = _now() if ok else None
            if not ok:
                stored["restore_error"] = errors[-1]

        _update_handover(key, record_restore)

    if previous_profile:
        try:
            from core import state as receiver_state
            receiver_state.set_sdr2_state(
                status="idle",
                profile=str(previous_profile),
                locked=False,
                process=None,
            )
        except Exception as error:
            errors.append(f"profile {previous_profile}: {error}")

    if errors:
        def mark_attention(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
            handover["status"] = "ATTENTION"
            handover["restore_errors"] = list(errors)
            handover["restore_failed_at"] = _now()
            reservation["status"] = "ATTENTION"

        _update_handover(key, mark_attention)
        event_bus.publish_receiver(
            "ERROR",
            "Receiver handover requires attention",
            "; ".join(errors),
            data={"mission_key": key, "receiver_id": _runtime_id(canonical)},
        )
        return {"ok": False, "attention": True, "released": False, "errors": errors}

    def mark_restored(reservation: dict[str, Any], handover: dict[str, Any]) -> None:
        handover["status"] = "RESTORED"
        handover["restored_at"] = _now()
        handover["restore_errors"] = []
        reservation["status"] = "RESTORED"

    _update_handover(key, mark_restored)
    release(mission_key=key, detail=detail)
    event_bus.publish_receiver(
        "SUCCESS",
        "Receiver handover restored",
        f"Receiver context for {key} was fully restored",
        data={"mission_key": key, "receiver_id": _runtime_id(canonical)},
    )
    return {"ok": True, "attention": False, "released": True, "errors": []}


def recover_handovers(
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
    active_mission_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Restore unfinished handovers before stale reservations are released."""
    active = {str(value) for value in active_mission_keys or () if str(value)}
    with _LOCK:
        reservations = deepcopy(_load_state().get("reservations", {}))
    results = []
    for reservation in reservations.values():
        if not isinstance(reservation, dict):
            continue
        key = str(reservation.get("mission_key") or "").strip()
        handover = reservation.get("handover")
        if not key or key in active or not isinstance(handover, dict):
            continue
        results.append({
            "mission_key": key,
            **restore_handover(
                mission_key=key,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
                detail="Receiver context restored after runtime recovery",
            ),
        })
    return {
        "ok": all(item.get("ok") for item in results),
        "recovered": len([item for item in results if item.get("ok")]),
        "attention": len([item for item in results if not item.get("ok")]),
        "results": results,
    }


def service_action_block(plugin_id: str, action: str) -> dict[str, Any] | None:
    """Block Start/Restart when the assigned receiver is reserved."""
    operation = str(action or "").strip().lower()
    if operation not in {"start", "restart"}:
        return None
    device = get_assigned_device(plugin_id)
    if device is None:
        return {
            "reason": "receiver_assignment_missing",
            "plugin_id": str(plugin_id),
            "action": operation,
        }
    canonical = device["registry_id"]
    if not hardware_ready(canonical):
        return {"reason": "hardware_unavailable", "message": "Receiver hardware is missing, unbound or requires recovery"}
    with _LOCK:
        reservation = deepcopy(_load_state().get("reservations", {}).get(canonical))
    if not isinstance(reservation, dict):
        return None
    return {
        "reason": "receiver_reserved",
        "plugin_id": str(plugin_id),
        "action": operation,
        "receiver_id": device["runtime_id"],
        "receiver_number": device["number"],
        "mission_key": reservation.get("mission_key"),
        "reservation_status": reservation.get("status"),
        "message": (
            f"{device['number']} is gereserveerd voor "
            f"{reservation.get('mission_key') or 'een actieve missie'}; "
            f"{str(plugin_id).upper()} {operation} is geblokkeerd."
        ),
    }


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
        handover = reservation.get("handover")
        if isinstance(handover, dict) and str(handover.get("status") or "").upper() not in {"RESTORED", "DEFERRED_HARDWARE"}:
            raise RuntimeError(
                "Receiver kan niet worden vrijgegeven voordat de handover volledig is hersteld"
            )
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
    event_bus.publish_receiver("INFO", "Receiver released", f"{event_data['receiver_number']}: {event_data['previous_status']} → RELEASED · owner {released.get('mission_key', '-')} · {detail}", data=event_data)
    return get_status()


# Hardware lifecycle belongs to this existing manager. GET snapshots never bind.
_binding_message = 'Waiting for hardware observation'
_previous_active = {}
_tick_lock = RLock()


def hardware_ready(receiver_id):
    device = get_device(receiver_id)
    if not device or not device.get('present'):
        return False
    with _LOCK:
        state = _load_state()
        return not state.get('binding_transaction') and device['registry_id'] not in state.get('hardware_recovery', {})


def binding_status():
    with _LOCK:
        state = _load_state()
        return {'message': _binding_message, 'transaction': bool(state.get('binding_transaction')),
                'recovery': deepcopy(state.get('hardware_recovery', {}))}


def service_control_serialized(function):
    """Prevent a dashboard service start racing a hardware binding commit."""
    from functools import wraps
    @wraps(function)
    def wrapped(*args, **kwargs):
        with _LOCK:
            return function(*args, **kwargs)
    return wrapped


def bind_hardware(*, privileged_apply, service_state, mapping=None):
    """Idempotent registry transaction with a durable external-sync intent.

    Existing privileged adapter owns AIS/readsb files, service preservation and
    rollback. On interruption the intent blocks new work until an idempotent retry
    completes; no blank serial is ever passed to an executor.
    """
    global _binding_message
    from core import receiver_registry, receiver_hardware, receiver_authority, config
    from core.device_manager import get_conflicting_services
    with _LOCK:
        snapshot = receiver_hardware.scan(refresh=True)
        if not snapshot['ok'] or snapshot['ambiguous']:
            raise RuntimeError(snapshot['error'] or 'USB identity is ambiguous')
        state = _load_state()
        rows = receiver_registry.get_receivers(include_disabled=True)
        current = {r['id']: r['serial'] for r in rows}
        enabled = {r['id']: r for r in rows if r['enabled']}
        devices = {r['serial'] for r in snapshot['receivers'] if r['serial']}
        pending = state.get('binding_transaction')
        if pending and current not in (pending['previous'], {**pending['previous'], **pending['mapping']}):
            raise RuntimeError('Registry changed during pending binding; review configuration')
        if pending and mapping is None:
            changes = pending['mapping']
        elif mapping is not None:
            if not isinstance(mapping, dict) or not mapping:
                raise ValueError('Select at least one receiver and serial')
            changes = {}
            for key, value in mapping.items():
                if key not in enabled or not isinstance(value, str) or value not in devices:
                    raise ValueError('Select an enabled receiver and a currently present serial')
                changes[key] = value
        else:
            vacant = [key for key in enabled if not current[key] or current[key] not in devices]
            new = sorted(devices - {v for v in current.values() if v})
            # Preserve retained receivers. For two entirely new receivers, sorted
            # serials provide stable first binding independent of USB enumeration.
            if not vacant or not new:
                _binding_message = 'Bindings retained; waiting for missing hardware' if vacant else 'Hardware bindings ready'
                return {'ok': True, 'changed': False}
            if len(vacant) != len(new):
                _binding_message = 'ACTION_REQUIRED: select the receiver bindings below'
                return {'ok': False, 'changed': False, 'message': _binding_message}
            changes = dict(zip(vacant, new))
        candidate = {**current, **changes}
        bound = [value for value in candidate.values() if value]
        if len(bound) != len(set(bound)):
            raise ValueError('A physical serial cannot belong to two slots')
        if any(value not in devices for value in changes.values()):
            raise RuntimeError('Pending replacement is no longer connected')
        changed = [key for key in changes if candidate[key] != current[key]]
        if not changed and not pending:
            return {'ok': True, 'changed': False}
        if state['reservations']:
            raise RuntimeError('Waiting for the existing mission/session to release its reservation')
        for key in changed:
            for service in get_conflicting_services(key):
                observation = service_state(service)
                if observation.get('state') not in {'inactive', 'failed'}:
                    raise RuntimeError(f'{service}: stop reception before changing this binding')
        state['binding_transaction'] = {'mapping': changes, 'previous': current, 'started_at': _now()} if mapping is not None else (pending or {'mapping': changes, 'previous': current, 'started_at': _now()})
        _save_state(state)
        # Missing service roles do not prevent HF/mission-only stations binding.
        assignments = config.get_receiver_assignments()
        ids = {role: resolve_id(assignments.get(role)) for role in ('ais', 'adsb')}
        serials = {role: candidate.get(key, '') for role, key in ids.items()}
        if all(serials.values()):
            result = privileged_apply(serials['ais'], serials['adsb'])
            if not result.get('ok'):
                _binding_message = 'ACTION_REQUIRED: ' + str(result.get('message', 'External service configuration failed'))
                raise RuntimeError(_binding_message)
        receiver_registry.write_bindings(candidate)
        receiver_authority.invalidate_cache()
        state = _load_state()
        state['binding_transaction'] = None
        _save_state(state)
        _binding_message = 'Hardware bindings updated; roles and reception settings preserved'
        return {'ok': True, 'changed': True, 'bindings': candidate}


def hardware_tick(*, service_state, service_action, wait_for_service, stop_receiver, privileged_apply):
    """One bounded observation/recovery cycle, invoked by the dashboard worker."""
    global _binding_message, _previous_active
    from core import receiver_hardware
    from core.device_manager import get_conflicting_services
    with _tick_lock:
        snapshot = receiver_hardware.scan(refresh=True)
        if not snapshot['ok'] or snapshot['ambiguous']:
            _binding_message = snapshot['error'] or 'UNKNOWN USB state'
            return
        devices = get_devices()
        for device in devices:
            key = device['registry_id']
            services = get_conflicting_services(key)
            observations = {name: service_state(name) for name in services}
            active = [name for name, item in observations.items() if item.get('active')]
            if device['presence'] == 'PRESENT':
                _previous_active[key] = active
                continue
            if device['presence'] != 'MISSING':
                continue
            with _LOCK:
                state = _load_state()
                recoveries = state.setdefault('hardware_recovery', {})
                recovery = recoveries.setdefault(key, {'services': [], 'status': 'WAITING'})
                for service in active + _previous_active.get(key, []):
                    if service not in recovery['services']: recovery['services'].append(service)
                reservation = deepcopy(state['reservations'].get(key))
                _save_state(state)
            # Executor stop runs outside the manager lock: watcher cleanup needs it.
            stop_receiver(key, reservation)
            for service in services:
                if observations[service].get('state') not in {'inactive', 'failed'} or observations[service].get('active'):
                    result = service_action('stop', service)
                    if not _result_ok(result) or not wait_for_service(service, 'inactive', 15):
                        raise RuntimeError(f'{service}: hardware-loss stop failed')
            _previous_active[key] = []
        bind_hardware(privileged_apply=privileged_apply, service_state=service_state)
        # Restore only the services retained in the manager's recovery intent.
        with _LOCK:
            state = _load_state()
            if state.get('binding_transaction'): return
            for key in list(state.get('hardware_recovery', {})):
                device = get_device(key)
                if not device or not device.get('present') or key in state['reservations']:
                    continue
                recovery = state['hardware_recovery'][key]
                for service in sorted(recovery['services'], key=lambda name: (name.endswith('-control.service'), name)):
                    result = service_action('start', service)
                    if not _result_ok(result) or not wait_for_service(service, 'active', 15):
                        recovery['status'] = 'ACTION_REQUIRED'
                        _save_state(state)
                        raise RuntimeError(f'{service}: restart failed; recovery intent retained')
                    recovery['services'].remove(service)
                    _save_state(state)
                del state['hardware_recovery'][key]
                _save_state(state)


def cancel_service_recovery(plugin_id):
    """An explicit operator Stop cancels queued automatic service restoration."""
    from core.device_manager import get_role_handover_services
    cancelled = set(get_role_handover_services(plugin_id))
    with _LOCK:
        state = _load_state()
        for recovery in state.get('hardware_recovery', {}).values():
            recovery['services'] = [name for name in recovery['services'] if name not in cancelled]
        for key in _previous_active:
            _previous_active[key] = [name for name in _previous_active[key] if name not in cancelled]
        _save_state(state)


def defer_missing_service(service):
    """Let existing controller cleanup defer its exact prior service intent."""
    from core.device_manager import get_conflicting_services
    with _LOCK:
        for device in get_devices():
            if service in get_conflicting_services(device['registry_id']) and device['presence'] == 'MISSING':
                state = _load_state()
                recovery = state.setdefault('hardware_recovery', {}).setdefault(device['registry_id'], {'services': [], 'status': 'WAITING'})
                if service not in recovery['services']: recovery['services'].append(service)
                _save_state(state)
                return True
    return False
