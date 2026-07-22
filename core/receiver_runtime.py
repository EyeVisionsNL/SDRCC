#!/usr/bin/env python3

"""Read-only Receiver Runtime observation foundation.

Receiver Manager remains the authority for receiver inventory and reservations.
This module only composes existing state into a normalized runtime snapshot.

It intentionally contains no methods for:
- reserving or releasing receivers;
- starting or stopping services;
- starting SatDump or other plugins;
- changing Mission Engine state;
- persisting runtime state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import subprocess
from typing import Any, Callable

from core import config
from core import mission_engine
from core import receiver_manager


ServiceReader = Callable[[str], dict[str, Any]]


SERVICE_BY_ROLE: dict[str, str] = {
    "ais": "ais-catcher.service",
    "adsb": "readsb.service",
}


def _now() -> str:
    """Return a timezone-aware observation timestamp."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_service_state(service_name: str) -> dict[str, Any]:
    """Observe a systemd service without changing it."""
    result: dict[str, Any] = {
        "service": service_name,
        "active": False,
        "state": "unknown",
        "enabled": "unknown",
        "observed": False,
        "error": None,
    }

    try:
        active = subprocess.run(
            ["systemctl", "is-active", service_name],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        active_text = active.stdout.strip() or active.stderr.strip() or "unknown"
        result["active"] = active.stdout.strip() == "active"
        result["state"] = active_text
        result["observed"] = True
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)
        return result

    try:
        enabled = subprocess.run(
            ["systemctl", "is-enabled", service_name],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        result["enabled"] = (
            enabled.stdout.strip()
            or enabled.stderr.strip()
            or "unknown"
        )
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = str(error)

    return result


def _normalise_assignments(raw: Any) -> dict[str, str | None]:
    """Return only supported assignment fields as normalized receiver ids."""
    data = raw if isinstance(raw, dict) else {}
    assignments: dict[str, str | None] = {}
    for role in ("weather", "ais", "adsb"):
        value = data.get(role)
        assignments[role] = str(value).strip() if value else None
    return assignments


def _roles_for_receiver(
    receiver_id: str,
    assignments: dict[str, str | None],
) -> list[str]:
    """Return configured roles for one receiver."""
    return [
        role
        for role in ("weather", "ais", "adsb")
        if assignments.get(role) == receiver_id
    ]


def _service_observations(
    receiver_id: str,
    assignments: dict[str, str | None],
    service_reader: ServiceReader,
) -> list[dict[str, Any]]:
    """Observe services assigned to a receiver."""
    observations: list[dict[str, Any]] = []
    for role, service_name in SERVICE_BY_ROLE.items():
        if assignments.get(role) != receiver_id:
            continue
        item = deepcopy(service_reader(service_name))
        item["role"] = role
        observations.append(item)
    return observations


def _mission_for_receiver(
    receiver_id: str,
    active_job: Any,
    reservation: Any,
) -> dict[str, Any] | None:
    """Return the active job only when it belongs to this receiver."""
    if not isinstance(active_job, dict):
        return None

    active_receiver = str(active_job.get("receiver_id") or "").strip()
    if active_receiver == receiver_id:
        return deepcopy(active_job)

    if isinstance(reservation, dict):
        mission_id = str(reservation.get("mission_id") or "").strip()
        mission_key = str(reservation.get("mission_key") or "").strip()
        job_id = str(active_job.get("mission_id") or "").strip()
        if job_id and job_id in {mission_id, mission_key}:
            return deepcopy(active_job)

    return None


def _runtime_state(
    reservation: Any,
    mission: Any,
    services: list[dict[str, Any]],
) -> str:
    """Derive a display-only runtime state from authoritative observations."""
    if isinstance(reservation, dict):
        reservation_state = str(reservation.get("status") or "").upper()
        if reservation_state == "ACTIVE" or isinstance(mission, dict):
            return "MISSION_ACTIVE"
        return "RESERVED"

    if any(bool(service.get("active")) for service in services):
        return "SERVICE_ACTIVE"

    return "IDLE"


class ReceiverRuntime:
    """Compose a read-only snapshot of receiver runtime observations."""

    def __init__(
        self,
        *,
        service_reader: ServiceReader | None = None,
    ) -> None:
        self._service_reader = service_reader or _read_service_state

    def get_snapshot(self) -> dict[str, Any]:
        """Return one immutable observation snapshot.

        No state is cached or persisted. Every invocation reads the current
        Receiver Manager, Mission Engine, configuration and systemd state.
        """
        observed_at = _now()
        manager_status = receiver_manager.get_status()
        mission_status = mission_engine.get_mission_status()
        assignments = _normalise_assignments(
            config.get_receiver_assignments()
        )

        manager_receivers = manager_status.get("receivers")
        if not isinstance(manager_receivers, dict):
            manager_receivers = {}

        reservations = manager_status.get("reservations")
        if not isinstance(reservations, dict):
            reservations = {}

        active_job = mission_status.get("active_job")
        receivers: dict[str, dict[str, Any]] = {}

        receiver_ids = list(manager_receivers.keys())
        for receiver_id in reservations:
            if receiver_id not in receiver_ids:
                receiver_ids.append(receiver_id)

        for receiver_id in receiver_ids:
            manager_item = manager_receivers.get(receiver_id)
            if not isinstance(manager_item, dict):
                manager_item = {}

            device = manager_item.get("device")
            if not isinstance(device, dict):
                device = {"id": receiver_id, "missing": True}

            reservation = reservations.get(receiver_id)
            if not isinstance(reservation, dict):
                reservation = manager_item.get("reservation")
            if not isinstance(reservation, dict):
                reservation = None

            services = _service_observations(
                receiver_id,
                assignments,
                self._service_reader,
            )
            observed_mission = _mission_for_receiver(
                receiver_id,
                active_job,
                reservation,
            )

            receivers[receiver_id] = {
                "receiver_id": receiver_id,
                "device": deepcopy(device),
                "serial": device.get("serial"),
                "name": device.get("name"),
                "configured_roles": _roles_for_receiver(
                    receiver_id,
                    assignments,
                ),
                "reservation": deepcopy(reservation),
                "reserved": reservation is not None,
                "reservation_owner": (
                    reservation.get("mission_key")
                    if isinstance(reservation, dict)
                    else None
                ),
                "observed_services": services,
                "observed_mission": observed_mission,
                "runtime_state": _runtime_state(
                    reservation,
                    observed_mission,
                    services,
                ),
                "authority": "receiver_manager",
                "updated_at": observed_at,
            }

        states = {
            receiver_id: item["runtime_state"]
            for receiver_id, item in receivers.items()
        }

        return {
            "ok": bool(manager_status.get("ok", True)),
            "read_only": True,
            "authority": "receiver_manager",
            "updated_at": observed_at,
            "receiver_count": len(receivers),
            "assignments": assignments,
            "mission_phase": (
                mission_status.get("phase")
                or mission_status.get("state")
            ),
            "active_mission_id": (
                active_job.get("mission_id")
                if isinstance(active_job, dict)
                else None
            ),
            "states": states,
            "receivers": receivers,
        }

    def get_receivers(self) -> dict[str, dict[str, Any]]:
        """Return all normalized receiver observations."""
        return self.get_snapshot()["receivers"]

    def get_receiver(self, receiver_id: str) -> dict[str, Any] | None:
        """Return one receiver observation, or None when unknown."""
        key = str(receiver_id or "").strip()
        if not key:
            return None
        receiver = self.get_receivers().get(key)
        return deepcopy(receiver) if receiver is not None else None


receiver_runtime = ReceiverRuntime()


def get_snapshot() -> dict[str, Any]:
    """Module-level convenience wrapper."""
    return receiver_runtime.get_snapshot()


def get_receivers() -> dict[str, dict[str, Any]]:
    """Module-level convenience wrapper."""
    return receiver_runtime.get_receivers()


def get_receiver(receiver_id: str) -> dict[str, Any] | None:
    """Module-level convenience wrapper."""
    return receiver_runtime.get_receiver(receiver_id)
