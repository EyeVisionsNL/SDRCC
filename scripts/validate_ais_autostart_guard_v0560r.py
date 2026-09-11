#!/usr/bin/env python3
"""Validate the fixed-target AIS update autostart guard."""
from __future__ import annotations

import importlib.util
import ast
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def load_helper():
    path = ROOT / "scripts/sdrcc_disable_ais_autostart.py"
    spec = importlib.util.spec_from_file_location("ais_autostart_helper", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def validate_helper() -> None:
    helper = load_helper()
    calls = []

    def run(command):
        calls.append(command)
        if command[1] == "show":
            return SimpleNamespace(returncode=0, stdout="loaded\n", stderr="")
        if command[1] == "disable":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="disabled\n", stderr="")

    payload = helper.disable_ais_autostart(run=run)
    check(payload["ok"], "helper verifies both services disabled")
    check(
        ["/usr/bin/systemctl", "disable", "ais-catcher.service", "ais-catcher-control.service"] in calls,
        "helper targets only the two exact AIS services",
    )
    check(not any("--now" in call for call in calls), "helper does not stop running AIS services")

    missing_calls = []

    def missing(command):
        missing_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="not-found\n", stderr="")

    missing_payload = helper.disable_ais_autostart(run=missing)
    check(not missing_payload["ok"], "missing unit blocks the action before mutation")
    check(not any(call[1] == "disable" for call in missing_calls), "preflight failure makes no change")


def validate_integration() -> None:
    app = (ROOT / "dashboard/app.py").read_text()
    template = (ROOT / "dashboard/templates/index.html").read_text()
    controls = (ROOT / "dashboard/static/js/controls.js").read_text()
    installer = (ROOT / "install.sh").read_text()
    updater = (ROOT / "scripts/install/update_existing.sh").read_text()
    uninstaller = (ROOT / "uninstall.sh").read_text()

    check('"disable_ais_autostart"' in app, "backend action is explicitly allow-listed")
    check("AIS_AUTOSTART_HELPER" in app, "backend delegates to the fixed-target helper")
    check("AIS update protection" in template, "Advanced Maintenance contains the AIS update guard")
    check("disable_ais_autostart" in controls and "confirm(" in controls, "button requires confirmation")
    check("Running services were not stopped" in app, "operator receives runtime-state feedback")
    for source, label in ((installer, "clean installer"), (updater, "update installer")):
        check("sdrcc-disable-ais-autostart" in source, f"{label} installs privileged boundary")
        check("sdrcc-ais-autostart" in source, f"{label} installs exact sudoers rule")
    check(
        updater.index('INSTALL_USER="$(stat -c %U "$PROJECT_ROOT")"')
        < updater.index('if [[ ! -f "$INSTALL_RECEIPT" ]]'),
        "update installer defines the project owner for existing receipts",
    )
    check(
        "sdrcc-disable-ais-autostart" in uninstaller and "sdrcc-ais-autostart" in uninstaller,
        "uninstaller removes the new integration",
    )
    check(
        (ROOT / "VERSION").read_text().strip() in {"0.56.0r", "0.56.0s"},
        "AIS autostart guard remains present in the current release",
    )


def validate_dashboard_action() -> None:
    source = (ROOT / "dashboard/app.py").read_text()
    tree = ast.parse(source, filename="dashboard/app.py")
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name in {"AIS_AUTOSTART_HELPER", "AIS_CONTROL_SERVICE"} for name in names):
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "handle_ais_autostart_disable_action":
            selected.append(node)

    states = {
        "ais-catcher.service": {"enabled": "enabled", "active": True},
        "ais-catcher-control.service": {"enabled": "enabled", "active": False},
    }

    def execute(command, timeout=30):
        assert command == ["sudo", "-n", "/usr/local/sbin/sdrcc-disable-ais-autostart"]
        for state in states.values():
            state["enabled"] = "disabled"
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    namespace = {
        "Path": Path,
        "json": json,
        "service_state": lambda name: dict(states[name], service=name),
        "run_command": execute,
        "write_log": lambda message: None,
        "jsonify": lambda value: value,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "dashboard/app.py", "exec"), namespace)
    payload = namespace["handle_ais_autostart_disable_action"]()
    check(payload["ok"], "dashboard action reports verified disabled state")
    check(payload["runtime_state_changed"] is False, "dashboard reports no runtime stop")
    check(states["ais-catcher.service"]["active"], "active AIS reception remains running")


def main() -> None:
    validate_helper()
    validate_integration()
    validate_dashboard_action()
    print("PASS: v0.56.0r-r2 AIS autostart guard validation complete")


if __name__ == "__main__":
    main()
