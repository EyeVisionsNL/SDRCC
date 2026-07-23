#!/usr/bin/env python3
"""Read-only execution adapter factory and catalog for SDRCC."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Type

from core import plugin_registry
from core import execution_journal
from core.execution_adapter import ExecutionAdapter, ExecutionAdapterError
from core.execution_adapters import NullAdapter, SatDumpAdapter, ServiceAdapter


_FACTORY_VERSION = "0.43.0c2"

_ADAPTERS: dict[str | None, Type[ExecutionAdapter]] = {
    None: NullAdapter,
    "service": ServiceAdapter,
    "satdump": SatDumpAdapter,
}


class PluginNotFoundError(ExecutionAdapterError):
    """Raised when adapter resolution targets an unknown plugin."""


class UnknownExecutorError(ExecutionAdapterError):
    """Raised when Registry metadata names an unsupported executor."""


def get_supported_executor_types() -> tuple[str, ...]:
    """Return operational executor metadata values in stable order."""
    return tuple(key for key in _ADAPTERS if key is not None)


def get_adapter_class(executor_type: str | None) -> Type[ExecutionAdapter]:
    """Resolve one adapter class from normalized executor metadata."""
    normalized = (
        str(executor_type).strip().lower()
        if executor_type is not None
        else None
    )
    adapter_class = _ADAPTERS.get(normalized)
    if adapter_class is None:
        raise UnknownExecutorError(
            f"Onbekend executor-type: {executor_type!r}"
        )
    return adapter_class


def get_adapter(plugin_id: str) -> ExecutionAdapter:
    """Resolve a fail-closed adapter for one registered plugin."""
    plugin = plugin_registry.get_plugin(plugin_id)
    if plugin is None:
        raise PluginNotFoundError(f"Onbekende plugin: {plugin_id!r}")

    adapter_class = get_adapter_class(plugin.get("executor"))
    return adapter_class(plugin)


def build_plan(
    plugin_id: str,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and journal one read-only execution plan.

    Journaling is observer-only: it records a defensive plan snapshot and never
    performs execution, changes receiver state or assumes lifecycle authority.
    """
    observed = build_plan_with_journal(plugin_id, request)
    return observed["plan"]


def build_plan_with_journal(
    plugin_id: str,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a plan and return its observer-only journal correlation."""
    plan = get_adapter(plugin_id).build_plan(request).as_dict()
    entry = execution_journal.create_entry(plan, request=request)
    return {
        "plan": plan,
        "execution_id": entry["execution_id"],
        "journal_entry": entry,
    }


def get_plan_catalog(*, include_planned: bool = True) -> dict[str, Any]:
    """Return read-only execution plans for all registered plugins."""
    plugins = plugin_registry.get_plugins(include_planned=include_planned)
    plans: list[dict[str, Any]] = []
    errors: list[str] = []

    for plugin in plugins:
        plugin_id = str(plugin.get("id") or "").strip().lower()
        try:
            plan = build_plan(plugin_id)
        except ExecutionAdapterError as error:
            errors.append(f"{plugin_id or '<unknown>'}: {error}")
            continue

        plans.append(plan)
        for validation_error in plan["validation_errors"]:
            errors.append(f"{plugin_id}: {validation_error}")

    return {
        "ok": not errors,
        "read_only": True,
        "planning_only": True,
        "foundation_only": True,
        "source": "execution_factory",
        "factory_version": _FACTORY_VERSION,
        "schema_version": 1,
        "plugin_count": len(plans),
        "plans": plans,
        "errors": errors,
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    }


def describe_plugin(plugin_id: str) -> dict[str, Any]:
    """Return the read-only adapter description for one plugin."""
    return get_adapter(plugin_id).describe().as_dict()


def validate_foundation(*, include_planned: bool = True) -> dict[str, Any]:
    """Validate all current Registry executor mappings."""
    plugins = plugin_registry.get_plugins(include_planned=include_planned)
    descriptions: list[dict[str, Any]] = []
    errors: list[str] = []

    for plugin in plugins:
        plugin_id = str(plugin.get("id") or "").strip().lower()
        try:
            description = get_adapter(plugin_id).describe().as_dict()
        except ExecutionAdapterError as error:
            errors.append(f"{plugin_id or '<unknown>'}: {error}")
            continue

        descriptions.append(description)
        for validation_error in description["validation_errors"]:
            errors.append(f"{plugin_id}: {validation_error}")

    return {
        "ok": not errors,
        "read_only": True,
        "foundation_only": True,
        "source": "execution_factory",
        "factory_version": _FACTORY_VERSION,
        "schema_version": 1,
        "supported_executor_types": list(get_supported_executor_types()),
        "plugin_count": len(descriptions),
        "plugins": descriptions,
        "errors": errors,
        "generated_at": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
    }


def get_catalog_snapshot(*, include_planned: bool = True) -> dict[str, Any]:
    """Return the validated, read-only execution adapter catalog."""
    return validate_foundation(include_planned=include_planned)
