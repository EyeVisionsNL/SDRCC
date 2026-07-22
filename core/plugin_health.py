#!/usr/bin/env python3
"""Read-only plugin health and validation foundation for SDRCC.

This module evaluates snapshots produced by Plugin Runtime. It does not:
- start or stop services;
- reserve or release receivers;
- alter assignments;
- execute missions or decoders;
- persist health state.

Plugin Registry remains metadata authority.
Receiver Manager remains receiver authority.
Plugin Runtime remains runtime observation source.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Callable

from core import plugin_runtime


SnapshotReader = Callable[..., dict[str, Any]]

_HEALTH_ORDER = {
    "GOOD": 0,
    "DEGRADED": 1,
    "UNAVAILABLE": 2,
    "PLANNED": 3,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _issue(code: str, message: str, *, field: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if field:
        item["field"] = field
    return item


def _evaluate_plugin(plugin: dict[str, Any], observed_at: str) -> dict[str, Any]:
    plugin_id = str(plugin.get("plugin_id") or "").strip().lower()
    status = str(plugin.get("status") or "").strip().lower()
    executor = str(plugin.get("executor") or "").strip().lower() or None
    runtime_state = str(plugin.get("runtime_state") or "").strip().upper()
    capabilities = [
        str(item).strip().lower()
        for item in plugin.get("capabilities", [])
        if str(item).strip()
    ]
    services = [
        deepcopy(item)
        for item in plugin.get("services", [])
        if isinstance(item, dict)
    ]

    warnings: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    mission_capable = bool(
        {"mission_planning", "pass_planning"} & set(capabilities)
        or executor == "satdump"
    )
    service_capable = executor == "service" or "service_control" in capabilities

    if status == "planned":
        health = "PLANNED"
        score = 0
        readiness = {
            "operational": False,
            "mission": False,
            "service": False,
        }
        return {
            "plugin_id": plugin_id,
            "label": plugin.get("label"),
            "health": health,
            "score": score,
            "ready": readiness,
            "mission_capable": mission_capable,
            "service_capable": service_capable,
            "runtime_state": runtime_state or "PLANNED",
            "receiver_id": plugin.get("receiver_id"),
            "warnings": warnings,
            "errors": errors,
            "read_only": True,
            "updated_at": observed_at,
        }

    if status != "active":
        errors.append(_issue(
            "INVALID_PLUGIN_STATUS",
            f"Pluginstatus '{status or 'missing'}' is niet inzetbaar.",
            field="status",
        ))

    if not plugin_id:
        errors.append(_issue(
            "MISSING_PLUGIN_ID",
            "Plugin-ID ontbreekt.",
            field="plugin_id",
        ))

    if not plugin.get("assignment_role"):
        errors.append(_issue(
            "MISSING_ASSIGNMENT_ROLE",
            "Assignmentrol ontbreekt.",
            field="assignment_role",
        ))

    if not capabilities:
        errors.append(_issue(
            "MISSING_CAPABILITIES",
            "Plugin declareert geen capabilities.",
            field="capabilities",
        ))

    receiver_id = plugin.get("receiver_id")
    if not receiver_id:
        errors.append(_issue(
            "RECEIVER_UNASSIGNED",
            "Actieve plugin heeft geen receiver-assignment.",
            field="receiver_id",
        ))
    elif not isinstance(plugin.get("receiver"), dict):
        errors.append(_issue(
            "RECEIVER_NOT_OBSERVED",
            "Toegewezen receiver ontbreekt in de runtime-observatie.",
            field="receiver",
        ))

    if runtime_state == "UNASSIGNED":
        errors.append(_issue(
            "RUNTIME_UNASSIGNED",
            "Plugin Runtime meldt dat de plugin niet is toegewezen.",
            field="runtime_state",
        ))
    elif runtime_state == "PLANNED":
        errors.append(_issue(
            "ACTIVE_PLUGIN_MARKED_PLANNED",
            "Actieve plugin heeft runtime-status PLANNED.",
            field="runtime_state",
        ))
    elif runtime_state not in {
        "READY",
        "SERVICE_ACTIVE",
        "RECEIVER_RESERVED",
        "MISSION_ACTIVE",
    }:
        errors.append(_issue(
            "UNKNOWN_RUNTIME_STATE",
            f"Onbekende runtime-status '{runtime_state or 'missing'}'.",
            field="runtime_state",
        ))

    active_services = [item for item in services if bool(item.get("active"))]
    observed_services = [item for item in services if bool(item.get("observed"))]
    service_errors = [
        item for item in services
        if item.get("error") not in {None, ""}
    ]

    if service_capable:
        if not services:
            errors.append(_issue(
                "SERVICE_NOT_OBSERVED",
                "Service-plugin heeft geen gekoppelde service-observatie.",
                field="services",
            ))
        elif service_errors:
            errors.append(_issue(
                "SERVICE_OBSERVATION_ERROR",
                "Minstens één service kon niet betrouwbaar worden geobserveerd.",
                field="services",
            ))
        elif not observed_services:
            errors.append(_issue(
                "SERVICE_NOT_OBSERVED",
                "Gekoppelde service is niet geobserveerd.",
                field="services",
            ))
        elif not active_services:
            warnings.append(_issue(
                "SERVICE_INACTIVE",
                "Gekoppelde service is momenteel niet actief.",
                field="services",
            ))

    if executor is None:
        errors.append(_issue(
            "MISSING_EXECUTOR",
            "Actieve plugin heeft geen executor.",
            field="executor",
        ))

    mission_ready = (
        mission_capable
        and receiver_id is not None
        and runtime_state in {"READY", "RECEIVER_RESERVED", "MISSION_ACTIVE"}
        and not errors
    )
    service_ready = (
        service_capable
        and receiver_id is not None
        and bool(active_services)
        and not errors
    )
    operational = (
        receiver_id is not None
        and runtime_state in {
            "READY",
            "SERVICE_ACTIVE",
            "RECEIVER_RESERVED",
            "MISSION_ACTIVE",
        }
        and not errors
        and (not service_capable or bool(active_services))
    )

    if errors:
        health = "UNAVAILABLE"
        score = max(0, 100 - 35 * len(errors) - 10 * len(warnings))
    elif warnings:
        health = "DEGRADED"
        score = max(50, 100 - 15 * len(warnings))
    else:
        health = "GOOD"
        score = 100

    return {
        "plugin_id": plugin_id,
        "label": plugin.get("label"),
        "health": health,
        "score": score,
        "ready": {
            "operational": operational,
            "mission": mission_ready,
            "service": service_ready,
        },
        "mission_capable": mission_capable,
        "service_capable": service_capable,
        "runtime_state": runtime_state,
        "receiver_id": receiver_id,
        "warnings": warnings,
        "errors": errors,
        "read_only": True,
        "updated_at": observed_at,
    }


class PluginHealth:
    """Evaluate one immutable Plugin Runtime snapshot."""

    def __init__(self, *, snapshot_reader: SnapshotReader | None = None) -> None:
        self._snapshot_reader = snapshot_reader or plugin_runtime.get_snapshot

    def get_snapshot(self, *, include_planned: bool = True) -> dict[str, Any]:
        observed_at = _now()
        runtime = self._snapshot_reader(include_planned=include_planned)
        runtime_plugins = runtime.get("plugins")
        if not isinstance(runtime_plugins, list):
            runtime_plugins = []

        plugins = [
            _evaluate_plugin(plugin, observed_at)
            for plugin in runtime_plugins
            if isinstance(plugin, dict)
        ]

        counts = {
            "GOOD": 0,
            "DEGRADED": 0,
            "UNAVAILABLE": 0,
            "PLANNED": 0,
        }
        for item in plugins:
            counts[item["health"]] += 1

        active_health = [
            item["health"]
            for item in plugins
            if item["health"] != "PLANNED"
        ]
        overall_health = (
            max(active_health, key=lambda value: _HEALTH_ORDER[value])
            if active_health
            else "PLANNED"
        )

        mission_ready = [
            item["plugin_id"]
            for item in plugins
            if item["ready"]["mission"]
        ]
        service_ready = [
            item["plugin_id"]
            for item in plugins
            if item["ready"]["service"]
        ]
        operational = [
            item["plugin_id"]
            for item in plugins
            if item["ready"]["operational"]
        ]

        return {
            "ok": bool(runtime.get("ok", True)) and counts["UNAVAILABLE"] == 0,
            "read_only": True,
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "runtime_source": "plugin_runtime",
            "source": "plugin_health",
            "include_planned": include_planned,
            "overall_health": overall_health,
            "plugin_count": len(plugins),
            "counts": counts,
            "ready": {
                "operational": operational,
                "mission": mission_ready,
                "service": service_ready,
            },
            "plugins": plugins,
            "updated_at": observed_at,
        }


_HEALTH = PluginHealth()


def get_snapshot(*, include_planned: bool = True) -> dict[str, Any]:
    """Return the current read-only plugin health snapshot."""
    return _HEALTH.get_snapshot(include_planned=include_planned)
