#!/usr/bin/env python3

"""Safe systemd service-handover planning for SDR receivers.

v0.28.0e is deliberately inspection-only. It discovers the service group,
reads live systemd state and records an ordered stop/restore plan. No service
is stopped or started by this module in this release.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable
import subprocess

from core.device_manager import get_conflicting_service_group, get_device
from core import receiver_manager

Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


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
    stop_actions = [name for name in group["stop_order"] if name in active_before]
    restore_actions = [name for name in group["restore_order"] if name in active_before]

    return {
        "ok": True,
        "mode": "DRY_RUN",
        "receiver_id": receiver_id,
        "receiver_number": device.get("number"),
        "receiver_serial": device.get("serial"),
        "role": group["role"],
        "service_group": deepcopy(group),
        "services": services,
        "active_before": active_before,
        "planned_stop_order": stop_actions,
        "planned_restore_order": restore_actions,
        "inspected_at": _now(),
        "changes_applied": False,
    }


def inspect_reserved_handover(*, mission_key: str, runner: Runner = _run) -> dict[str, Any]:
    status = receiver_manager.get_status()
    reservation = status.get("reservation")
    if not reservation or reservation.get("mission_key") != mission_key:
        raise RuntimeError("Geen passende receiver-reservering gevonden")

    plan = build_plan(str(reservation["receiver_id"]), runner=runner)
    updated = receiver_manager.set_service_group_snapshot(
        mission_key=mission_key,
        service_group=plan["service_group"],
        service_snapshot=plan,
        dry_run=True,
    )
    return {"plan": plan, "receiver_status": updated}
