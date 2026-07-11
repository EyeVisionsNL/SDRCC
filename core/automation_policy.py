#!/usr/bin/env python3

"""Persistent automation policy for SDRCC.

The policy decides which steps the autonomous mission controller is allowed
to perform. Manual controls remain available regardless of these settings.
"""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

from core import event_bus
from core import config as config_core


POLICY_FIELDS = {
    "auto_preflight": "Automatische preflight",
    "reserve_receiver": "Receiver automatisch reserveren",
    "prepare_sdr": "SDR automatisch voorbereiden",
    "start_recording": "Opname automatisch starten",
    "start_satdump": "SatDump automatisch starten",
    "process_images": "Images automatisch verwerken",
    "archive_mission": "Automatisch archiveren",
    "restore_services": "Receiver-services automatisch herstellen",
}

DEFAULT_POLICY = {
    "auto_preflight": True,
    "reserve_receiver": True,
    "prepare_sdr": True,
    "start_recording": True,
    "start_satdump": True,
    "process_images": True,
    "archive_mission": True,
    "restore_services": True,
}

_lock = RLock()


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "aan"}:
            return True
        if normalized in {"0", "false", "no", "off", "uit"}:
            return False
    raise ValueError(f"Ongeldige aan/uit-waarde: {value!r}")


def get_policy() -> dict[str, bool]:
    """Return the complete policy with safe defaults."""

    with _lock:
        stored = config_core.get_automation_policy_config()
        policy = deepcopy(DEFAULT_POLICY)
        for key in POLICY_FIELDS:
            if key in stored:
                try:
                    policy[key] = _coerce_bool(stored[key])
                except ValueError:
                    policy[key] = DEFAULT_POLICY[key]
        return policy


def update_policy(changes: dict[str, Any]) -> dict[str, bool]:
    """Validate, persist and publish changed automation switches."""

    if not isinstance(changes, dict):
        raise ValueError("Automation Policy moet een object zijn")

    unknown = sorted(set(changes) - set(POLICY_FIELDS))
    if unknown:
        raise ValueError(
            "Onbekende Automation Policy-instelling(en): " + ", ".join(unknown)
        )

    with _lock:
        previous = get_policy()
        updated = dict(previous)
        for key, value in changes.items():
            updated[key] = _coerce_bool(value)

        config_core.set_automation_policy_config(updated)

    changed = {
        key: updated[key]
        for key in POLICY_FIELDS
        if previous.get(key) != updated.get(key)
    }

    if changed:
        detail = ", ".join(
            f"{POLICY_FIELDS[key]}={'AAN' if value else 'UIT'}"
            for key, value in changed.items()
        )
        event_bus.publish_automation(
            "INFO",
            "Automation Policy gewijzigd",
            detail,
            data={
                "changed": changed,
                "policy": updated,
            },
        )

    return updated


def is_enabled(name: str) -> bool:
    if name not in POLICY_FIELDS:
        raise KeyError(f"Onbekende Automation Policy-instelling: {name}")
    return bool(get_policy()[name])


def get_payload(mode: str | None = None) -> dict[str, Any]:
    policy = get_policy()
    return {
        "mode": str(mode or "MANUAL").upper(),
        "policy": policy,
        "labels": dict(POLICY_FIELDS),
        "manual_override": True,
    }
