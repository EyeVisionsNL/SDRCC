#!/usr/bin/env python3
"""Validate SDRCC Execution Plan Consumers and compatible delegation evolution.

This validator protects architecture and public contracts without pinning the
dashboard integration to one concrete helper function name.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path


ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()


def _called_attributes(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def static_validation() -> list[str]:
    errors: list[str] = []
    consumer_path = ROOT / "core/execution_plan_consumer.py"
    mission_path = ROOT / "core/mission_engine.py"
    app_path = ROOT / "dashboard/app.py"

    consumer_text = consumer_path.read_text(encoding="utf-8")
    mission_text = mission_path.read_text(encoding="utf-8")
    app_text = app_path.read_text(encoding="utf-8")

    consumer_tree = ast.parse(consumer_text, filename=str(consumer_path))
    mission_tree = ast.parse(mission_text, filename=str(mission_path))
    app_tree = ast.parse(app_text, filename=str(app_path))

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

    for node in ast.walk(consumer_tree):
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

    mission_calls = _called_attributes(mission_tree)
    app_calls = _called_attributes(app_tree)

    if "consume_weather_mission" not in mission_calls:
        errors.append("Mission Engine consumeert weather-plan niet")

    compatible_service_calls = {
        "consume_service_action",
        "delegate_service_action",
    }
    if not (app_calls & compatible_service_calls):
        errors.append(
            "Dashboard service-acties consumeren of delegeren service-plan niet"
        )

    if "delegate_service_action" in app_calls:
        service_actions = None
        for node in app_tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name)
                and target.id == "SERVICE_ACTIONS"
                for target in node.targets
            ):
                continue
            try:
                service_actions = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                errors.append("SERVICE_ACTIONS is niet statisch valideerbaar")
            break

        if not isinstance(service_actions, dict):
            errors.append("SERVICE_ACTIONS ontbreekt of is ongeldig")
        else:
            for action_id, action in service_actions.items():
                if not isinstance(action, dict):
                    errors.append(
                        f"SERVICE_ACTIONS[{action_id!r}] is geen mapping"
                    )
                    continue
                if not action.get("plugin_id"):
                    errors.append(
                        f"SERVICE_ACTIONS[{action_id!r}] mist plugin_id"
                    )
                if "service" in action:
                    errors.append(
                        f"SERVICE_ACTIONS[{action_id!r}] bevat hardcoded service"
                    )

        if "SERVICE_PLUGIN_BY_NAME" in app_text:
            errors.append(
                "Dashboard bevat verouderde SERVICE_PLUGIN_BY_NAME mapping"
            )

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

    service_mode: str
    mismatch_detected: bool

    if hasattr(execution_plan_consumer, "delegate_service_action"):
        service_mode = "delegation"

        ais = execution_plan_consumer.delegate_service_action("ais", "start")
        assert ais["ok"] is True
        assert ais["delegated_target"] == "ais-catcher.service"
        assert ais["delegated_action"] == "start"
        assert ais["delegation_scope"] == "service_target_only"
        assert ais["operation_authority"] == (
            "existing_dashboard_systemctl_path"
        )
        assert ais["plan"]["targets"] == ["ais-catcher.service"]

        adsb = execution_plan_consumer.delegate_service_action("adsb", "restart")
        assert adsb["ok"] is True
        assert adsb["delegated_target"] == "readsb.service"
        assert adsb["delegated_action"] == "restart"
        assert adsb["plan"]["targets"] == ["readsb.service"]

        invalid_action = execution_plan_consumer.delegate_service_action(
            "ais",
            "enable",
        )
        assert invalid_action["ok"] is False
        assert invalid_action["delegated_target"] == "ais-catcher.service"

        mismatch_detected = True
        if hasattr(execution_plan_consumer, "consume_service_action"):
            mismatch = execution_plan_consumer.consume_service_action(
                "ais",
                "readsb.service",
                "start",
            )
            assert mismatch["ok"] is False
            assert mismatch["target_matches"] is False
            mismatch_detected = mismatch["target_matches"] is False
    else:
        service_mode = "validation"

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
        mismatch_detected = mismatch["target_matches"] is False

    snapshot = execution_plan_consumer.get_snapshot()
    assert snapshot["read_only"] is True
    assert snapshot["behavior_changed"] is False

    if service_mode == "validation":
        assert snapshot["consumer_version"] == "0.43.0a"
        assert snapshot["validation_only"] is True
        assert snapshot["authority"] == "observer_only"
        assert snapshot["history_count"] == 4
    else:
        assert snapshot["consumer_version"] >= "0.43.0b"
        assert snapshot["delegation_active"] is True
        assert snapshot["delegation_scope"] == "service_target_only"
        assert snapshot["operation_authority"] == (
            "existing_dashboard_systemctl_path"
        )
        assert snapshot["history_count"] >= 3

    return {
        "status": "ok",
        "consumer_version": snapshot["consumer_version"],
        "service_mode": service_mode,
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
        "mismatch_detected": mismatch_detected,
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
    print("PASS: Mission Engine consumeert weather-plan")
    print("PASS: Dashboard accepteert validation- of delegation-integratie")

    try:
        result = runtime_validation()
    except Exception as error:
        print(
            f"FAIL: consumercontract: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1

    print("PASS: Weather-, AIS- en ADS-B-plancontract geldig")
    print("PASS: Compatibilitypad is functienaam-onafhankelijk")
    print("PASS: Bestaand operationeel gedrag blijft ongewijzigd")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
