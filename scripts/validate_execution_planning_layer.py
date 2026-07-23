#!/usr/bin/env python3
"""Validate SDRCC v0.42.0c Execution Planning Layer."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path


ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()

EXPECTED = {
    "weather": {
        "adapter_type": "satdump",
        "launch_type": "mission",
        "target_type": "satdump_pipeline",
    },
    "ais": {
        "adapter_type": "service",
        "launch_type": "persistent_service",
        "target_type": "systemd_service",
    },
    "adsb": {
        "adapter_type": "service",
        "launch_type": "persistent_service",
        "target_type": "systemd_service",
    },
    "iss_voice": {
        "adapter_type": "null",
        "launch_type": "none",
        "target_type": "none",
    },
    "meshcore": {
        "adapter_type": "null",
        "launch_type": "none",
        "target_type": "none",
    },
}


def static_validation() -> list[str]:
    errors: list[str] = []
    files = [
        ROOT / "core/execution_plan.py",
        ROOT / "core/execution_adapter.py",
        ROOT / "core/execution_factory.py",
        ROOT / "core/execution_adapters/service_adapter.py",
        ROOT / "core/execution_adapters/satdump_adapter.py",
        ROOT / "core/execution_adapters/null_adapter.py",
        ROOT / "core/plugin_manager.py",
    ]
    forbidden_imports = {
        "subprocess",
        "os.system",
        "core.receiver_manager",
        "core.mission_engine",
        "core.process_manager",
        "core.satdump",
    }
    forbidden_calls = {
        "Popen",
        "run",
        "system",
        "start",
        "stop",
        "restart",
        "reserve",
        "release",
        "prepare",
        "execute",
        "cancel",
        "cleanup",
    }

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_imports:
                        errors.append(f"{path.name}: verboden import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module in forbidden_imports:
                    errors.append(f"{path.name}: verboden import {node.module}")
            elif isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in forbidden_calls and path.name != "execution_adapter.py":
                    errors.append(f"{path.name}:{node.lineno}: verboden call {name}")

    return errors


def runtime_validation() -> dict:
    sys.path.insert(0, str(ROOT))
    from core import execution_factory, plugin_manager
    from core.execution_adapter import ExecutionNotEnabledError

    catalog = execution_factory.get_plan_catalog(include_planned=True)
    assert catalog["ok"] is True
    assert catalog["read_only"] is True
    assert catalog["planning_only"] is True
    assert catalog["foundation_only"] is True
    assert catalog["plugin_count"] == 5

    actual = {}
    for plan in catalog["plans"]:
        plugin_id = plan["plugin_id"]
        actual[plugin_id] = {
            "adapter_type": plan["adapter_type"],
            "launch_type": plan["launch_type"],
            "target_type": plan["target_type"],
        }
        assert plan["executable"] is False
        assert plan["read_only"] is True
        assert plan["foundation_only"] is True
        assert plan["metadata_valid"] is True
        assert plan["validation_errors"] == []

    assert actual == EXPECTED

    weather = execution_factory.build_plan(
        "weather",
        {"target": "METEOR-M2-4", "receiver_role": "weather"},
    )
    assert weather["targets"] == ["METEOR-M2-4"]
    assert weather["receiver_role"] == "weather"
    assert "receiver_locked" in weather["requirements"]

    ais = execution_factory.build_plan("ais")
    assert ais["targets"] == ["ais-catcher.service"]

    adsb = execution_factory.build_plan("adsb")
    assert adsb["targets"] == ["readsb.service"]

    null_plan = execution_factory.build_plan("iss_voice")
    assert null_plan["targets"] == []
    assert null_plan["requirements"] == ["execution_backend_required"]

    for plugin_id in EXPECTED:
        adapter = execution_factory.get_adapter(plugin_id)
        for method_name in ("prepare", "execute", "cancel", "cleanup"):
            method = getattr(adapter, method_name)
            try:
                method()
            except ExecutionNotEnabledError:
                pass
            else:
                raise AssertionError(
                    f"{plugin_id}.{method_name} fail-closed contract gebroken"
                )

    manager = plugin_manager.get_snapshot(include_planned=True)
    assert manager["ok"] is True
    assert manager["manager_version"] == "0.42.0c"
    assert manager["source_status"]["planning"] is True
    assert manager["summary"]["execution_plans_valid"] is True
    assert manager["summary"]["execution_planning_only"] is True
    assert manager["planning_source"] == "execution_factory"
    assert manager["planning_authority"] == "description_only"
    assert manager["planning"]["plans"] == catalog["plans"] or (
        {
            p["plugin_id"]: p
            for p in manager["planning"]["plans"]
        }
        ==
        {
            p["plugin_id"]: p
            for p in catalog["plans"]
        }
    )
    assert all(item["execution_plan"] for item in manager["plugins"])

    return {
        "status": "ok",
        "factory_version": catalog["factory_version"],
        "manager_version": manager["manager_version"],
        "plan_count": catalog["plugin_count"],
        "plans": actual,
        "weather_target_test": weather["targets"],
        "service_targets": {
            "ais": ais["targets"],
            "adsb": adsb["targets"],
        },
        "source_status": manager["source_status"],
        "summary": manager["summary"],
    }


def main() -> int:
    errors = static_validation()
    if errors:
        print("FAIL: statische planninggrenzen geschonden", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("PASS: Planning Layer bevat geen execution-call-sites")
    print("PASS: authority imports blijven afwezig")

    try:
        result = runtime_validation()
    except Exception as error:
        print(
            f"FAIL: planningcontract: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Service-, SatDump- en Null-plannen consistent")
    print("PASS: planning blijft read-only en non-executable")
    print("PASS: bestaande adaptermethoden blijven fail-closed")
    print("PASS: Plugin Manager planning-integratie geldig")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
