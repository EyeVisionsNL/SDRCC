#!/usr/bin/env python3
"""Central read-only Plugin Manager facade for SDRCC.

The Plugin Manager combines existing Plugin Registry, Plugin Runtime,
Plugin Health, Execution Adapter discovery and read-only execution planning
snapshots behind one stable interface.

It deliberately does not:
- load or unload plugin code;
- start or stop services;
- reserve or release receivers;
- alter assignments;
- start missions or decoders;
- calculate independent runtime or health state;
- persist manager state.

Plugin Registry remains metadata authority.
Receiver Manager remains receiver authority.
Plugin Runtime remains runtime observation source.
Plugin Health remains validation and readiness source.
Execution Factory remains read-only adapter discovery and planning source.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from core import execution_factory
from core import plugin_health
from core import plugin_registry
from core import plugin_runtime


RegistryReader = Callable[..., dict[str, Any]]
RuntimeReader = Callable[..., dict[str, Any]]
HealthReader = Callable[..., dict[str, Any]]
ExecutionReader = Callable[..., dict[str, Any]]
PlanningReader = Callable[..., dict[str, Any]]

_MANAGER_VERSION = "0.42.0c"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _plugin_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    plugins = snapshot.get("plugins")
    if not isinstance(plugins, list):
        return result

    for item in plugins:
        if not isinstance(item, dict):
            continue
        plugin_id = str(
            item.get("id")
            or item.get("plugin_id")
            or ""
        ).strip().lower()
        if plugin_id:
            result[plugin_id] = item
    return result


def _merge_plugins(
    registry: dict[str, Any],
    runtime: dict[str, Any],
    health: dict[str, Any],
    execution: dict[str, Any],
    planning: dict[str, Any],
) -> list[dict[str, Any]]:
    runtime_by_id = _plugin_map(runtime)
    health_by_id = _plugin_map(health)
    execution_by_id = _plugin_map(execution)
    planning_by_id = {
        str(item.get("plugin_id") or "").strip().lower(): item
        for item in planning.get("plans", [])
        if isinstance(item, dict) and item.get("plugin_id")
    }
    result: list[dict[str, Any]] = []

    registry_plugins = registry.get("plugins")
    if not isinstance(registry_plugins, list):
        registry_plugins = []

    for metadata in registry_plugins:
        if not isinstance(metadata, dict):
            continue

        plugin_id = str(metadata.get("id") or "").strip().lower()
        if not plugin_id:
            continue

        result.append({
            "plugin_id": plugin_id,
            "metadata": deepcopy(metadata),
            "runtime": deepcopy(runtime_by_id.get(plugin_id)),
            "health": deepcopy(health_by_id.get(plugin_id)),
            "execution": deepcopy(execution_by_id.get(plugin_id)),
            "execution_plan": deepcopy(planning_by_id.get(plugin_id)),
        })

    return result


def _statistics(
    plugins: list[dict[str, Any]],
    runtime: dict[str, Any],
    health: dict[str, Any],
) -> dict[str, Any]:
    active = 0
    planned = 0
    mission_capable = 0
    service_capable = 0

    for item in plugins:
        metadata = item.get("metadata")
        health_item = item.get("health")

        if isinstance(metadata, dict):
            if metadata.get("status") == "active":
                active += 1
            elif metadata.get("status") == "planned":
                planned += 1

        if isinstance(health_item, dict):
            mission_capable += int(bool(health_item.get("mission_capable")))
            service_capable += int(bool(health_item.get("service_capable")))

    health_counts = health.get("counts")
    if not isinstance(health_counts, dict):
        health_counts = {}

    runtime_states = runtime.get("states")
    if not isinstance(runtime_states, dict):
        runtime_states = {}

    state_counts: dict[str, int] = {}
    for state in runtime_states.values():
        normalized = str(state or "UNKNOWN").strip().upper()
        state_counts[normalized] = state_counts.get(normalized, 0) + 1

    return {
        "total": len(plugins),
        "active": active,
        "planned": planned,
        "mission_capable": mission_capable,
        "service_capable": service_capable,
        "health": deepcopy(health_counts),
        "runtime_states": state_counts,
    }


class PluginManager:
    """Read-only facade over existing plugin information layers."""

    def __init__(
        self,
        *,
        registry_reader: RegistryReader | None = None,
        runtime_reader: RuntimeReader | None = None,
        health_reader: HealthReader | None = None,
        execution_reader: ExecutionReader | None = None,
        planning_reader: PlanningReader | None = None,
    ) -> None:
        self._registry_reader = (
            registry_reader or plugin_registry.get_registry_snapshot
        )
        self._runtime_reader = runtime_reader or plugin_runtime.get_snapshot
        self._health_reader = health_reader or plugin_health.get_snapshot
        self._execution_reader = (
            execution_reader or execution_factory.get_catalog_snapshot
        )
        self._planning_reader = (
            planning_reader or execution_factory.get_plan_catalog
        )

    def get_snapshot(self, *, include_planned: bool = True) -> dict[str, Any]:
        """Return one combined immutable plugin information snapshot."""
        generated_at = _now()

        registry = self._registry_reader(include_planned=include_planned)
        runtime = self._runtime_reader(include_planned=include_planned)
        health = self._health_reader(include_planned=include_planned)
        execution = self._execution_reader(
            include_planned=include_planned,
        )
        planning = self._planning_reader(
            include_planned=include_planned,
        )

        plugins = _merge_plugins(
            registry, runtime, health, execution, planning
        )
        statistics = _statistics(plugins, runtime, health)

        source_status = {
            "registry": bool(registry.get("ok", True)),
            "runtime": bool(runtime.get("ok", True)),
            "health": bool(health.get("ok", True)),
            "execution": bool(execution.get("ok", True)),
            "planning": bool(planning.get("ok", True)),
        }

        ready = health.get("ready")
        if not isinstance(ready, dict):
            ready = {}

        summary = {
            "overall_health": health.get("overall_health", "UNKNOWN"),
            "operational_plugins": deepcopy(ready.get("operational", [])),
            "mission_ready_plugins": deepcopy(ready.get("mission", [])),
            "service_ready_plugins": deepcopy(ready.get("service", [])),
            "execution_adapters_valid": bool(execution.get("ok", True)),
            "execution_foundation_only": bool(
                execution.get("foundation_only", False)
            ),
            "execution_plans_valid": bool(planning.get("ok", True)),
            "execution_planning_only": bool(
                planning.get("planning_only", False)
            ),
            "sources_ok": all(source_status.values()),
        }

        return {
            "ok": all(source_status.values()),
            "read_only": True,
            "source": "plugin_manager",
            "manager_version": _MANAGER_VERSION,
            "schema_version": 1,
            "include_planned": include_planned,
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "runtime_source": "plugin_runtime",
            "health_source": "plugin_health",
            "execution_source": "execution_factory",
            "execution_authority": "delegation_only",
            "planning_source": "execution_factory",
            "planning_authority": "description_only",
            "source_status": source_status,
            "summary": summary,
            "statistics": statistics,
            "plugins": plugins,
            "registry": deepcopy(registry),
            "runtime": deepcopy(runtime),
            "health": deepcopy(health),
            "execution": deepcopy(execution),
            "planning": deepcopy(planning),
            "generated_at": generated_at,
        }

    def get_plugins(self, *, include_planned: bool = True) -> list[dict[str, Any]]:
        """Return combined plugin records in stable Registry order."""
        return self.get_snapshot(
            include_planned=include_planned,
        )["plugins"]

    def get_plugin(
        self,
        plugin_id: str,
        *,
        include_planned: bool = True,
    ) -> dict[str, Any] | None:
        """Return one combined plugin record by ID."""
        normalized = str(plugin_id or "").strip().lower()
        if not normalized:
            return None

        for item in self.get_plugins(include_planned=include_planned):
            if item.get("plugin_id") == normalized:
                return item
        return None

    def get_summary(self, *, include_planned: bool = True) -> dict[str, Any]:
        """Return the manager summary."""
        return self.get_snapshot(
            include_planned=include_planned,
        )["summary"]

    def get_statistics(self, *, include_planned: bool = True) -> dict[str, Any]:
        """Return manager statistics."""
        return self.get_snapshot(
            include_planned=include_planned,
        )["statistics"]


_MANAGER = PluginManager()


def get_snapshot(*, include_planned: bool = True) -> dict[str, Any]:
    """Return the current Plugin Manager snapshot."""
    return _MANAGER.get_snapshot(include_planned=include_planned)


def get_plugins(*, include_planned: bool = True) -> list[dict[str, Any]]:
    """Return combined plugin records."""
    return _MANAGER.get_plugins(include_planned=include_planned)


def get_plugin(
    plugin_id: str,
    *,
    include_planned: bool = True,
) -> dict[str, Any] | None:
    """Return one combined plugin record."""
    return _MANAGER.get_plugin(
        plugin_id,
        include_planned=include_planned,
    )


def get_summary(*, include_planned: bool = True) -> dict[str, Any]:
    """Return the current manager summary."""
    return _MANAGER.get_summary(include_planned=include_planned)


def get_statistics(*, include_planned: bool = True) -> dict[str, Any]:
    """Return current manager statistics."""
    return _MANAGER.get_statistics(include_planned=include_planned)
