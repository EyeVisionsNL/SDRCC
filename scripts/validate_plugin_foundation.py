#!/usr/bin/env python3
"""Validate the stabilized SDRCC Plugin Foundation architecture."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()

SCAN_ROOTS = ("core", "dashboard", "scripts", "tests")
DIRECT_REGISTRY_CAPABILITY_METHODS = {
    "plugin_has_capability",
    "get_plugins_with_capability",
    "get_capabilities",
    "get_capability_map",
}


def iter_python_files() -> Iterable[Path]:
    for root_name in SCAN_ROOTS:
        root = PROJECT_ROOT / root_name
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


def validate_no_direct_registry_capability_consumers() -> list[str]:
    violations: list[str] = []

    for path in iter_python_files():
        relative = path.relative_to(PROJECT_ROOT)

        # Definitions inside the Registry itself are allowed.
        if relative == Path("core/plugin_registry.py"):
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            violations.append(f"{relative}: cannot parse: {error}")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Attribute):
                continue
            owner = function.value
            if (
                isinstance(owner, ast.Name)
                and owner.id == "plugin_registry"
                and function.attr in DIRECT_REGISTRY_CAPABILITY_METHODS
            ):
                violations.append(
                    f"{relative}:{node.lineno}: "
                    f"plugin_registry.{function.attr}(...)"
                )

    return violations


def validate_runtime_contract() -> dict[str, object]:
    sys.path.insert(0, str(PROJECT_ROOT))

    from core import (  # pylint: disable=import-outside-toplevel
        plugin_capabilities,
        plugin_health,
        plugin_manager,
        plugin_registry,
        plugin_runtime,
        receiver_runtime,
        rf_diagnostics,
    )

    snapshot = plugin_capabilities.get_snapshot()
    if not isinstance(snapshot, dict):
        raise TypeError("Plugin Capability snapshot is not a dictionary")

    weather = plugin_registry.get_plugin("weather")
    if not weather:
        raise RuntimeError("Weather plugin metadata is unavailable")

    if not plugin_capabilities.has_capability("weather", "rf_diagnostics"):
        raise RuntimeError("Weather plugin lacks expected rf_diagnostics capability")

    if rf_diagnostics._SCAN_PLUGIN_ID != "weather":
        raise RuntimeError("RF Diagnostics plugin identity changed unexpectedly")

    modules = {
        "plugin_registry": plugin_registry.__name__,
        "plugin_capabilities": plugin_capabilities.__name__,
        "plugin_runtime": plugin_runtime.__name__,
        "plugin_health": plugin_health.__name__,
        "plugin_manager": plugin_manager.__name__,
        "receiver_runtime": receiver_runtime.__name__,
        "rf_diagnostics": rf_diagnostics.__name__,
    }

    return {
        "status": "ok",
        "modules": modules,
        "capability_snapshot": snapshot,
    }


def main() -> int:
    violations = validate_no_direct_registry_capability_consumers()
    if violations:
        print("FAIL: direct Registry capability consumers found:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print("PASS: no direct Registry capability consumers")

    try:
        contract = validate_runtime_contract()
    except Exception as error:  # noqa: BLE001 - diagnostic script
        print(
            f"FAIL: Plugin Foundation contract validation failed: "
            f"{type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Plugin Foundation module contract")
    print("PASS: Plugin Capability Layer query contract")
    print(json.dumps(contract, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
