#!/usr/bin/env python3
"""Validate SDRCC v0.42.0a Execution Adapter Foundation."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(
    os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")
).resolve()

ADAPTER_FILES = {
    Path("core/execution_adapter.py"),
    Path("core/execution_factory.py"),
    Path("core/execution_adapters/__init__.py"),
    Path("core/execution_adapters/service_adapter.py"),
    Path("core/execution_adapters/satdump_adapter.py"),
    Path("core/execution_adapters/null_adapter.py"),
}

FORBIDDEN_IMPORTS = {
    "subprocess",
    "signal",
    "core.rtl",
    "core.receiver_runtime",
    "core.plugin_runtime",
    "core.plugin_health",
}

FORBIDDEN_CALL_NAMES = {
    "Popen",
    "run",
    "check_call",
    "check_output",
    "system",
    "kill",
    "terminate",
    "send_signal",
    "reserve",
    "release",
    "activate",
    "deactivate",
    "mission_create_job",
    "mission_set_state",
    "mission_finish_job",
    "mission_cancel",
}


def iter_adapter_paths() -> Iterable[Path]:
    for relative in sorted(ADAPTER_FILES):
        yield PROJECT_ROOT / relative


def validate_static_boundaries() -> list[str]:
    violations: list[str] = []

    for path in iter_adapter_paths():
        relative = path.relative_to(PROJECT_ROOT)
        if not path.exists():
            violations.append(f"{relative}: bestand ontbreekt")
            continue

        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError) as error:
            violations.append(f"{relative}: parsefout: {error}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_IMPORTS:
                        violations.append(
                            f"{relative}:{node.lineno}: verboden import "
                            f"{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in FORBIDDEN_IMPORTS:
                    violations.append(
                        f"{relative}:{node.lineno}: verboden import "
                        f"{node.module}"
                    )
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                else:
                    continue
                if name in FORBIDDEN_CALL_NAMES:
                    violations.append(
                        f"{relative}:{node.lineno}: verboden lifecycle-call "
                        f"{name}(...)"
                    )

    return violations


def validate_runtime_contract() -> dict[str, object]:
    sys.path.insert(0, str(PROJECT_ROOT))

    from core import execution_factory  # pylint: disable=import-outside-toplevel
    from core.execution_adapter import (  # pylint: disable=import-outside-toplevel
        ExecutionNotEnabledError,
    )

    snapshot = execution_factory.get_catalog_snapshot(include_planned=True)
    if not snapshot.get("ok"):
        raise RuntimeError(
            "Adaptercatalogus ongeldig: "
            + "; ".join(snapshot.get("errors") or [])
        )

    expected = {
        "weather": "satdump",
        "ais": "service",
        "adsb": "service",
        "iss_voice": "null",
        "meshcore": "null",
    }
    actual = {
        item["plugin_id"]: item["adapter_type"]
        for item in snapshot["plugins"]
    }
    if actual != expected:
        raise RuntimeError(
            f"Onverwachte adaptermapping: expected={expected}, actual={actual}"
        )

    for plugin_id in expected:
        adapter = execution_factory.get_adapter(plugin_id)
        if adapter.can_execute():
            raise RuntimeError(f"{plugin_id}: foundation mag niet executable zijn")
        try:
            adapter.execute({})
        except ExecutionNotEnabledError:
            pass
        else:
            raise RuntimeError(
                f"{plugin_id}: execute() faalde niet fail-closed"
            )

    return snapshot


def main() -> int:
    violations = validate_static_boundaries()
    if violations:
        print("FAIL: architectuurgrenzen geschonden:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1

    print("PASS: adapters bevatten geen lifecycle- of procesbesturing")

    try:
        snapshot = validate_runtime_contract()
    except Exception as error:  # noqa: BLE001 - diagnostic validator
        print(
            f"FAIL: runtimecontract: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Registry-to-adapter mapping")
    print("PASS: alle adapters zijn fail-closed")
    print("PASS: Service/SatDump/Null metadata-contracten")
    print(json.dumps(snapshot, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
