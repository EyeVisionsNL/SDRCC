#!/usr/bin/env python3
"""Receiver Manager projection for mission and restore contexts.

This module remains observer-only. Receiver Manager is the sole writer and its
existing state file is the only runtime source for persisted handovers.
"""
from __future__ import annotations

from typing import Any

from core import config
from core import plugin_registry
from core import receiver_manager

VERSION = "0.54.0b"


def _read_runtime_contexts() -> dict[str, Any]:
    snapshot = receiver_manager.get_status()
    reservations = [
        item for item in snapshot.get("canonical_reservations", {}).values()
        if isinstance(item, dict)
    ]
    last_releases = [
        item for item in snapshot.get("canonical_last_releases", {}).values()
        if isinstance(item, dict)
    ]
    active = reservations[0] if len(reservations) == 1 else None
    latest_release = max(
        last_releases,
        key=lambda item: str(item.get("released_at") or ""),
        default=None,
    )
    source = active or latest_release or {}
    return {
        "mission_context": active,
        "restore_context": (
            (active or {}).get("handover")
            or (latest_release or {}).get("handover")
        ),
        "reservations": reservations,
        "last_releases": last_releases,
        "updated_at": (
            ((active or {}).get("handover") or {}).get("updated_at")
            or source.get("released_at")
            or source.get("reserved_at")
        ),
    }


def validate_contract() -> dict[str, Any]:
    policy = config.get_assignment_restore_policy()
    errors: list[str] = []
    for role, receiver_id in policy["mission_assignments"].items():
        plugin = plugin_registry.get_plugin(role)
        if plugin is None:
            errors.append(f"Mission role zonder plugin: {role}")
        elif "mission_planning" not in plugin.get("capabilities", []):
            errors.append(f"Plugin is niet mission-capable: {role}")
        if receiver_id not in policy["receiver_ids"]:
            errors.append(f"Ongeldige receiver voor {role}: {receiver_id}")

    assigned_defaults: set[str] = set()
    for receiver_id, plugin_ids in policy["receiver_defaults"].items():
        if receiver_id not in policy["receiver_ids"]:
            errors.append(f"Onbekende default receiver: {receiver_id}")
        for plugin_id in plugin_ids:
            plugin = plugin_registry.get_plugin(plugin_id)
            if plugin is None:
                errors.append(f"Default plugin ontbreekt: {plugin_id}")
            elif "continuous_receive" not in plugin.get("capabilities", []):
                errors.append(f"Default plugin is niet continuous: {plugin_id}")
            if plugin_id in assigned_defaults:
                errors.append(f"Default plugin dubbel toegewezen: {plugin_id}")
            assigned_defaults.add(plugin_id)

    return {"ok": not errors, "errors": errors, "version": VERSION}


def get_snapshot() -> dict[str, Any]:
    policy = config.get_assignment_restore_policy()
    runtime = _read_runtime_contexts()
    validation = validate_contract()
    return {
        "ok": validation["ok"],
        "version": VERSION,
        "read_only": False,
        "authority": "receiver_manager",
        "service_authority": "existing_dashboard_systemctl_path",
        "receiver_authority": True,
        "mission_engine_authority": False,
        "execution_enabled": True,
        "restore_enabled": True,
        "mission_assignments": policy["mission_assignments"],
        "receiver_defaults": policy["receiver_defaults"],
        "supported": {
            "mission_roles": policy["mission_assignment_roles"],
            "default_plugins": policy["default_context_plugins"],
            "receivers": policy["receiver_ids"],
        },
        "mission_context": runtime["mission_context"],
        "restore_context": runtime["restore_context"],
        "reservations": runtime["reservations"],
        "last_releases": runtime["last_releases"],
        "updated_at": runtime["updated_at"],
        "validation": validation,
    }
