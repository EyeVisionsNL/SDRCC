#!/usr/bin/env python3
"""Deterministic lifecycle checks for SDRCC v0.54.0q."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def service(name: str, *, active: bool, enabled: str = "disabled", age: float = 60.0) -> dict:
    return {
        "service": name,
        "active": active,
        "state": "active" if active else "inactive",
        "enabled": enabled,
        "main_pid": 100 if active else 0,
        "active_age_seconds": age if active else None,
        "started_epoch": time.time() - age if active else None,
    }


def app_lifecycle_namespace() -> dict:
    """Load pure dashboard lifecycle helpers without importing Flask runtime."""
    from core import plugin_registry

    source = read("dashboard/app.py")
    tree = ast.parse(source, filename="dashboard/app.py")
    selected = []
    names = {
        "_service_group_names",
        "_primary_service_state",
        "_derive_service_lifecycle",
        "_service_action_steps",
        "get_ais_control_snapshot",
    }
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name in targets for name in (
                "SERVICE_STARTING_GRACE_SECONDS",
                "AIS_CONTROL_SERVICE",
            )):
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
    namespace = {
        "plugin_registry": plugin_registry,
        "service_state": lambda name: service(name, active=False),
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "dashboard/app.py", "exec"), namespace)
    check(names.issubset(namespace), "dashboard lifecycle helpers are loadable as pure functions")
    return namespace


def validate_registry_and_runtime() -> None:
    from core import plugin_registry, receiver_runtime

    check(
        plugin_registry.get_plugin_lifecycle_services("ais") == [
            "ais-catcher.service",
        ],
        "normal AIS lifecycle contains only AIS-Catcher",
    )
    check(
        plugin_registry.get_plugin_handover_services("ais") == [
            "ais-catcher-control.service",
            "ais-catcher.service",
        ],
        "Receiver Manager handover still releases Control before AIS-Catcher",
    )
    check(
        plugin_registry.get_plugin_services("ais") == ["ais-catcher.service"],
        "Execution Plan keeps one primary AIS target",
    )

    observations = receiver_runtime._service_observations(
        "receiver01",
        {"ais": "receiver01"},
        lambda name: service(name, active=name.endswith("control.service")),
    )
    check(
        [item["service"] for item in observations] == [
            "ais-catcher-control.service",
            "ais-catcher.service",
        ],
        "Receiver Runtime observes both AIS lifecycle members",
    )


def validate_inventory_availability() -> None:
    from core import plugin_runtime, receiver_inventory, receiver_registry, receiver_runtime

    originals = (
        receiver_registry.public_snapshot,
        receiver_runtime.get_snapshot,
        plugin_runtime.get_snapshot,
    )
    try:
        receiver_registry.public_snapshot = lambda: {
            "receivers": [{
                "number": "SDR1",
                "canonical_id": "receiver01",
                "runtime_id": "sdr1",
                "name": "SDR1",
                "driver": "rtlsdr",
                "serial": "05419737",
                "capabilities": ["ais"],
            }]
        }
        receiver_runtime.get_snapshot = lambda: {
            "receivers": {
                "receiver01": {
                    "configured_roles": ["ais"],
                    "reserved": False,
                    "runtime_state": "SERVICE_ACTIVE",
                    "observed_services": [
                        service("ais-catcher-control.service", active=True),
                        service("ais-catcher.service", active=False),
                    ],
                }
            }
        }
        plugin_runtime.get_snapshot = lambda include_planned=True: {"plugins": []}
        item = receiver_inventory.get_snapshot()["receivers"][0]
        check(item["available"] is False, "active AIS companion keeps receiver unavailable")
        check(
            item["active_services"] == ["ais-catcher-control.service"],
            "Receiver Inventory identifies the active AIS companion",
        )
    finally:
        (
            receiver_registry.public_snapshot,
            receiver_runtime.get_snapshot,
            plugin_runtime.get_snapshot,
        ) = originals


def validate_readsb_readiness() -> None:
    from core import receiver_monitor

    original_aircraft = receiver_monitor.READSB_AIRCRAFT_FILES
    original_stats = receiver_monitor.READSB_STATS_FILES
    try:
        with tempfile.TemporaryDirectory(prefix="sdrcc-v0540q-readsb-") as directory:
            root = Path(directory)
            aircraft = root / "aircraft.json"
            statistics = root / "stats.json"
            aircraft.write_text(json.dumps({"aircraft": [], "messages": 0}), encoding="utf-8")
            statistics.write_text(json.dumps({
                "last1min": {"start": 100.0, "end": 160.0, "messages": 0}
            }), encoding="utf-8")
            receiver_monitor.READSB_AIRCRAFT_FILES = (aircraft,)
            receiver_monitor.READSB_STATS_FILES = (statistics,)

            now = time.time()
            os.utime(aircraft, (now, now))
            os.utime(statistics, (now, now))
            ready = receiver_monitor.get_adsb_metrics(
                True,
                service_started_epoch=now - 2,
            )
            check(ready["runtime_ready"] is True, "current readsb files confirm runtime readiness")
            check(
                ready["targets"] == 0 and ready["messages_per_second"] == 0.0,
                "zero aircraft and zero messages do not fail ADS-B readiness",
            )

            old = now - 90
            os.utime(aircraft, (old, old))
            stale = receiver_monitor.get_adsb_metrics(True, service_started_epoch=now - 2)
            check(stale["runtime_ready"] is False, "stale readsb runtime file is rejected")

            os.utime(aircraft, (now, now))
            os.utime(statistics, (now, now))
            previous_runtime = receiver_monitor.get_adsb_metrics(
                True,
                service_started_epoch=now + 5,
            )
            check(
                previous_runtime["runtime_ready"] is False,
                "files from a previous readsb process do not confirm a new start",
            )
    finally:
        receiver_monitor.READSB_AIRCRAFT_FILES = original_aircraft
        receiver_monitor.READSB_STATS_FILES = original_stats


def validate_lifecycle_projection() -> None:
    lifecycle = app_lifecycle_namespace()
    derive = lifecycle["_derive_service_lifecycle"]
    primary_state = lifecycle["_primary_service_state"](
        "adsb",
        {"readsb.service": service("readsb.service", active=True)},
    )
    check(
        primary_state.get("pid") == primary_state.get("main_pid") == 100,
        "System MainPID is passed to Receiver Authority as pid",
    )

    ais_stopped = {
        "ais-catcher.service": service("ais-catcher.service", active=False),
    }
    stopped = derive("ais", ais_stopped, {}, {})
    check(stopped["lifecycle_state"] == "STOPPED", "AIS lifecycle follows AIS-Catcher only")

    running_states = {
        name: service(name, active=True)
        for name in ais_stopped
    }
    running = derive(
        "ais", running_states, {"runtime_verified": True}, {}
    )
    check(running["lifecycle_state"] == "RUNNING", "verified AIS-Catcher is RUNNING")

    enabled_states = deepcopy(running_states)
    enabled_states["ais-catcher.service"]["enabled"] = "enabled"
    enabled = derive(
        "ais", enabled_states, {"runtime_verified": True}, {}
    )
    check(enabled["lifecycle_state"] == "ATTENTION", "AIS autostart drift is ATTENTION")

    control_snapshot = lifecycle["get_ais_control_snapshot"](
        observed=service("ais-catcher-control.service", active=True)
    )
    check(
        control_snapshot["lifecycle_state"] == "RUNNING"
        and control_snapshot["maintenance_only"],
        "AIS-Catcher Control has an independent maintenance snapshot",
    )

    adsb_state = {"readsb.service": service("readsb.service", active=True)}
    adsb_running = derive(
        "adsb",
        adsb_state,
        {"runtime_verified": True},
        {"runtime_files_fresh": True, "targets": 0},
    )
    check(adsb_running["lifecycle_state"] == "RUNNING", "verified readsb runtime is RUNNING")

    adsb_state["readsb.service"]["active_age_seconds"] = 2.0
    adsb_starting = derive(
        "adsb",
        adsb_state,
        {"runtime_verified": True},
        {"runtime_files_fresh": False},
    )
    check(adsb_starting["lifecycle_state"] == "STARTING", "young unverified readsb is STARTING")

    adsb_state["readsb.service"]["active_age_seconds"] = 60.0
    adsb_attention = derive(
        "adsb",
        adsb_state,
        {"runtime_verified": True},
        {"runtime_files_fresh": False},
    )
    check(adsb_attention["lifecycle_state"] == "ATTENTION", "stale active readsb is ATTENTION")


def validate_action_order() -> None:
    lifecycle = app_lifecycle_namespace()
    action_steps = lifecycle["_service_action_steps"]

    check(
        action_steps("ais", "stop") == [
            ("stop", "ais-catcher.service"),
        ],
        "normal Stop AIS stops only AIS-Catcher",
    )
    check(
        action_steps("ais", "start") == [
            ("start", "ais-catcher.service"),
        ],
        "normal Start AIS starts only AIS-Catcher",
    )
    check(
        action_steps("ais", "restart") == [
            ("stop", "ais-catcher.service"),
            ("start", "ais-catcher.service"),
        ],
        "normal AIS restart never starts Control",
    )
    app_source = read("dashboard/app.py")
    check(
        "for operation, target in steps:" in app_source
        and "result = run_systemctl(operation, target)" in app_source,
        "existing dashboard authority executes the registered lifecycle steps",
    )
    check(
        '"automatic_restart_performed": False' in app_source,
        "successful service action performs no automatic restart",
    )
    check(
        '"maintenance_service": AIS_CONTROL_SERVICE' in app_source
        and "handle_maintenance_service_action" in app_source,
        "AIS-Catcher Control uses an explicit maintenance-only action path",
    )


def validate_maintenance_action_execution() -> None:
    source = read("dashboard/app.py")
    tree = ast.parse(source, filename="dashboard/app.py")
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "AIS_CONTROL_SERVICE" in targets:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "get_ais_control_snapshot",
            "handle_maintenance_service_action",
        }:
            selected.append(node)

    current = {"active": False}
    calls = []

    def observed(name: str) -> dict:
        return service(name, active=current["active"])

    def execute(action: str, target: str) -> SimpleNamespace:
        calls.append((action, target))
        current["active"] = action == "start"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    namespace = {
        "jsonify": lambda value: value,
        "receiver_manager": SimpleNamespace(service_action_block=lambda plugin, action: None),
        "service_state": observed,
        "run_systemctl": execute,
        "wait_for_service": lambda target, expected, timeout: (
            current["active"] is (expected == "active")
        ),
        "write_log": lambda message: None,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "dashboard/app.py", "exec"), namespace)
    action = {
        "label": "AIS-Catcher Control starten",
        "plugin_id": "ais",
        "systemctl": "start",
        "maintenance_service": "ais-catcher-control.service",
    }
    response = namespace["handle_maintenance_service_action"](
        "start_ais_control",
        action,
    )
    check(response.get("ok") is True, "maintenance Start action reaches RUNNING")
    check(
        calls == [("start", "ais-catcher-control.service")],
        "maintenance Start targets only AIS-Catcher Control",
    )


def validate_presentation_contracts() -> None:
    javascript = read("dashboard/static/js/services.js")
    dashboard_loader = read("dashboard/static/dashboard.js")
    dashboard_module = read("dashboard/static/js/dashboard.js")
    statusbar = read("dashboard/static/js/statusbar.js")
    stylesheet = read("dashboard/static/css/system.css")
    template = read("dashboard/templates/index.html")
    app_source = read("dashboard/app.py")

    for state in ("RUNNING", "STOPPED", "STARTING", "PARTIAL", "ATTENTION"):
        check(state in javascript or state in app_source, f"System exposes lifecycle state {state}")
    check("service.can_start" in javascript and "service.can_stop" in javascript, "buttons use lifecycle capabilities")
    check("lifecycle_state" in statusbar, "status bar uses verified lifecycle state")
    check("ais-service-detail" in template and "adsb-service-detail" in template, "service detail hooks are present")
    check(
        "start_ais_control" in template
        and "stop_ais_control" in template
        and "Advanced Maintenance" in template,
        "Advanced Maintenance exposes separate AIS-Catcher Control buttons",
    )
    check(
        "start_ais_control" in javascript and "data.ais_control" in javascript,
        "maintenance buttons use the independent Control status",
    )
    check(
        any(version in template for version in ("dashboard.js?v=0.54.0q-r3", "dashboard.js?v=0.54.0t-r1"))
        and any(version in dashboard_loader for version in ("dashboard.js?v=0.54.0q-r3", "dashboard.js?v=0.54.0t-r1"))
        and "services.js?v=0.54.0q-r3" in dashboard_module,
        "q-r3 service module remains cache-busted through an approved dashboard chain",
    )
    check(".system-service-row.is-partial" in stylesheet, "PARTIAL has an attention presentation")
    check(".system-service-row.is-attention" in stylesheet, "ATTENTION has a failure presentation")
    check("systemctl enable" not in app_source, "dashboard actions never change autostart")
    check(
        '"automatic_restart_performed": False' in app_source,
        "dashboard explicitly reports that no automatic restart was performed",
    )


def main() -> None:
    validate_registry_and_runtime()
    validate_inventory_availability()
    validate_readsb_readiness()
    validate_lifecycle_projection()
    validate_action_order()
    validate_maintenance_action_execution()
    validate_presentation_contracts()
    print("PASS: v0.54.0q System Service Lifecycle Integrity validation complete")


if __name__ == "__main__":
    main()
