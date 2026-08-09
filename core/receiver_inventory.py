#!/usr/bin/env python3
"""Read-only Receiver Inventory runtime aggregation for SDRCC v0.50.0b.

Receiver Registry remains the physical identity authority.
Receiver Manager and Receiver Runtime remain the reservation/runtime authorities.
Plugin Runtime remains the plugin assignment and service observation source.

This module only combines existing observations for display. It does not reserve
receivers, change assignments, start services, or alter Mission Engine state.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from core import plugin_runtime, receiver_registry, receiver_runtime

VERSION = "0.50.0b"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalise_receiver_id(value: Any) -> str | None:
    """Resolve runtime aliases and canonical ids through Receiver Registry."""
    if value is None:
        return None
    return receiver_registry.resolve_id(value)


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _plugins_for_receiver(
    canonical_id: str,
    plugin_snapshot: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return configured roles, plugin summaries and service observations."""
    roles: list[str] = []
    plugins: list[dict[str, Any]] = []
    services: list[dict[str, Any]] = []

    raw_plugins = plugin_snapshot.get("plugins")
    if not isinstance(raw_plugins, list):
        raw_plugins = []

    for plugin in raw_plugins:
        if not isinstance(plugin, dict):
            continue
        plugin_receiver = _normalise_receiver_id(
            plugin.get("receiver_id")
            or (plugin.get("receiver") or {}).get("canonical_id")
            or (plugin.get("receiver") or {}).get("runtime_id")
        )
        if plugin_receiver != canonical_id:
            continue

        role = plugin.get("assignment_role") or plugin.get("plugin_id")
        if role:
            roles.append(role)

        plugins.append({
            "plugin_id": plugin.get("plugin_id"),
            "label": plugin.get("label"),
            "assignment_role": role,
            "runtime_state": plugin.get("runtime_state"),
            "executor": plugin.get("executor"),
            "available": plugin.get("available"),
            "status": plugin.get("status"),
        })

        plugin_services = plugin.get("services")
        if not isinstance(plugin_services, list):
            continue
        for service in plugin_services:
            if not isinstance(service, dict):
                continue
            item = deepcopy(service)
            item.setdefault("role", role)
            if not any(
                existing.get("service") == item.get("service")
                and existing.get("role") == item.get("role")
                for existing in services
            ):
                services.append(item)

    return _unique_strings(roles), plugins, services


def _merge_services(
    runtime_services: Any,
    plugin_services: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge duplicate read-only observations without changing their meaning."""
    merged: list[dict[str, Any]] = []
    sources = runtime_services if isinstance(runtime_services, list) else []
    for source in [*sources, *plugin_services]:
        if not isinstance(source, dict):
            continue
        key = (source.get("service"), source.get("role"))
        existing = next(
            (
                item
                for item in merged
                if (item.get("service"), item.get("role")) == key
            ),
            None,
        )
        if existing is None:
            merged.append(deepcopy(source))
        else:
            for field, value in source.items():
                if existing.get(field) in (None, "", "unknown"):
                    existing[field] = deepcopy(value)
                if field == "active" and bool(value):
                    existing[field] = True
    return merged


def _display_state(observed: dict[str, Any], services: list[dict[str, Any]]) -> str:
    """Map existing runtime observations to a concise inventory state."""
    state = str(observed.get("runtime_state") or "").strip().upper()

    if state in {"MISSION_ACTIVE", "ACTIVE"} or isinstance(
        observed.get("observed_mission"), dict
    ):
        return "ACTIVE"
    if state == "RESERVED" or bool(observed.get("reserved")):
        return "RESERVED"
    if state == "SERVICE_ACTIVE" or any(
        bool(service.get("active")) for service in services
    ):
        return "ACTIVE"
    if state in {"IDLE", "READY", "RELEASED"}:
        return "READY"
    if state in {"OFFLINE", "MISSING", "NOT_PRESENT"}:
        return "OFFLINE"
    return state or "UNKNOWN"


def get_snapshot() -> dict[str, Any]:
    """Return one immutable read-only Receiver Inventory snapshot."""
    registry = receiver_registry.public_snapshot()
    runtime = receiver_runtime.get_snapshot()
    plugins = plugin_runtime.get_snapshot(include_planned=True)

    runtime_receivers = runtime.get("receivers")
    if not isinstance(runtime_receivers, dict):
        runtime_receivers = {}

    items: list[dict[str, Any]] = []
    for registered in registry.get("receivers", []):
        if not isinstance(registered, dict):
            continue

        canonical = _normalise_receiver_id(
            registered.get("canonical_id")
            or registered.get("registry_id")
            or registered.get("id")
        )
        if not canonical:
            continue

        observed = runtime_receivers.get(canonical, {})
        if not isinstance(observed, dict):
            observed = {}

        plugin_roles, plugin_items, plugin_services = _plugins_for_receiver(
            canonical,
            plugins,
        )
        runtime_roles = observed.get("configured_roles")
        if not isinstance(runtime_roles, list):
            runtime_roles = []
        roles = _unique_strings([*runtime_roles, *plugin_roles])

        services = _merge_services(
            observed.get("observed_services"),
            plugin_services,
        )
        active_services = _unique_strings([
            service.get("service")
            for service in services
            if bool(service.get("active"))
        ])

        reserved = bool(observed.get("reserved"))
        state = _display_state(observed, services)

        items.append({
            "number": registered.get("number"),
            "canonical_id": canonical,
            "runtime_id": registered.get("runtime_id"),
            "aliases": registered.get("aliases", []),
            "name": registered.get("name"),
            "description": registered.get("description"),
            "driver": registered.get("driver"),
            "serial": registered.get("serial"),
            "enabled": registered.get("enabled", True),
            "locked": registered.get("locked", False),
            "capabilities": registered.get("capabilities", []),
            "assigned_roles": roles,
            "plugins": plugin_items,
            "runtime_state": state,
            "observed_runtime_state": observed.get("runtime_state"),
            "available": not reserved and not active_services,
            "reserved": reserved,
            "reservation": deepcopy(observed.get("reservation")),
            "active_services": active_services,
            "services": services,
            "observed_mission": deepcopy(observed.get("observed_mission")),
        })

    return {
        "ok": True,
        "version": VERSION,
        "read_only": True,
        "behavior_changed": False,
        "identity_authority": "receiver_registry",
        "runtime_authority": "receiver_manager",
        "plugin_source": "plugin_runtime",
        "source": "receiver_inventory",
        "receiver_count": len(items),
        "receivers": items,
        "updated_at": _now(),
    }
