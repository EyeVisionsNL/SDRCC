#!/usr/bin/env python3
from pathlib import Path
import ast
import json
import tempfile
import yaml

ROOT = Path(__file__).resolve().parent.parent


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main():
    from core import config
    from core import receiver_contexts

    policy = config.get_assignment_restore_policy()
    check("foundation version", policy["version"] == "0.47.1a")
    check("mission roles centralized", set(policy["mission_assignments"]) == {"weather", "iss_voice"})
    check("both physical receivers supported", set(policy["receiver_ids"]) == {"sdr1", "sdr2"})
    check("AIS and ADS-B are flexible defaults", set(policy["default_context_plugins"]) == {"ais", "adsb"})
    check("foundation execution disabled", policy["execution_enabled"] is False)
    check("foundation restore disabled", policy["restore_enabled"] is False)

    snapshot = receiver_contexts.get_snapshot()
    check("context snapshot valid", snapshot["ok"] is True)
    check("context API contract read-only", snapshot["read_only"] is True)
    check("no service authority", snapshot["service_authority"] is False)
    check("no receiver authority", snapshot["receiver_authority"] is False)
    check("no mission engine authority", snapshot["mission_engine_authority"] is False)

    source = (ROOT / "core" / "receiver_contexts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import)}
    check("context module contains no subprocess import", "subprocess" not in imports)
    check("context module contains no systemctl", "systemctl" not in source)

    station = yaml.safe_load((ROOT / "config" / "station.yaml").read_text(encoding="utf-8"))
    check("mission_assignments persisted", isinstance(station.get("mission_assignments"), dict))
    check("receiver_defaults persisted", isinstance(station.get("receiver_defaults"), dict))
    check("legacy assignments retained", isinstance(station.get("assignments"), dict))

    app_source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    for route in ("/api/receiver-contexts", "/api/mission-assignments", "/api/receiver-defaults"):
        check(f"route present {route}", route in app_source)

    html = (ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    check("Mission Assignments UI present", "mission-assignments-form" in html)
    check("Receiver Defaults UI present", "receiver-defaults-form" in html)
    print("VALIDATION PASS: v0.47.1a Mission Assignment & Restore Policy Foundation")


if __name__ == "__main__":
    main()
