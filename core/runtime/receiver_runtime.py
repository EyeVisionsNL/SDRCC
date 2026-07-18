"""Thread-safe runtime context for one physical SDR receiver."""

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


def _empty_hardware() -> dict[str, Any]:
    return {
        "frequency_hz": None,
        "sample_rate_hz": None,
        "gain_db": None,
        "gain_mode": None,
        "ppm": None,
        "device_open": None,
        "driver": None,
    }


def _empty_roles() -> dict[str, Any]:
    return {"current": None, "previous": None, "requested": None}


def _empty_live_metrics() -> dict[str, Any]:
    return {
        "snr_db": None,
        "peak_snr_db": None,
        "ber": None,
        "frames": None,
        "cadus": None,
        "images": None,
        "cpu_percent": None,
        "memory_percent": None,
        "temperature_c": None,
    }


def _empty_scheduler() -> dict[str, Any]:
    return {"state": None, "next_job": None, "queue_position": None}


def _empty_metadata() -> dict[str, Any]:
    return {"plugin_data": {}, "decoder_data": {}, "custom": {}}


_ALLOWED_TRANSITIONS: dict[RuntimeState, set[RuntimeState]] = {
    RuntimeState.OFFLINE: {RuntimeState.IDLE, RuntimeState.ERROR},
    RuntimeState.IDLE: {RuntimeState.OFFLINE, RuntimeState.RESERVED, RuntimeState.ERROR},
    RuntimeState.RESERVED: {
        RuntimeState.IDLE, RuntimeState.PREPARING, RuntimeState.RUNNING,
        RuntimeState.RESTORING, RuntimeState.ERROR,
    },
    RuntimeState.PREPARING: {
        RuntimeState.RUNNING, RuntimeState.RESTORING, RuntimeState.ERROR,
    },
    RuntimeState.RUNNING: {
        RuntimeState.PROCESSING, RuntimeState.RESTORING, RuntimeState.IDLE,
        RuntimeState.ERROR,
    },
    RuntimeState.PROCESSING: {
        RuntimeState.RESTORING, RuntimeState.IDLE, RuntimeState.ERROR,
    },
    RuntimeState.RESTORING: {
        RuntimeState.IDLE, RuntimeState.OFFLINE, RuntimeState.ERROR,
    },
    RuntimeState.ERROR: {
        RuntimeState.RESTORING, RuntimeState.IDLE, RuntimeState.OFFLINE,
    },
}


@dataclass
class ReceiverRuntime:
    """Complete, backwards-compatible runtime context for one receiver."""

    receiver_id: str
    name: str
    serial: str | None = None
    number: str | None = None
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    state: RuntimeState = RuntimeState.IDLE
    health: ReceiverHealth = ReceiverHealth.ONLINE
    reservation: dict[str, Any] | None = None
    active_mission: dict[str, Any] | None = None
    detail: str = "Configured receiver runtime"
    started_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    roles: dict[str, Any] = field(default_factory=_empty_roles)
    hardware: dict[str, Any] = field(default_factory=_empty_hardware)
    live_metrics: dict[str, Any] = field(default_factory=_empty_live_metrics)
    scheduler: dict[str, Any] = field(default_factory=_empty_scheduler)
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)
    mission_history: list[dict[str, Any]] = field(default_factory=list)
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
        self, *, name: str, serial: str | None, number: str | None,
        capabilities: tuple[str, ...], current_role: str | None = None,
    ) -> None:
        with self._lock:
            self.name = name
            self.serial = serial
            self.number = number
            self.capabilities = capabilities
            if current_role is not None and self.roles.get("current") is None:
                self.roles["current"] = current_role
            self.updated_at = _utc_now()

    def update_hardware(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                if key in self.hardware:
                    self.hardware[key] = deepcopy(value)
            self.updated_at = _utc_now()

    def update_live_metrics(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                if key in self.live_metrics:
                    self.live_metrics[key] = deepcopy(value)
            self.updated_at = _utc_now()

    def update_scheduler(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                if key in self.scheduler:
                    self.scheduler[key] = deepcopy(value)
            self.updated_at = _utc_now()

    def set_role(
        self, *, current: str | None = None, previous: str | None = None,
        requested: str | None = None,
    ) -> None:
        with self._lock:
            if current is not None:
                self.roles["current"] = current
            if previous is not None:
                self.roles["previous"] = previous
            if requested is not None:
                self.roles["requested"] = requested
            self.updated_at = _utc_now()

    def update_metadata(self, section: str, values: dict[str, Any]) -> None:
        if section not in self.metadata:
            raise KeyError(f"Unknown runtime metadata section: {section}")
        with self._lock:
            self.metadata[section].update(deepcopy(values))
            self.updated_at = _utc_now()

    def observe_legacy_reservation(self, reservation: dict[str, Any] | None) -> None:
        """Mirror the authoritative v1 receiver reservation without owning it."""
        with self._lock:
            previous_mission = deepcopy(self.active_mission)
            self.reservation = deepcopy(reservation)
            if reservation is None:
                if previous_mission:
                    history_item = previous_mission
                    history_item["observed_finished_at"] = _utc_now()
                    self.mission_history.append(history_item)
                    self.mission_history[:] = self.mission_history[-20:]
                self.active_mission = None
                if self.state not in {RuntimeState.OFFLINE, RuntimeState.ERROR}:
                    self.state = RuntimeState.IDLE
                self.roles["requested"] = None
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
                self.roles["previous"] = reservation.get("previous_role")
                self.roles["requested"] = str(reservation.get("mission_type") or "").lower() or None
                self.detail = (
                    "Observed active legacy mission" if status == "ACTIVE"
                    else "Observed legacy receiver reservation"
                )
            self.updated_at = _utc_now()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            identity = {
                "receiver_id": self.receiver_id,
                "name": self.name,
                "number": self.number,
                "serial": self.serial,
                "capabilities": list(self.capabilities),
            }
            lifecycle = {
                "state": self.state.value,
                "health": self.health.value,
                "detail": self.detail,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
            }
            context = {
                "identity": identity,
                "lifecycle": lifecycle,
                "roles": deepcopy(self.roles),
                "hardware": deepcopy(self.hardware),
                "reservation": deepcopy(self.reservation),
                "active_mission": deepcopy(self.active_mission),
                "mission_history": deepcopy(self.mission_history),
                "live_metrics": deepcopy(self.live_metrics),
                "scheduler": deepcopy(self.scheduler),
                "metadata": deepcopy(self.metadata),
            }
            # Existing top-level fields remain unchanged for API compatibility.
            return {
                **identity,
                "state": lifecycle["state"],
                "health": lifecycle["health"],
                "reservation": deepcopy(self.reservation),
                "active_mission": deepcopy(self.active_mission),
                "detail": self.detail,
                "updated_at": self.updated_at,
                "context_version": "1.0",
                "context": context,
            }
