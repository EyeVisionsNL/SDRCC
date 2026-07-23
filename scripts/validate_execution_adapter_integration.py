#!/usr/bin/env python3
"""Validate SDRCC Execution Adapter discovery integration."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(
    os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")
).resolve()

EXPECTED_ADAPTERS = {
    "weather": "satdump",
    "ais": "service",
    "adsb": "service",
    "iss_voice": "null",
    "meshcore": "null",
}


def validate_static_boundaries() -> list[str]:
    """Verify the integration remains read-only and localized."""
    violations: list[str] = []
    path = PROJECT_ROOT / "core/plugin_manager.py"

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    forbidden_imports = {
        "subprocess",
        "core.receiver_manager",
        "core.mission_engine",
        "core.process_manager",
        "core.satdump",
        "core.rtl",
    }
    forbidden_calls = {
        "reserve",
        "release",
        "activate",
        "deactivate",
        "execute",
        "prepare",
        "cancel",
        "cleanup",
        "Popen",
        "system",
        "run",
    }

    imports: set[str] = set()
    imported_names: set[str] = set()
    calls: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
            imported_names.update(
                alias.asname or alias.name.rsplit(".", 1)[-1]
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
            imported_names.update(
                alias.asname or alias.name
                for alias in node.names
            )
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.append((node.lineno, node.func.id))
            elif isinstance(node.func, ast.Attribute):
                calls.append((node.lineno, node.func.attr))

    for imported in sorted(imports.intersection(forbidden_imports)):
        violations.append(f"core/plugin_manager.py: verboden import {imported}")

    for lineno, call_name in calls:
        if call_name in forbidden_calls:
            violations.append(
                f"core/plugin_manager.py:{lineno}: verboden call {call_name}(...)"
            )

    if (
        "core.execution_factory" not in imports
        and not (
            "core" in imports
            and "execution_factory" in imported_names
        )
    ):
        violations.append(
            "core/plugin_manager.py importeert execution_factory niet"
        )

    return violations


def validate_runtime_contract() -> dict[str, Any]:
    """Validate discovery consistency across Factory and Plugin Manager."""
    sys.path.insert(0, str(PROJECT_ROOT))

    from core import execution_factory  # pylint: disable=import-outside-toplevel
    from core import plugin_manager  # pylint: disable=import-outside-toplevel

    factory = execution_factory.get_catalog_snapshot(include_planned=True)
    manager = plugin_manager.get_snapshot(include_planned=True)

    if not factory.get("ok"):
        raise RuntimeError(f"Execution Factory ongeldig: {factory.get('errors')}")
    if not manager.get("ok"):
        raise RuntimeError(
            f"Plugin Manager-bronnen ongeldig: {manager.get('source_status')}"
        )

    if manager.get("manager_version") not in {"0.42.0b", "0.42.0c"}:
        raise RuntimeError(
            f"Onverwachte manager_version: {manager.get('manager_version')!r}"
        )

    if manager.get("execution_source") != "execution_factory":
        raise RuntimeError("Plugin Manager execution_source ontbreekt")

    source_status = manager.get("source_status")
    if not isinstance(source_status, dict) or source_status.get("execution") is not True:
        raise RuntimeError("Execution source_status is niet geldig")

    summary = manager.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("Plugin Manager summary ontbreekt")
    if summary.get("execution_adapters_valid") is not True:
        raise RuntimeError("Execution adapter validity ontbreekt in summary")
    if summary.get("execution_foundation_only") is not True:
        raise RuntimeError("Foundation-only bescherming ontbreekt in summary")

    embedded = manager.get("execution")
    if embedded != factory:
        # generated_at is deterministic within the factory call only, so compare
        # semantic fields rather than requiring identical timestamps.
        semantic_keys = {
            "ok",
            "read_only",
            "foundation_only",
            "source",
            "factory_version",
            "schema_version",
            "supported_executor_types",
            "plugin_count",
            "plugins",
            "errors",
        }
        for key in semantic_keys:
            if embedded.get(key) != factory.get(key):
                raise RuntimeError(
                    f"Embedded execution snapshot wijkt af bij veld {key!r}"
                )

    manager_plugins = manager.get("plugins")
    if not isinstance(manager_plugins, list):
        raise RuntimeError("Plugin Manager pluginlijst ontbreekt")

    actual: dict[str, str] = {}
    for item in manager_plugins:
        if not isinstance(item, dict):
            raise RuntimeError("Ongeldig Plugin Manager-pluginrecord")
        plugin_id = item.get("plugin_id")
        execution = item.get("execution")
        if not isinstance(execution, dict):
            raise RuntimeError(f"{plugin_id}: execution discovery ontbreekt")
        actual[str(plugin_id)] = str(execution.get("adapter_type"))

        if execution.get("executable") is not False:
            raise RuntimeError(f"{plugin_id}: adapter is onverwacht executable")
        if execution.get("foundation_only") is not True:
            raise RuntimeError(f"{plugin_id}: foundation_only ontbreekt")
        if execution.get("metadata_valid") is not True:
            raise RuntimeError(f"{plugin_id}: metadata ongeldig")
        if execution.get("validation_errors") != []:
            raise RuntimeError(f"{plugin_id}: onverwachte validatiefouten")

    if actual != EXPECTED_ADAPTERS:
        raise RuntimeError(
            f"Onverwachte adaptermapping: expected={EXPECTED_ADAPTERS}, "
            f"actual={actual}"
        )

    active_only = plugin_manager.get_snapshot(include_planned=False)
    active_ids = [
        item.get("plugin_id")
        for item in active_only.get("plugins", [])
    ]
    if active_ids != ["weather", "ais", "adsb"]:
        raise RuntimeError(
            f"include_planned=False levert onverwachte plugins: {active_ids}"
        )

    return {
        "status": "ok",
        "manager_version": manager.get("manager_version"),
        "source_status": source_status,
        "summary": summary,
        "adapter_mapping": actual,
        "active_only_plugins": active_ids,
        "plugin_count": len(manager_plugins),
    }


def main() -> int:
    violations = validate_static_boundaries()
    if violations:
        print("FAIL: integratiegrenzen geschonden:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print("PASS: Plugin Manager-integratie blijft read-only")
    print("PASS: geen receiver/mission/process authority imports")

    try:
        result = validate_runtime_contract()
    except Exception as error:  # noqa: BLE001 - diagnostic validator
        print(
            f"FAIL: discovery integration: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Execution Factory snapshot geïntegreerd")
    print("PASS: adapter discovery per plugin consistent")
    print("PASS: include_planned contract behouden")
    print("PASS: alle adapters blijven foundation-only en non-executable")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
