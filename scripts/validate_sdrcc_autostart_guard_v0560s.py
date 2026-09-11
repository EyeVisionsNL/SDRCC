#!/usr/bin/env python3
"""Validate the fixed-target FlexGround autostart maintenance guard."""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def load_helper():
    path = ROOT / "scripts/sdrcc_disable_self_autostart.py"
    spec = importlib.util.spec_from_file_location("sdrcc_autostart_helper", path)
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

    payload = helper.disable_self_autostart(run=run)
    check(payload["ok"], "helper verifies FlexGround autostart disabled")
    check(
        ["/usr/bin/systemctl", "disable", "sdrcc.service"] in calls,
        "helper targets only sdrcc.service",
    )
    check(not any("--now" in call for call in calls), "helper does not stop the dashboard")

    missing_calls = []

    def missing(command):
        missing_calls.append(command)
        return SimpleNamespace(returncode=0, stdout="not-found\n", stderr="")

    payload = helper.disable_self_autostart(run=missing)
    check(not payload["ok"], "missing unit blocks the action")
    check(not any(call[1] == "disable" for call in missing_calls), "preflight failure makes no change")


def validate_dashboard_action() -> None:
    source = (ROOT / "dashboard/app.py").read_text()
    tree = ast.parse(source, filename="dashboard/app.py")
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "SDRCC_AUTOSTART_HELPER" in names:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "handle_sdrcc_autostart_disable_action":
            selected.append(node)

    state = {"enabled": "enabled", "active": True}

    def execute(command, timeout=30):
        assert command == ["sudo", "-n", "/usr/local/sbin/sdrcc-disable-self-autostart"]
        state["enabled"] = "disabled"
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    namespace = {
        "Path": Path,
        "json": json,
        "service_state": lambda name: dict(state, service=name),
        "run_command": execute,
        "write_log": lambda message: None,
        "jsonify": lambda value: value,
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), "dashboard/app.py", "exec"), namespace)
    payload = namespace["handle_sdrcc_autostart_disable_action"]()
    check(payload["ok"], "dashboard reports verified disabled state")
    check(payload["runtime_state_changed"] is False, "dashboard reports no runtime stop")
    check(state["active"], "dashboard remains active")


def validate_integration() -> None:
    app = (ROOT / "dashboard/app.py").read_text()
    template = (ROOT / "dashboard/templates/index.html").read_text()
    controls = (ROOT / "dashboard/static/js/controls.js").read_text()
    installer = (ROOT / "install.sh").read_text()
    updater = (ROOT / "scripts/install/update_existing.sh").read_text()
    uninstaller = (ROOT / "uninstall.sh").read_text()

    check('"disable_sdrcc_autostart"' in app, "backend action is explicitly allow-listed")
    check("SDRCC_AUTOSTART_HELPER" in app, "backend uses the fixed-target helper")
    check("FlexGround test mode" in template, "Advanced Maintenance contains the control")
    check("enable --now sdrcc.service" in template, "UI shows the recovery command")
    check("disable_sdrcc_autostart" in controls and "confirm(" in controls, "button requires confirmation")
    for source, label in ((installer, "clean installer"), (updater, "update installer")):
        check("sdrcc-disable-self-autostart" in source, f"{label} installs the helper")
        check("sdrcc-self-autostart" in source, f"{label} installs the sudoers boundary")
    check(
        "sdrcc-disable-self-autostart" in uninstaller and "sdrcc-self-autostart" in uninstaller,
        "uninstaller removes the integration",
    )
    check((ROOT / "VERSION").read_text().strip() == "0.56.0s", "release version is 0.56.0s")


def main() -> None:
    validate_helper()
    validate_dashboard_action()
    validate_integration()
    print("PASS: v0.56.0s-r1 FlexGround autostart guard validation complete")


if __name__ == "__main__":
    main()
