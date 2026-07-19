"""Read-only receiver operation context for SDRCC.

This module normalizes existing Mission Engine, Receiver Manager and Runtime v2
state into one receiver-keyed API contract. It deliberately performs no writes
and does not change command ownership.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from core import device_manager
from core import mission_engine
from core import receiver_manager
from core.runtime import runtime_manager as runtime_manager_core

API_VERSION = "v0.33.0a"
CONTRACT_VERSION = "1.0"


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _same(left: Any, right: Any) -> bool:
    left_text = _text(left)
    right_text = _text(right)
    return left_text is not None and left_text == right_text


def _decision(allowed: bool, code: str, detail: str) -> dict[str, Any]:
    return {
        "allowed": bool(allowed),
        "reason": code,
        "detail": detail,
    }


def _runtime_context(runtime_receiver: Any) -> dict[str, Any]:
    return deepcopy(runtime_receiver) if isinstance(runtime_receiver, dict) else {}


def _receiver_identity(device: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    identity = runtime.get("identity") if isinstance(runtime.get("identity"), dict) else {}
    return {
        "receiver_id": device.get("id"),
        "number": identity.get("number") or device.get("number"),
        "name": identity.get("name") or device.get("name"),
        "serial": identity.get("serial") or device.get("serial"),
        "role": device.get("role"),
        "roles": deepcopy(device.get("roles") or []),
        "capabilities": deepcopy(identity.get("capabilities") or []),
    }


def _consistency(
    receiver_id: str,
    active_job: dict[str, Any] | None,
    reservation: dict[str, Any] | None,
    runtime: dict[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    runtime_reservation = runtime.get("reservation") if isinstance(runtime.get("reservation"), dict) else None
    runtime_mission = runtime.get("active_mission") if isinstance(runtime.get("active_mission"), dict) else None

    if active_job and not _same(active_job.get("receiver_id"), receiver_id):
        active_job = None
    if reservation and not _same(reservation.get("receiver_id"), receiver_id):
        reservation = None

    if active_job and reservation:
        mission_id = active_job.get("mission_id")
        reserved_mission_id = reservation.get("mission_id")
        if mission_id and reserved_mission_id and not _same(mission_id, reserved_mission_id):
            issues.append({
                "code": "MISSION_ID_MISMATCH",
                "detail": "Mission Engine en Receiver Manager verwijzen naar verschillende mission_id's.",
            })

    if reservation and runtime_reservation:
        if not _same(reservation.get("receiver_id"), runtime_reservation.get("receiver_id")):
            issues.append({
                "code": "RUNTIME_RECEIVER_MISMATCH",
                "detail": "Runtime v2 spiegelt een reservering voor een andere receiver.",
            })
        if reservation.get("mission_key") and runtime_reservation.get("mission_key") and not _same(
            reservation.get("mission_key"), runtime_reservation.get("mission_key")
        ):
            issues.append({
                "code": "MISSION_KEY_MISMATCH",
                "detail": "Receiver Manager en Runtime v2 verwijzen naar verschillende mission_key's.",
            })

    if runtime_mission and reservation:
        if runtime_mission.get("mission_id") and reservation.get("mission_id") and not _same(
            runtime_mission.get("mission_id"), reservation.get("mission_id")
        ):
            issues.append({
                "code": "RUNTIME_MISSION_ID_MISMATCH",
                "detail": "Runtime v2 en Receiver Manager verwijzen naar verschillende mission_id's.",
            })

    return {
        "ok": not issues,
        "issues": issues,
    }


def _build_receiver(
    device: dict[str, Any],
    *,
    active_job: dict[str, Any] | None,
    global_reservation: dict[str, Any] | None,
    runtime: dict[str, Any],
    engine_phase: str,
) -> dict[str, Any]:
    receiver_id = str(device.get("id") or "").lower()
    lifecycle = runtime.get("lifecycle") if isinstance(runtime.get("lifecycle"), dict) else {}
    health = str(lifecycle.get("health") or "UNKNOWN").upper()
    lifecycle_state = str(lifecycle.get("state") or "UNKNOWN").upper()
    online = lifecycle_state != "OFFLINE" and health not in {"OFFLINE", "MISSING"}

    reservation = (
        deepcopy(global_reservation)
        if isinstance(global_reservation, dict)
        and _same(global_reservation.get("receiver_id"), receiver_id)
        else None
    )
    mission = (
        deepcopy(active_job)
        if isinstance(active_job, dict)
        and _same(active_job.get("receiver_id"), receiver_id)
        else None
    )

    reservation_owner = _text(global_reservation.get("receiver_id")) if isinstance(global_reservation, dict) else None
    mission_owner = _text(active_job.get("receiver_id")) if isinstance(active_job, dict) else None
    consistency = _consistency(receiver_id, mission, reservation, runtime)

    if not online:
        record_now = _decision(False, "RECEIVER_OFFLINE", "De receiver is niet online.")
    elif not consistency["ok"]:
        record_now = _decision(False, "CONTEXT_MISMATCH", "De receivercontext is niet consistent.")
    elif active_job:
        record_now = _decision(False, "MISSION_ACTIVE", "Er is al een actieve missie.")
    elif global_reservation:
        record_now = _decision(
            False,
            "RECEIVER_RESERVED" if reservation else "OTHER_RECEIVER_RESERVED",
            "Deze receiver is al gereserveerd." if reservation else f"{str(reservation_owner or 'Een andere receiver').upper()} is al gereserveerd.",
        )
    else:
        record_now = _decision(True, "READY", "De receiver kan voor een handmatige opname worden aangevraagd.")

    if mission:
        if consistency["ok"]:
            stop_mission = _decision(True, "ACTIVE_MISSION_OWNER", "Deze receiver is eigenaar van de actieve missie.")
            mission_next = _decision(True, "ACTIVE_MISSION_OWNER", "Deze receiver is eigenaar van de actieve Mission Engine-job.")
        else:
            stop_mission = _decision(False, "CONTEXT_MISMATCH", "De actieve missiecontext is niet consistent.")
            mission_next = _decision(False, "CONTEXT_MISMATCH", "De actieve missiecontext is niet consistent.")
    elif active_job:
        owner = str(mission_owner or "onbekend").upper()
        stop_mission = _decision(False, "OTHER_RECEIVER_OWNS_MISSION", f"De actieve missie hoort bij {owner}.")
        mission_next = _decision(False, "OTHER_RECEIVER_OWNS_MISSION", f"De actieve Mission Engine-job hoort bij {owner}.")
    else:
        stop_mission = _decision(False, "NO_ACTIVE_MISSION", "Er is geen actieve missie om te stoppen.")
        mission_next = _decision(False, "NO_ACTIVE_MISSION", "Er is geen actieve Mission Engine-job.")

    return {
        "receiver_id": receiver_id,
        "identity": _receiver_identity(device, runtime),
        "available": bool(online and not global_reservation and not active_job),
        "online": online,
        "lifecycle": deepcopy(lifecycle),
        "reservation": reservation,
        "active_mission": mission,
        "mission_id": mission.get("mission_id") if mission else (reservation.get("mission_id") if reservation else None),
        "mission_key": reservation.get("mission_key") if reservation else None,
        "mission_phase": mission.get("status") if mission else engine_phase,
        "runtime": runtime,
        "consistency": consistency,
        "operations": {
            "record_now": record_now,
            "stop_mission": stop_mission,
            "mission_next": mission_next,
        },
        # Flat compatibility fields for the first UI consumers.
        "can_record_now": record_now["allowed"],
        "can_stop_mission": stop_mission["allowed"],
        "can_mission_next": mission_next["allowed"],
        "denial_reasons": {
            "record_now": None if record_now["allowed"] else record_now["reason"],
            "stop_mission": None if stop_mission["allowed"] else stop_mission["reason"],
            "mission_next": None if mission_next["allowed"] else mission_next["reason"],
        },
    }


def get_snapshot() -> dict[str, Any]:
    """Return a receiver-keyed, read-only operation context snapshot."""
    devices = device_manager.get_devices()
    mission = mission_engine.get_mission_status()
    receiver_state = receiver_manager.get_status()
    runtime_snapshot = runtime_manager_core.get_snapshot()

    active_job = mission.get("active_job") if isinstance(mission.get("active_job"), dict) else None
    reservation = receiver_state.get("reservation") if isinstance(receiver_state.get("reservation"), dict) else None
    runtimes = runtime_snapshot.get("receivers") if isinstance(runtime_snapshot.get("receivers"), dict) else {}
    engine_phase = str(mission.get("phase") or mission.get("state") or "UNKNOWN")

    receivers = {
        str(device.get("id")): _build_receiver(
            device,
            active_job=active_job,
            global_reservation=reservation,
            runtime=_runtime_context(runtimes.get(str(device.get("id")))),
            engine_phase=engine_phase,
        )
        for device in devices
        if device.get("id")
    }

    consistency_issues = [
        {"receiver_id": receiver_id, **issue}
        for receiver_id, context in receivers.items()
        for issue in context["consistency"]["issues"]
    ]

    return {
        "ok": True,
        "version": API_VERSION,
        "contract_version": CONTRACT_VERSION,
        "generated_at": _now_text(),
        "mode": "read-only",
        "authority": {
            "mission": "mission-engine",
            "reservation": "receiver-manager-v1",
            "runtime": "runtime-v2-observer",
        },
        "receiver_count": len(receivers),
        "receivers": receivers,
        "global": {
            "mission_phase": engine_phase,
            "active_mission_id": active_job.get("mission_id") if active_job else None,
            "active_receiver_id": active_job.get("receiver_id") if active_job else None,
            "reservation_receiver_id": reservation.get("receiver_id") if reservation else None,
            "reservation_mission_key": reservation.get("mission_key") if reservation else None,
            "parallel_writes_supported": False,
        },
        "consistency": {
            "ok": not consistency_issues,
            "issues": consistency_issues,
        },
        "notes": [
            "This endpoint is observational and performs no state changes.",
            "Scheduler mode and current Mission Engine ownership remain global.",
            "Operation decisions prepare future receiver-targeted write endpoints.",
        ],
    }
