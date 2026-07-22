#!/usr/bin/env python3
"""Central read-only plugin metadata registry for SDRCC.

This module deliberately contains metadata only. It does not start services,
change receiver assignments, reserve hardware, or execute plugins.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Iterable


_REGISTRY = {
    "weather": {
        "id": "weather",
        "label": "Weather",
        "description": "Satellietweerontvangst en beelddecodering via SatDump.",
        "assignment_role": "weather",
        "category": "satellite",
        "status": "active",
        "receiver_type": "rtl_sdr",
        "executor": "satdump",
        "services": [],
        "capabilities": [
            "mission_planning",
            "recording",
            "decoding",
            "images",
            "live_rf",
            "rf_diagnostics",
        ],
        "dashboard": {
            "assignment": True,
            "live_status": True,
            "settings": True,
        },
    },
    "ais": {
        "id": "ais",
        "label": "AIS",
        "description": "AIS scheepsontvangst via AIS-catcher.",
        "assignment_role": "ais",
        "category": "terrestrial",
        "status": "active",
        "receiver_type": "rtl_sdr",
        "executor": "service",
        "services": ["ais-catcher.service"],
        "capabilities": [
            "continuous_receive",
            "service_control",
            "external_viewer",
        ],
        "dashboard": {
            "assignment": True,
            "live_status": True,
            "settings": False,
        },
    },
    "adsb": {
        "id": "adsb",
        "label": "ADS-B",
        "description": "ADS-B vliegtuigontvangst via readsb.",
        "assignment_role": "adsb",
        "category": "terrestrial",
        "status": "active",
        "receiver_type": "rtl_sdr",
        "executor": "service",
        "services": ["readsb.service"],
        "capabilities": [
            "continuous_receive",
            "service_control",
            "external_viewer",
        ],
        "dashboard": {
            "assignment": True,
            "live_status": True,
            "settings": False,
        },
    },
    "iss_voice": {
        "id": "iss_voice",
        "label": "ISS Voice",
        "description": "Geplande ontvangstplugin voor ISS-spraakverkeer.",
        "assignment_role": "iss_voice",
        "category": "satellite",
        "status": "planned",
        "receiver_type": "rtl_sdr",
        "executor": None,
        "services": [],
        "capabilities": [
            "pass_planning",
            "audio_receive",
            "recording",
            "live_rf",
        ],
        "dashboard": {
            "assignment": False,
            "live_status": False,
            "settings": False,
        },
    },
    "meshcore": {
        "id": "meshcore",
        "label": "MeshCore",
        "description": "Gereserveerde pluginrol voor toekomstige MeshCore-integratie.",
        "assignment_role": "meshcore",
        "category": "terrestrial",
        "status": "planned",
        "receiver_type": "rtl_sdr",
        "executor": None,
        "services": [],
        "capabilities": [
            "packet_receive",
        ],
        "dashboard": {
            "assignment": False,
            "live_status": False,
            "settings": False,
        },
    },
}


def get_plugin_roles() -> tuple[str, ...]:
    """Return plugin roles in stable registry order."""
    return tuple(_REGISTRY)


def get_plugin(plugin_id: str) -> dict | None:
    """Return a defensive copy of one plugin definition."""
    normalized = str(plugin_id or "").strip().lower()
    plugin = _REGISTRY.get(normalized)
    return deepcopy(plugin) if plugin is not None else None


def get_plugins(*, include_planned: bool = True) -> list[dict]:
    """Return all plugin definitions in stable order."""
    plugins = []
    for plugin_id in get_plugin_roles():
        plugin = get_plugin(plugin_id)
        if not include_planned and plugin["status"] != "active":
            continue
        plugins.append(plugin)
    return plugins


def is_plugin_supported(plugin_id: str) -> bool:
    """Return whether a plugin ID exists in the registry."""
    return get_plugin(plugin_id) is not None


def get_plugin_services(plugin_id: str) -> list[str]:
    """Return services owned by a plugin."""
    plugin = get_plugin(plugin_id)
    return list(plugin["services"]) if plugin else []


def get_plugin_capabilities(plugin_id: str) -> list[str]:
    """Return capabilities declared by a plugin."""
    plugin = get_plugin(plugin_id)
    return list(plugin["capabilities"]) if plugin else []


def plugin_has_capability(plugin_id: str, capability: str) -> bool:
    """Return whether a plugin declares one capability."""
    normalized = str(capability or "").strip().lower()
    return normalized in get_plugin_capabilities(plugin_id)


def get_plugins_with_capability(
    capability: str,
    *,
    include_planned: bool = True,
) -> list[dict]:
    """Return plugins that declare one capability in stable registry order."""
    normalized = str(capability or "").strip().lower()
    if not normalized:
        return []
    return [
        plugin
        for plugin in get_plugins(include_planned=include_planned)
        if normalized in plugin.get("capabilities", [])
    ]


def get_plugin_executor(plugin_id: str) -> str | None:
    """Return the configured executor type for a plugin."""
    plugin = get_plugin(plugin_id)
    return plugin.get("executor") if plugin else None


def validate_registry(
    *,
    assignment_roles: Iterable[str] | None = None,
) -> dict:
    """Validate structural integrity and optional assignment-role parity."""
    errors = []
    seen_assignment_roles = set()
    allowed_statuses = {"active", "planned"}
    allowed_categories = {"satellite", "terrestrial"}
    allowed_receiver_types = {"rtl_sdr"}

    for key, plugin in _REGISTRY.items():
        if plugin.get("id") != key:
            errors.append(f"{key}: id komt niet overeen met registratiesleutel")

        role = plugin.get("assignment_role")
        if not role:
            errors.append(f"{key}: assignment_role ontbreekt")
        elif role in seen_assignment_roles:
            errors.append(f"{key}: dubbele assignment_role {role}")
        else:
            seen_assignment_roles.add(role)

        if plugin.get("status") not in allowed_statuses:
            errors.append(f"{key}: ongeldige status")
        if plugin.get("category") not in allowed_categories:
            errors.append(f"{key}: ongeldige categorie")
        if plugin.get("receiver_type") not in allowed_receiver_types:
            errors.append(f"{key}: ongeldig receiver_type")

        services = plugin.get("services")
        if not isinstance(services, list):
            errors.append(f"{key}: services moet een lijst zijn")
        elif len(services) != len(set(services)):
            errors.append(f"{key}: dubbele service")

        capabilities = plugin.get("capabilities")
        if not isinstance(capabilities, list) or not capabilities:
            errors.append(f"{key}: capabilities ontbreekt of is leeg")
        elif len(capabilities) != len(set(capabilities)):
            errors.append(f"{key}: dubbele capability")

        dashboard = plugin.get("dashboard")
        if not isinstance(dashboard, dict):
            errors.append(f"{key}: dashboardmetadata ontbreekt")

    if assignment_roles is not None:
        configured = tuple(str(role).strip().lower() for role in assignment_roles)
        registry_roles = get_plugin_roles()
        missing = [role for role in configured if role not in registry_roles]
        extra = [role for role in registry_roles if role not in configured]
        if missing:
            errors.append(
                "Assignmentrollen zonder plugin: " + ", ".join(missing)
            )
        if extra:
            errors.append(
                "Plugins zonder assignmentrol: " + ", ".join(extra)
            )

    return {
        "ok": not errors,
        "plugin_count": len(_REGISTRY),
        "roles": list(get_plugin_roles()),
        "errors": errors,
    }


def get_registry_snapshot(*, include_planned: bool = True) -> dict:
    """Return the API-safe read-only registry payload."""
    plugins = get_plugins(include_planned=include_planned)
    return {
        "ok": True,
        "read_only": True,
        "source": "plugin_registry",
        "count": len(plugins),
        "include_planned": include_planned,
        "plugins": plugins,
    }
