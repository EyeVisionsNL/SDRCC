"""Generic multi-receiver manager with Runtime Context Foundation."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from core import config as config_core

from .receiver_runtime import ReceiverRuntime

_RECEIVER_ID = re.compile(r"^sdr\d+$", re.IGNORECASE)
_DEFAULT_CAPABILITIES = ("weather", "voice", "ais", "adsb", "vhf", "uhf")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_capabilities(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return _DEFAULT_CAPABILITIES
    result = tuple(sorted({str(item).strip().lower() for item in value if str(item).strip()}))
    return result or _DEFAULT_CAPABILITIES


def _receiver_number(receiver_id: str) -> str:
    suffix = receiver_id[3:] if receiver_id.lower().startswith("sdr") else receiver_id
    return f"SDR{suffix}"


def _configured_roles(station: dict[str, Any]) -> dict[str, str]:
    assignments = station.get("assignments")
    if not isinstance(assignments, dict):
        return {}
    result: dict[str, str] = {}
    for role, receiver_id in assignments.items():
        key = str(receiver_id).strip().lower()
        if key and key not in result:
            result[key] = str(role).strip().lower()
    return result


class RuntimeManager:
    """Own receiver contexts while receiver_manager v1 remains authoritative."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._receivers: dict[str, ReceiverRuntime] = {}
        self._started_at = _utc_now()
        self._bridge_error: str | None = None
        self.refresh_configuration()

    def refresh_configuration(self) -> None:
        station = config_core.load_station() or {}
        configured: dict[str, dict[str, Any]] = {
            str(receiver_id).lower(): receiver_config
            for receiver_id, receiver_config in station.items()
            if _RECEIVER_ID.fullmatch(str(receiver_id)) and isinstance(receiver_config, dict)
        }
        roles = _configured_roles(station)
        with self._lock:
            for receiver_id in sorted(configured):
                receiver_config = configured[receiver_id]
                name = str(receiver_config.get("name") or receiver_id.upper())
                raw_serial = receiver_config.get("serial")
                serial = None if raw_serial is None else str(raw_serial)
                capabilities = _normalise_capabilities(receiver_config.get("capabilities"))
                runtime = self._receivers.get(receiver_id)
                if runtime is None:
                    self._receivers[receiver_id] = ReceiverRuntime(
                        receiver_id=receiver_id,
                        name=name,
                        serial=serial,
                        number=_receiver_number(receiver_id),
                        capabilities=capabilities,
                        roles={"current": roles.get(receiver_id), "previous": None, "requested": None},
                    )
                else:
                    runtime.update_configuration(
                        name=name,
                        serial=serial,
                        number=_receiver_number(receiver_id),
                        capabilities=capabilities,
                        current_role=roles.get(receiver_id),
                    )

            for receiver_id in set(self._receivers) - set(configured):
                runtime = self._receivers[receiver_id]
                if runtime.reservation is None and runtime.active_mission is None:
                    runtime.transition("OFFLINE", detail="Receiver is no longer present in station.yaml")

    def observe_legacy_receiver_manager(self) -> None:
        """Mirror current v1 reservation state; never mutate v1 state."""
        try:
            from core import receiver_manager

            legacy = receiver_manager.get_status() or {}
            reservation = legacy.get("reservation")
            receiver_id = None
            if isinstance(reservation, dict):
                receiver_id = str(reservation.get("receiver_id") or "").strip().lower() or None

            with self._lock:
                for current_id, runtime in self._receivers.items():
                    runtime.observe_legacy_reservation(
                        deepcopy(reservation) if current_id == receiver_id else None
                    )
            self._bridge_error = None
        except Exception as error:
            self._bridge_error = str(error)

    def get(self, receiver_id: str) -> ReceiverRuntime:
        key = str(receiver_id).strip().lower()
        with self._lock:
            try:
                return self._receivers[key]
            except KeyError as exc:
                raise KeyError(f"Unknown receiver runtime: {receiver_id}") from exc

    def snapshot(self, *, refresh: bool = True) -> dict[str, Any]:
        if refresh:
            self.refresh_configuration()
            self.observe_legacy_receiver_manager()
        with self._lock:
            receivers = {
                receiver_id: self._receivers[receiver_id].snapshot()
                for receiver_id in sorted(self._receivers)
            }
        return {
            "ok": True,
            "version": "v0.30.2",
            "architecture": "runtime-v2-context-foundation",
            "context_version": "1.0",
            "mode": "parallel-observer",
            "authority": "receiver-manager-v1",
            "bridge": {
                "enabled": True,
                "direction": "receiver-manager-v1 -> runtime-v2",
                "read_only": True,
                "error": self._bridge_error,
            },
            "receiver_count": len(receivers),
            "receivers": receivers,
            "started_at": self._started_at,
            "updated_at": _utc_now(),
            "notes": [
                "Existing mission execution and reservation ownership remain authoritative.",
                "Runtime Context groups identity, lifecycle, roles, hardware, metrics, scheduler and metadata.",
                "Existing receiver API fields remain available for backwards compatibility.",
                "Hardware health probing and subsystem writers are not active yet.",
            ],
        }


_RUNTIME_MANAGER: RuntimeManager | None = None
_RUNTIME_MANAGER_LOCK = RLock()


def get_runtime_manager() -> RuntimeManager:
    global _RUNTIME_MANAGER
    with _RUNTIME_MANAGER_LOCK:
        if _RUNTIME_MANAGER is None:
            _RUNTIME_MANAGER = RuntimeManager()
        return _RUNTIME_MANAGER


def get_snapshot() -> dict[str, Any]:
    return get_runtime_manager().snapshot()
