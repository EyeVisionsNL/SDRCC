#!/usr/bin/env python3
"""Read-only plugin runtime observation foundation for SDRCC.

This module composes plugin metadata, assignments and receiver observations.
It deliberately does not:
- load executable plugin code dynamically;
- start or stop services;
- reserve or release receivers;
- start missions or decoders;
- persist runtime state.

Receiver Manager remains the receiver authority. Plugin Registry remains the
metadata authority.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from core import plugin_registry
from core import receiver_runtime


RuntimeReader = Callable[[], dict[str, Any]]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _services_for_plugin(
    plugin_id: str,
    receiver: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(receiver, dict):
        return []

    result = []
    for item in receiver.get("observed_services", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("role") or "").strip().lower() != plugin_id:
            continue
        result.append(deepcopy(item))
    return result


def _mission_for_plugin(
    plugin: dict[str, Any],
    receiver: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(receiver, dict):
        return None

    mission = receiver.get("observed_mission")
    if not isinstance(mission, dict):
        return None

    executor = str(plugin.get("executor") or "").strip().lower()
    if executor == "satdump":
        return deepcopy(mission)

    mission_type = str(
        mission.get("plugin_id")
        or mission.get("mission_type")
        or mission.get("mode")
        or ""
    ).strip().lower()
    return deepcopy(mission) if mission_type == plugin["id"] else None


def _derive_state(
    plugin: dict[str, Any],
    receiver_id: str | None,
    receiver: dict[str, Any] | None,
    services: list[dict[str, Any]],
    mission: dict[str, Any] | None,
) -> str:
    if plugin.get("status") != "active":
        return "PLANNED"

    if not receiver_id:
        return "UNASSIGNED"

    if isinstance(mission, dict):
        return "MISSION_ACTIVE"

    if any(bool(item.get("active")) for item in services):
        return "SERVICE_ACTIVE"

    if isinstance(receiver, dict) and receiver.get("reserved"):
        return "RECEIVER_RESERVED"

    return "READY"


class PluginRuntime:
    """Build one immutable read-only plugin observation snapshot."""

    def __init__(self, *, runtime_reader: RuntimeReader | None = None) -> None:
        self._runtime_reader = runtime_reader or receiver_runtime.get_snapshot

    def get_snapshot(self, *, include_planned: bool = True) -> dict[str, Any]:
        observed_at = _now()
        runtime = self._runtime_reader()
        assignments = runtime.get("assignments")
        if not isinstance(assignments, dict):
            assignments = {}

        receivers = runtime.get("receivers")
        if not isinstance(receivers, dict):
            receivers = {}

        plugins = []
        for plugin in plugin_registry.get_plugins(
            include_planned=include_planned,
        ):
            plugin_id = plugin["id"]
            role = plugin["assignment_role"]
            receiver_id = assignments.get(role)
            receiver = receivers.get(receiver_id) if receiver_id else None
            services = _services_for_plugin(plugin_id, receiver)
            mission = _mission_for_plugin(plugin, receiver)
            runtime_state = _derive_state(
                plugin,
                receiver_id,
                receiver,
                services,
                mission,
            )

            plugins.append({
                "plugin_id": plugin_id,
                "label": plugin["label"],
                "status": plugin["status"],
                "executor": plugin["executor"],
                "capabilities": list(plugin["capabilities"]),
                "assignment_role": role,
                "receiver_id": receiver_id,
                "receiver": (
                    deepcopy(receiver.get("device"))
                    if isinstance(receiver, dict)
                    else None
                ),
                "services": services,
                "mission": mission,
                "runtime_state": runtime_state,
                "available": runtime_state in {
                    "READY",
                    "SERVICE_ACTIVE",
                    "MISSION_ACTIVE",
                },
                "read_only": True,
                "updated_at": observed_at,
            })

        states = {
            item["plugin_id"]: item["runtime_state"]
            for item in plugins
        }

        return {
            "ok": bool(runtime.get("ok", True)),
            "read_only": True,
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "source": "plugin_runtime",
            "include_planned": include_planned,
            "plugin_count": len(plugins),
            "states": states,
            "plugins": plugins,
            "updated_at": observed_at,
        }


_RUNTIME = PluginRuntime()


def get_snapshot(*, include_planned: bool = True) -> dict[str, Any]:
    """Return the current read-only plugin runtime snapshot."""
    return _RUNTIME.get_snapshot(include_planned=include_planned)
