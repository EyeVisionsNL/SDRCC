"""Generic multi-receiver Runtime Manager foundation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from core import config as config_core

from .receiver_runtime import ReceiverRuntime

_RECEIVER_ID = re.compile(r"^sdr\d+$", re.IGNORECASE)
_DEFAULT_CAPABILITIES = (
    "weather",
    "voice",
    "ais",
    "adsb",
    "vhf",
    "uhf",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalise_capabilities(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple, set)):
        return _DEFAULT_CAPABILITIES
    result = tuple(
        sorted(
            {
                str(item).strip().lower()
                for item in value
                if str(item).strip()
            }
        )
    )
    return result or _DEFAULT_CAPABILITIES


class RuntimeManager:
    """Own the generic runtime state for all configured physical receivers.

    This foundation runs alongside the existing receiver and mission engines.
    It does not reserve hardware or start/stop mission processes yet.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._receivers: dict[str, ReceiverRuntime] = {}
        self._started_at = _utc_now()
        self.refresh_configuration()

    def refresh_configuration(self) -> None:
        station = config_core.load_station() or {}
        configured: dict[str, dict[str, Any]] = {
            str(receiver_id).lower(): receiver_config
            for receiver_id, receiver_config in station.items()
            if _RECEIVER_ID.fullmatch(str(receiver_id))
            and isinstance(receiver_config, dict)
        }

        with self._lock:
            for receiver_id in sorted(configured):
                receiver_config = configured[receiver_id]
                name = str(receiver_config.get("name") or receiver_id.upper())
                raw_serial = receiver_config.get("serial")
                serial = None if raw_serial is None else str(raw_serial)
                capabilities = _normalise_capabilities(
                    receiver_config.get("capabilities")
                )

                runtime = self._receivers.get(receiver_id)
                if runtime is None:
                    self._receivers[receiver_id] = ReceiverRuntime(
                        receiver_id=receiver_id,
                        name=name,
                        serial=serial,
                        capabilities=capabilities,
                    )
                else:
                    runtime.update_configuration(
                        name=name,
                        serial=serial,
                        capabilities=capabilities,
                    )

            # A removed receiver remains visible while it owns runtime work.
            for receiver_id in set(self._receivers) - set(configured):
                runtime = self._receivers[receiver_id]
                if runtime.reservation is None and runtime.active_mission is None:
                    runtime.transition(
                        "OFFLINE",
                        detail="Receiver is no longer present in station.yaml",
                    )

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
        with self._lock:
            receivers = {
                receiver_id: self._receivers[receiver_id].snapshot()
                for receiver_id in sorted(self._receivers)
            }
        return {
            "ok": True,
            "version": "v0.30.1b",
            "architecture": "runtime-v2-foundation",
            "mode": "parallel-observer",
            "receiver_count": len(receivers),
            "receivers": receivers,
            "started_at": self._started_at,
            "updated_at": _utc_now(),
            "notes": [
                "Existing mission execution remains authoritative.",
                "Hardware health probing is not active in this foundation.",
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
