#!/usr/bin/env python3
"""Read-only Mission Assignment and Restore Context foundation.

v0.47.1a deliberately does not stop/start services, reserve receivers, or
change Mission Engine state. It exposes validated configuration and any future
persisted context document through one central observation contract.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core import config
from core import plugin_registry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "state" / "receiver_contexts.json"
VERSION = "0.48.0a"


def _empty_runtime_contexts() -> dict[str, Any]:
    return {
        "mission_context": None,
        "restore_context": None,
        "updated_at": None,
    }


def _read_runtime_contexts() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return _empty_runtime_contexts()
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_runtime_contexts()
    if not isinstance(payload, dict):
        return _empty_runtime_contexts()
    return {
        "mission_context": payload.get("mission_context"),
        "restore_context": payload.get("restore_context"),
        "updated_at": payload.get("updated_at"),
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
        "updated_at": runtime["updated_at"],
        "validation": validation,
    }
