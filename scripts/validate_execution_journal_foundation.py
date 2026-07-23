#!/usr/bin/env python3
"""Validate SDRCC v0.43.0c1 Execution Journal Foundation."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()


def static_validation() -> list[str]:
    errors: list[str] = []
    path = ROOT / "core/execution_journal.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden_imports = {
        "subprocess", "core.receiver_manager", "core.mission_engine",
        "core.process_manager", "core.satdump",
    }
    forbidden_calls = {
        "Popen", "run", "system", "start", "stop", "restart", "reserve",
        "release", "prepare", "execute", "cancel", "cleanup",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_imports:
                    errors.append(f"verboden import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module in forbidden_imports:
            errors.append(f"verboden import {node.module}")
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else None
            )
            if name in forbidden_calls:
                errors.append(f"regel {node.lineno}: verboden call {name}")
    return errors


def runtime_validation() -> dict:
    sys.path.insert(0, str(ROOT))
    from core import execution_factory, execution_journal

    execution_journal.reset_journal()
    empty = execution_journal.get_snapshot()
    assert empty["ok"] is True
    assert empty["count"] == 0
    assert empty["authority"] == "observer_only"
    assert empty["persistence"] == "memory_only"

    plan = execution_factory.build_plan(
        "weather",
        {"target": "METEOR-M2-4", "receiver_role": "weather"},
    )
    assert plan["plugin_id"] == "weather"
    snapshot = execution_journal.get_snapshot()
    assert snapshot["count"] == 1
    latest = snapshot["latest"]
    assert latest["status"] == "PLAN_CREATED"
    assert latest["plugin_id"] == "weather"
    assert latest["read_only"] is True
    assert latest["behavior_changed"] is False
    assert latest["plan"] == plan
    assert latest["execution_id"]
    assert execution_journal.get_entry(latest["execution_id"]) == latest

    second = execution_factory.build_plan("ais")
    assert second["plugin_id"] == "ais"
    assert execution_journal.get_snapshot()["count"] == 2
    assert execution_journal.get_snapshot(plugin_id="weather")["count"] == 1
    assert execution_journal.get_snapshot(status="PLAN_CREATED")["count"] == 2
    assert execution_journal.get_snapshot(limit=1)["count"] == 1

    ids = [item["execution_id"] for item in execution_journal.get_snapshot()["entries"]]
    assert len(ids) == len(set(ids))

    return {
        "status": "ok",
        "journal_version": snapshot["journal_version"],
        "factory_version": execution_factory.get_plan_catalog()["factory_version"],
        "entry_count": execution_journal.get_snapshot()["count"],
        "unique_execution_ids": True,
        "observer_only": True,
    }


def main() -> int:
    errors = static_validation()
    if errors:
        print("FAIL: journalgrenzen geschonden", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("PASS: Execution Journal bevat geen operationele call-sites")
    try:
        result = runtime_validation()
    except Exception as error:
        print(f"FAIL: journalcontract: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("PASS: lege journal snapshot geldig")
    print("PASS: ExecutionFactory registreert PLAN_CREATED")
    print("PASS: execution_id uniek en opvraagbaar")
    print("PASS: filters en limiet geldig")
    print("PASS: observer-only contract intact")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
