#!/usr/bin/env python3
"""Read-only plugin capability query layer for SDRCC.

The Plugin Registry remains the metadata authority. This module only provides
stable capability queries. It owns no cache, state, lifecycle, runtime,
receiver, health, service, or scheduler logic.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Callable

from core import plugin_registry


CAPABILITY_SCHEMA_VERSION = 1
CAPABILITY_LAYER_VERSION = "0.39.0b"


def _normalize(value: object) -> str:
    return str(value or "").strip().lower()


def _read_registry(
    reader: Callable[..., dict],
    *,
    include_planned: bool,
) -> dict:
    snapshot = reader(include_planned=include_planned)
    if not isinstance(snapshot, dict):
        raise TypeError("Plugin Registry snapshot moet een dictionary zijn.")
    if not isinstance(snapshot.get("plugins", []), list):
        raise TypeError("Plugin Registry plugins moet een lijst zijn.")
    return deepcopy(snapshot)


class PluginCapabilityLayer:
    """Read-only capability facade backed by Plugin Registry."""

    def __init__(
        self,
        *,
        registry_reader: Callable[..., dict] | None = None,
    ) -> None:
        self._registry_reader = (
            registry_reader or plugin_registry.get_registry_snapshot
        )

    def get_snapshot(self, *, include_planned: bool = True) -> dict:
        registry = _read_registry(
            self._registry_reader,
            include_planned=include_planned,
        )

        plugins: dict[str, list[str]] = {}
        capability_map: dict[str, list[str]] = {}

        for item in registry.get("plugins", []):
            if not isinstance(item, dict):
                continue

            plugin_id = _normalize(item.get("id"))
            if not plugin_id:
                continue

            capabilities: list[str] = []
            for raw_capability in item.get("capabilities", []):
                capability = _normalize(raw_capability)
                if capability and capability not in capabilities:
                    capabilities.append(capability)

            plugins[plugin_id] = capabilities
            for capability in capabilities:
                capability_map.setdefault(capability, []).append(plugin_id)

        return {
            "ok": True,
            "read_only": True,
            "source": "plugin_capabilities",
            "metadata_authority": "plugin_registry",
            "schema_version": CAPABILITY_SCHEMA_VERSION,
            "layer_version": CAPABILITY_LAYER_VERSION,
            "include_planned": bool(include_planned),
            "plugin_count": len(plugins),
            "capability_count": len(capability_map),
            "plugins": plugins,
            "capabilities": capability_map,
        }

    def get_capability_map(
        self,
        *,
        include_planned: bool = True,
    ) -> dict[str, list[str]]:
        return deepcopy(
            self.get_snapshot(include_planned=include_planned)["capabilities"]
        )

    def get_capabilities(
        self,
        plugin_id: str,
        *,
        include_planned: bool = True,
    ) -> list[str]:
        normalized = _normalize(plugin_id)
        if not normalized:
            return []
        snapshot = self.get_snapshot(include_planned=include_planned)
        return list(snapshot["plugins"].get(normalized, []))

    def has_capability(
        self,
        plugin_id: str,
        capability: str,
        *,
        include_planned: bool = True,
    ) -> bool:
        normalized = _normalize(capability)
        if not normalized:
            return False
        return normalized in self.get_capabilities(
            plugin_id,
            include_planned=include_planned,
        )

    def get_plugins_with_capability(
        self,
        capability: str,
        *,
        include_planned: bool = True,
    ) -> list[str]:
        normalized = _normalize(capability)
        if not normalized:
            return []
        return list(
            self.get_capability_map(
                include_planned=include_planned,
            ).get(normalized, [])
        )


_LAYER = PluginCapabilityLayer()


def get_snapshot(*, include_planned: bool = True) -> dict:
    return _LAYER.get_snapshot(include_planned=include_planned)


def get_capability_map(
    *,
    include_planned: bool = True,
) -> dict[str, list[str]]:
    return _LAYER.get_capability_map(include_planned=include_planned)


def get_capabilities(
    plugin_id: str,
    *,
    include_planned: bool = True,
) -> list[str]:
    return _LAYER.get_capabilities(
        plugin_id,
        include_planned=include_planned,
    )


def has_capability(
    plugin_id: str,
    capability: str,
    *,
    include_planned: bool = True,
) -> bool:
    return _LAYER.has_capability(
        plugin_id,
        capability,
        include_planned=include_planned,
    )


def get_plugins_with_capability(
    capability: str,
    *,
    include_planned: bool = True,
) -> list[str]:
    return _LAYER.get_plugins_with_capability(
        capability,
        include_planned=include_planned,
    )
