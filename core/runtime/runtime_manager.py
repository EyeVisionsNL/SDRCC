"""Generic multi-receiver Runtime Manager with a read-only v1 reservation bridge."""

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


class RuntimeManager:
    """Own generic runtime snapshots while v1 remains authoritative."""

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
                        capabilities=capabilities,
                    )
                else:
                    runtime.update_configuration(name=name, serial=serial, capabilities=capabilities)

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
        except Exception as error:  # observer failure must never break SDRCC
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
            "version": "v0.30.1c",
            "architecture": "runtime-v2-reservation-bridge",
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
                "Runtime v2 mirrors live reservation and active-mission metadata.",
                "Hardware health probing is not active yet.",
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
