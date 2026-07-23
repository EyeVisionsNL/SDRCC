#!/usr/bin/env python3
"""Validate SDRCC v0.43.0a Execution Plan Consumers."""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path


ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()


def static_validation() -> list[str]:
    errors: list[str] = []
    consumer_path = ROOT / "core/execution_plan_consumer.py"
    tree = ast.parse(
        consumer_path.read_text(encoding="utf-8"),
        filename=str(consumer_path),
    )

    forbidden_imports = {
        "subprocess",
        "core.receiver_manager",
        "core.receiver_runtime",
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
        "lock",
        "unlock",
        "execute",
        "prepare",
        "cancel",
        "cleanup",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in forbidden_imports:
                    errors.append(f"verboden import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in forbidden_imports:
                errors.append(f"verboden import {node.module}")
        elif isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in forbidden_calls:
                errors.append(f"regel {node.lineno}: verboden call {name}")

    mission_text = (ROOT / "core/mission_engine.py").read_text(encoding="utf-8")
    app_text = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")

    if "consume_weather_mission" not in mission_text:
        errors.append("Mission Engine consumeert weather-plan niet")
    if "consume_service_action" not in app_text:
        errors.append("Dashboard service-acties consumeren service-plan niet")
    if "/api/execution-plan-consumers" not in app_text:
        errors.append("Consumer API ontbreekt")

    return errors


def runtime_validation() -> dict:
    sys.path.insert(0, str(ROOT))

    from core import execution_plan_consumer

    execution_plan_consumer.reset_history()

    mission = execution_plan_consumer.consume_weather_mission({
        "target": "METEOR-M2-4",
        "satellite": "METEOR-M2-4",
        "receiver_role": "weather",
        "receiver": "sdr1",
        "pipeline": "meteor_m2_lrpt",
    })
    assert mission["ok"] is True
    assert mission["read_only"] is True
    assert mission["validation_only"] is True
    assert mission["behavior_changed"] is False
    assert mission["plan"]["plugin_id"] == "weather"
    assert mission["plan"]["launch_type"] == "mission"
    assert mission["plan"]["targets"] == ["METEOR-M2-4"]

    ais = execution_plan_consumer.consume_service_action(
        "ais",
        "ais-catcher.service",
        "start",
    )
    assert ais["ok"] is True
    assert ais["target_matches"] is True
    assert ais["plan"]["targets"] == ["ais-catcher.service"]

    adsb = execution_plan_consumer.consume_service_action(
        "adsb",
        "readsb.service",
        "restart",
    )
    assert adsb["ok"] is True
    assert adsb["target_matches"] is True
    assert adsb["plan"]["targets"] == ["readsb.service"]

    mismatch = execution_plan_consumer.consume_service_action(
        "ais",
        "readsb.service",
        "start",
    )
    assert mismatch["ok"] is False
    assert mismatch["target_matches"] is False

    snapshot = execution_plan_consumer.get_snapshot()
    assert snapshot["consumer_version"] == "0.43.0a"
    assert snapshot["read_only"] is True
    assert snapshot["validation_only"] is True
    assert snapshot["behavior_changed"] is False
    assert snapshot["authority"] == "observer_only"
    assert snapshot["history_count"] == 4

    return {
        "status": "ok",
        "consumer_version": snapshot["consumer_version"],
        "history_count": snapshot["history_count"],
        "mission_plan": {
            "plugin_id": mission["plan"]["plugin_id"],
            "launch_type": mission["plan"]["launch_type"],
            "target_type": mission["plan"]["target_type"],
            "targets": mission["plan"]["targets"],
        },
        "service_plans": {
            "ais": ais["plan"]["targets"],
            "adsb": adsb["plan"]["targets"],
        },
        "mismatch_detected": mismatch["target_matches"] is False,
        "authority": snapshot["authority"],
        "behavior_changed": snapshot["behavior_changed"],
    }


def main() -> int:
    errors = static_validation()
    if errors:
        print("FAIL: consumer boundaries", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("PASS: Consumers bevatten geen operationele execution-call-sites")
    print("PASS: Consumers importeren geen lifecycle-authoriteiten")
    print("PASS: Mission Engine en service-acties consumeren plannen")

    try:
        result = runtime_validation()
    except Exception as error:
        print(
            f"FAIL: consumercontract: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Weather-, AIS- en ADS-B-planconsumptie geldig")
    print("PASS: Target mismatch wordt alleen gedetecteerd")
    print("PASS: Bestaand operationeel gedrag blijft ongewijzigd")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
