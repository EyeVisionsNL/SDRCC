#!/usr/bin/env python3
"""Validate SDRCC v0.55.0a Traffic Voice Foundation."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch


ROOT = Path(
    os.environ.get("SDRCC_ROOT") or Path(__file__).resolve().parents[1]
).resolve()
EXPECTED_MODES = ("marine_ais", "airband_adsb")
FORBIDDEN_IMPORTS = {
    "subprocess",
    "core.receiver_manager",
    "core.process_manager",
    "core.rtl",
    "core.device_manager",
}
FORBIDDEN_CALLS = {
    "Popen",
    "run",
    "system",
    "reserve",
    "release",
    "begin_handover",
    "restore_handover",
    "set_assignment",
    "set_plugin_assignments",
    "save_station",
    "open_device",
}


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def validate_static_boundaries() -> dict[str, object]:
    required = [
        "config/traffic_voice.yaml",
        "core/traffic_voice.py",
        "dashboard/static/css/traffic_voice.css",
        "dashboard/static/js/traffic_voice.js",
        "docs/traffic-voice-foundation-v0550a.md",
    ]
    for relative in required:
        check((ROOT / relative).is_file(), f"required file present: {relative}")

    source_path = ROOT / "core/traffic_voice.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_IMPORTS:
                    violations.append(f"forbidden import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in FORBIDDEN_IMPORTS:
                violations.append(f"forbidden import {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            else:
                continue
            if name in FORBIDDEN_CALLS:
                violations.append(f"line {node.lineno}: forbidden call {name}")
    check(not violations, "core foundation has no receiver, process or service authority")

    app_source = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    route_marker = '@app.route("/api/traffic-voice", methods=["GET"])'
    check(route_marker in app_source, "Traffic Voice API is GET-only")
    route_tail = app_source.split(route_marker, 1)[1]
    route_block = route_tail.split("@app.route", 1)[0]
    check("request.get_json" not in route_block, "Traffic Voice API has no write payload")
    check("handle_service_action" not in route_block, "Traffic Voice API has no service action")
    check("receiver_manager" not in route_block, "Traffic Voice API has no receiver action")

    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    check('data-tab="traffic-voice"' in html, "Traffic Voice top navigation present")
    check('id="tab-traffic-voice"' in html, "Traffic Voice page shell present")
    section = html.split('id="tab-traffic-voice"', 1)[1].split(
        '<section class="tab-page"', 1
    )[0]
    check("<button" not in section, "foundation UI exposes no execution controls")
    check("possible speaker" in section.lower(), "speaker identity is explicitly probabilistic")

    javascript = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(
        encoding="utf-8"
    )
    check('"/api/traffic-voice"' in javascript, "UI consumes foundation API")
    check("POST" not in javascript and "method:" not in javascript, "UI performs no writes")

    navigation = (ROOT / "dashboard/static/css/navigation_theme.css").read_text(
        encoding="utf-8"
    )
    check("repeat(10, minmax(0, 1fr))" in navigation, "navigation accounts for ten tabs")
    return {"required_files": required, "static_violations": violations}


def validate_runtime_contract() -> dict[str, object]:
    sys.path.insert(0, str(ROOT))
    from core import config  # pylint: disable=import-outside-toplevel
    from core import execution_factory  # pylint: disable=import-outside-toplevel
    from core import plugin_health  # pylint: disable=import-outside-toplevel
    from core import plugin_manager  # pylint: disable=import-outside-toplevel
    from core import plugin_registry  # pylint: disable=import-outside-toplevel
    from core import plugin_runtime  # pylint: disable=import-outside-toplevel
    from core import receiver_registry  # pylint: disable=import-outside-toplevel
    from core import traffic_voice  # pylint: disable=import-outside-toplevel

    roles = config.get_assignment_roles()
    check(roles == (
        "weather", "ais", "adsb", "iss_voice", "traffic_voice", "meshcore"
    ), "assignment roles have stable six-plugin order")

    registry_validation = plugin_registry.validate_registry(assignment_roles=roles)
    check(registry_validation["ok"], "Plugin Registry and assignment roles agree")
    check(registry_validation["plugin_count"] == 6, "Plugin Registry contains six plugins")

    plugin = plugin_registry.get_plugin("traffic_voice")
    check(plugin is not None, "Traffic Voice plugin metadata present")
    check(plugin["status"] == "planned", "Traffic Voice remains planned")
    check(plugin["executor"] is None, "Traffic Voice has no executor")
    check(plugin["services"] == [], "Traffic Voice has no lifecycle service")
    check(plugin["handover_services"] == [], "Traffic Voice has no handover service")

    receivers = receiver_registry.get_receivers()
    check(len(receivers) == 2, "exactly two enabled receivers retained")
    check(all(
        "traffic_voice" in receiver["capabilities"] for receiver in receivers
    ), "both receivers support the flexible Traffic Voice role")
    check(
        [receiver["serial"] for receiver in receivers] == ["05419737", "24006572"],
        "receiver serial identities remain unchanged",
    )

    assignments = config.get_receiver_assignments()
    check(assignments["traffic_voice"] == "sdr2", "initial Traffic Voice assignment is SDR2")
    check(assignments["ais"] == "sdr1", "AIS assignment remains SDR1")
    check(assignments["adsb"] == "sdr2", "ADS-B assignment remains SDR2")

    raw_config = config.load_traffic_voice()
    config_validation = traffic_voice.validate_configuration(raw_config)
    check(config_validation["ok"], "Traffic Voice configuration schema valid")
    settings = raw_config["traffic_voice"]
    check(settings["selected_mode"] == "marine_ais", "initial selected mode is Marine + AIS")
    check(tuple(settings["modes"]) == EXPECTED_MODES, "exactly two modes configured in stable order")
    check(settings["execution_enabled"] is False, "configuration execution remains disabled")
    check(settings["spectrum"]["fft_enabled"] is False, "false live FFT claim is disabled")
    check(settings["speaker_context"]["certainty"] == "probabilistic", "speaker certainty is probabilistic")

    snapshot = traffic_voice.get_snapshot()
    check(snapshot["ok"], "Traffic Voice foundation snapshot valid")
    check(snapshot["read_only"] and snapshot["foundation_only"], "snapshot is read-only foundation")
    check(snapshot["execution_enabled"] is False, "snapshot cannot enable execution")
    check(snapshot["assignment"]["separated"], "selected voice and AIS context receivers are separated")
    check(snapshot["assignment"]["matches_policy"], "selected assignment matches opposite-receiver policy")
    check(
        snapshot["assignment"]["voice_receiver"]["runtime_id"] == "sdr2"
        and snapshot["assignment"]["context_receiver"]["runtime_id"] == "sdr1",
        "Marine mode projects voice SDR2 and AIS SDR1",
    )
    airband = next(mode for mode in snapshot["modes"] if mode["id"] == "airband_adsb")
    check(
        airband["derived_voice_receiver"]["runtime_id"] == "sdr1"
        and airband["context_receiver"]["runtime_id"] == "sdr2",
        "Airband mode derives voice SDR1 and ADS-B SDR2",
    )

    unsafe_config = deepcopy(raw_config)
    unsafe_config["traffic_voice"]["execution_enabled"] = True
    check(
        traffic_voice.validate_configuration(unsafe_config)["ok"] is False,
        "execution enablement fails closed",
    )
    incomplete_config = deepcopy(raw_config)
    incomplete_config["traffic_voice"]["modes"].pop("airband_adsb")
    check(
        traffic_voice.validate_configuration(incomplete_config)["ok"] is False,
        "missing mode fails closed",
    )

    conflicting = dict(assignments)
    conflicting["traffic_voice"] = "sdr1"
    with patch.object(config, "get_receiver_assignments", return_value=conflicting):
        conflict_snapshot = traffic_voice.get_snapshot()
    check(conflict_snapshot["ok"] is False, "same-receiver context conflict fails closed")
    check(
        not conflict_snapshot["assignment"]["separated"],
        "context conflict is explicit in snapshot",
    )

    adapter = execution_factory.describe_plugin("traffic_voice")
    plan = execution_factory.get_adapter("traffic_voice").build_plan({}).as_dict()
    check(adapter["adapter_type"] == "null", "Traffic Voice resolves to NullAdapter")
    check(plan["executable"] is False and plan["foundation_only"] is True, "Traffic Voice execution plan is fail-closed")
    check(plan["targets"] == [], "Traffic Voice execution plan has no target")

    runtime = plugin_runtime.get_snapshot(include_planned=True)
    runtime_item = next(
        item for item in runtime["plugins"] if item["plugin_id"] == "traffic_voice"
    )
    check(runtime_item["runtime_state"] == "PLANNED", "Plugin Runtime reports PLANNED")

    registry_snapshot = plugin_registry.get_registry_snapshot(include_planned=True)
    runtime_snapshot = plugin_runtime.get_snapshot(include_planned=True)
    health_snapshot = plugin_health.get_snapshot(include_planned=True)
    execution_snapshot = execution_factory.get_catalog_snapshot(include_planned=True)
    planning_snapshot = {
        "ok": True,
        "plans": [
            execution_factory.get_adapter(item["id"]).build_plan({}).as_dict()
            for item in registry_snapshot["plugins"]
        ],
    }
    manager_items = plugin_manager._merge_plugins(
        registry_snapshot,
        runtime_snapshot,
        health_snapshot,
        execution_snapshot,
        planning_snapshot,
    )
    manager_item = next(
        item for item in manager_items if item["plugin_id"] == "traffic_voice"
    )
    check(manager_item["control"]["enabled"] is False, "Plugin Manager control remains disabled")
    check(manager_item["control"]["actions"] == [], "Plugin Manager exposes no Traffic Voice actions")
    check(manager_item["control"]["endpoint"] is None, "Plugin Manager exposes no action endpoint")

    return {
        "version": snapshot["version"],
        "roles": list(roles),
        "selected_mode": snapshot["selected_mode"],
        "assignment": snapshot["assignment"],
        "mode_count": len(snapshot["modes"]),
        "plugin_count": registry_validation["plugin_count"],
        "adapter_type": adapter["adapter_type"],
        "execution_enabled": snapshot["execution_enabled"],
        "prohibited": snapshot["prohibited_in_v0550a"],
    }


def main() -> int:
    try:
        static = validate_static_boundaries()
        runtime = validate_runtime_contract()
    except Exception as error:  # noqa: BLE001 - standalone contract validator
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print("VALIDATION PASS: SDRCC v0.55.0a Traffic Voice Foundation")
    print(json.dumps({"static": static, "runtime": runtime}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
