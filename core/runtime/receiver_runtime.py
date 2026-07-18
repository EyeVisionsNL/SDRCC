"""Thread-safe state container for one physical SDR receiver."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from .health import ReceiverHealth
from .runtime_state import RuntimeState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


_ALLOWED_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.OFFLINE: {RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.IDLE: {RuntimeState.OFFLINE, RuntimeState.RESERVED, RuntimeState.ERROR},
    RuntimeState.RESERVED: {
        RuntimeState.IDLE,
        RuntimeState.PREPARING,
        RuntimeState.RUNNING,
        RuntimeState.RESTORING,
        RuntimeState.ERROR,
    },
    RuntimeState.PREPARING: {
        RuntimeState.RUNNING,
        RuntimeState.RESTORING,
        RuntimeState.ERROR,
    },
    RuntimeState.RUNNING: {
        RuntimeState.PROCESSING,
        RuntimeState.RESTORING,
        RuntimeState.IDLE,
        RuntimeState.ERROR,
    },
    RuntimeState.PROCESSING: {
        RuntimeState.RESTORING,
        RuntimeState.IDLE,
        RuntimeState.ERROR,
    },
    RuntimeState.RESTORING: {
        RuntimeState.IDLE,
        RuntimeState.OFFLINE,
        RuntimeState.ERROR,
    },
    RuntimeState.ERROR: {
        RuntimeState.RESTORING,
        RuntimeState.IDLE,
        RuntimeState.OFFLINE,
    },
}


@dataclass
class ReceiverRuntime:
    """Runtime state belonging to exactly one physical receiver."""

    receiver_id: str
    name: str
    serial: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    state: RuntimeState = RuntimeState.IDLE
    health: ReceiverHealth = ReceiverHealth.ONLINE
    reservation: dict[str, Any] | None = None
    active_mission: dict[str, Any] | None = None
    detail: str = "Configured receiver runtime"
    updated_at: str = field(default_factory=_utc_now)
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def transition(self, target: RuntimeState | str, *, detail: str | None = None) -> None:
        target_state = RuntimeState(target)
        with self._lock:
            if target_state != self.state and target_state not in _ALLOWED_TRANSITIONS[self.state]:
                raise ValueError(
                    f"Invalid runtime transition for {self.receiver_id}: "
                    f"{self.state.value} -> {target_state.value}"
                )
            self.state = target_state
            if detail is not None:
                self.detail = str(detail)
            self.updated_at = _utc_now()

    def set_health(self, health: ReceiverHealth | str, *, detail: str | None = None) -> None:
        with self._lock:
            self.health = ReceiverHealth(health)
            if detail is not None:
                self.detail = str(detail)
            self.updated_at = _utc_now()

    def update_configuration(
        self,
        *,
        name: str,
        serial: str | None,
        capabilities: tuple[str, ...],
    ) -> None:
        with self._lock:
            self.name = name
            self.serial = serial
            self.capabilities = capabilities
            self.updated_at = _utc_now()

    def observe_legacy_reservation(self, reservation: dict[str, Any] | None) -> None:
        """Mirror the authoritative v1 receiver reservation without owning it."""
        with self._lock:
            self.reservation = deepcopy(reservation)
            if reservation is None:
                self.active_mission = None
                if self.state not in {RuntimeState.OFFLINE, RuntimeState.ERROR}:
                    self.state = RuntimeState.IDLE
                self.detail = "No active legacy reservation"
            else:
                status = str(reservation.get("status") or "RESERVED").upper()
                mission = {
                    "mission_key": reservation.get("mission_key"),
                    "mission_id": reservation.get("mission_id"),
                    "mission_type": reservation.get("mission_type"),
                    "target": reservation.get("target"),
                    "status": status,
                    "source": "receiver-manager-v1",
                }
                self.active_mission = mission if status == "ACTIVE" else None
                self.state = RuntimeState.RUNNING if status == "ACTIVE" else RuntimeState.RESERVED
                self.detail = (
                    "Observed active legacy mission"
                    if status == "ACTIVE"
                    else "Observed legacy receiver reservation"
                )
            self.updated_at = _utc_now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "receiver_id": self.receiver_id,
                "name": self.name,
                "serial": self.serial,
                "capabilities": list(self.capabilities),
                "state": self.state.value,
                "health": self.health.value,
                "reservation": deepcopy(self.reservation),
                "active_mission": deepcopy(self.active_mission),
                "detail": self.detail,
                "updated_at": self.updated_at,
            }
