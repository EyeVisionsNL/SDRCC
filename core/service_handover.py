#!/usr/bin/env python3

"""Live systemd service handover for SDR receivers.

A handover is transactional:
1. inspect the configured conflicting service group;
2. stop only services that were active before the mission;
3. verify that they are inactive;
4. later restart exactly those services in restore order;
5. verify recovery before the reservation may be released.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from time import monotonic, sleep
from typing import Any, Callable
import subprocess

from core.device_manager import get_conflicting_service_group, get_device
from core import receiver_manager

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _run_privileged(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", *command],
        text=True,
        capture_output=True,
        check=False,
    )


def inspect_service(service: str, *, runner: Runner = _run) -> dict[str, Any]:
    result = runner(["systemctl", "is-active", service])
    state = (result.stdout or "").strip() or "unknown"
    return {
        "service": service,
        "active_state": state,
        "was_active": result.returncode == 0 and state == "active",
        "returncode": int(result.returncode),
        "detail": (result.stderr or "").strip() or None,
    }


def build_plan(receiver_id: str, *, runner: Runner = _run) -> dict[str, Any]:
    device = get_device(receiver_id)
    if device is None:
        raise ValueError(f"Onbekende receiver: {receiver_id}")

    group = get_conflicting_service_group(receiver_id)
    services: dict[str, Any] = {}
    all_services = list(dict.fromkeys(group["stop_order"] + group["restore_order"]))
    for service in all_services:
        services[service] = inspect_service(service, runner=runner)

    active_before = [name for name, item in services.items() if item["was_active"]]
    return {
        "ok": True,
        "mode": "LIVE",
        "receiver_id": receiver_id,
        "receiver_number": device.get("number"),
        "receiver_serial": device.get("serial"),
        "role": group["role"],
        "service_group": deepcopy(group),
        "services": services,
        "active_before": active_before,
        "planned_stop_order": [s for s in group["stop_order"] if s in active_before],
        "planned_restore_order": [s for s in group["restore_order"] if s in active_before],
        "inspected_at": _now(),
        "changes_applied": False,
    }


def _wait_for_state(
    service: str,
    *,
    expected_active: bool,
    runner: Runner,
    timeout: float,
    interval: float,
) -> dict[str, Any]:
    deadline = monotonic() + max(0.1, timeout)
    last = inspect_service(service, runner=runner)
    while bool(last["was_active"]) != expected_active and monotonic() < deadline:
        sleep(max(0.01, interval))
        last = inspect_service(service, runner=runner)
    last["verified"] = bool(last["was_active"]) == expected_active
    return last


def stop_reserved_handover(
    *,
    mission_key: str,
    inspect_runner: Runner = _run,
    privileged_runner: Runner = _run_privileged,
    timeout: float = 8.0,
    interval: float = 0.25,
) -> dict[str, Any]:
    status = receiver_manager.get_status()
    reservation = status.get("reservation")
    if not reservation or reservation.get("mission_key") != mission_key:
        raise RuntimeError("Geen passende receiver-reservering gevonden")

    plan = build_plan(str(reservation["receiver_id"]), runner=inspect_runner)
    receiver_manager.set_service_group_snapshot(
        mission_key=mission_key,
        service_group=plan["service_group"],
        service_snapshot=plan,
        dry_run=False,
    )

    actions: list[dict[str, Any]] = []
    try:
        for service in plan["planned_stop_order"]:
            result = privileged_runner(["systemctl", "stop", service])
            action = {
                "service": service,
                "action": "stop",
                "returncode": int(result.returncode),
                "stdout": (result.stdout or "").strip() or None,
                "stderr": (result.stderr or "").strip() or None,
            }
            actions.append(action)
            if result.returncode != 0:
                raise RuntimeError(f"Stoppen van {service} mislukt: {action['stderr'] or action['stdout'] or 'onbekende fout'}")

            verification = _wait_for_state(
                service,
                expected_active=False,
                runner=inspect_runner,
                timeout=timeout,
                interval=interval,
            )
            action["verification"] = verification
            if not verification["verified"]:
                raise RuntimeError(f"{service} bleef actief na stop-opdracht")

        result_payload = {
            "ok": True,
            "mode": "LIVE",
            "phase": "STOPPED",
            "plan": plan,
            "actions": actions,
            "completed_at": _now(),
        }
        receiver_manager.mark_handover_stopped(
            mission_key=mission_key,
            handover_result=result_payload,
        )
        return {"handover": result_payload, "receiver_status": receiver_manager.get_status()}
    except Exception as exc:
        receiver_manager.mark_handover_attention(
            mission_key=mission_key,
            detail=str(exc),
            handover_result={"ok": False, "phase": "STOP_FAILED", "plan": plan, "actions": actions},
        )
        raise


def restore_reserved_handover(
    *,
    mission_key: str,
    inspect_runner: Runner = _run,
    privileged_runner: Runner = _run_privileged,
    timeout: float = 12.0,
    interval: float = 0.25,
) -> dict[str, Any]:
    status = receiver_manager.get_status()
    reservation = status.get("reservation")
    if not reservation or reservation.get("mission_key") != mission_key:
        raise RuntimeError("Geen passende receiver-reservering gevonden")

    snapshot = reservation.get("service_snapshot") or {}
    restore_order = list(snapshot.get("planned_restore_order") or [])
    actions: list[dict[str, Any]] = []

    try:
        for service in restore_order:
            current = inspect_service(service, runner=inspect_runner)
            if current["was_active"]:
                actions.append({
                    "service": service,
                    "action": "start",
                    "skipped": True,
                    "reason": "already_active",
                    "verification": current,
                })
                continue

            result = privileged_runner(["systemctl", "start", service])
            action = {
                "service": service,
                "action": "start",
                "returncode": int(result.returncode),
                "stdout": (result.stdout or "").strip() or None,
                "stderr": (result.stderr or "").strip() or None,
            }
            actions.append(action)
            if result.returncode != 0:
                raise RuntimeError(f"Starten van {service} mislukt: {action['stderr'] or action['stdout'] or 'onbekende fout'}")

            verification = _wait_for_state(
                service,
                expected_active=True,
                runner=inspect_runner,
                timeout=timeout,
                interval=interval,
            )
            action["verification"] = verification
            if not verification["verified"]:
                raise RuntimeError(f"{service} werd niet actief na start-opdracht")

        result_payload = {
            "ok": True,
            "mode": "LIVE",
            "phase": "RESTORED",
            "actions": actions,
            "completed_at": _now(),
        }
        receiver_manager.mark_restore_result(
            mission_key=mission_key,
            success=True,
            detail="Alle vooraf actieve services zijn hersteld",
        )
        return {"handover": result_payload, "receiver_status": receiver_manager.get_status()}
    except Exception as exc:
        receiver_manager.mark_handover_attention(
            mission_key=mission_key,
            detail=str(exc),
            handover_result={"ok": False, "phase": "RESTORE_FAILED", "actions": actions},
        )
        receiver_manager.mark_restore_result(mission_key=mission_key, success=False, detail=str(exc))
        raise
