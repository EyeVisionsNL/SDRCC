#!/usr/bin/env python3
"""Validate the v0.54.0a single receiver-assignment authority contract."""

from pathlib import Path
import ast

import yaml


ROOT = Path(__file__).resolve().parent.parent


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main():
    from core import config

    policy = config.get_assignment_restore_policy()
    check("authority version", policy["version"] == "0.54.0a")
    check(
        "single persistent authority declared",
        policy["assignment_authority"] == "config/station.yaml:assignments",
    )
    check("only assignments persists", policy["persistent_assignment_keys"] == ["assignments"])
    check("execution enabled", policy["execution_enabled"] is True)
    check("rollback enabled", policy["restore_enabled"] is True)
    check("legacy mappings are compatibility views", policy["compatibility_views_only"] is True)
    check("both physical receivers supported", set(policy["receiver_ids"]) == {"sdr1", "sdr2"})

    assignments = policy["assignments"]
    missions = policy["mission_assignments"]
    defaults = policy["receiver_defaults"]
    check(
        "mission projection derived from assignments",
        missions == {role: assignments.get(role) for role in ("weather", "iss_voice")},
    )
    projected_defaults = {receiver_id: [] for receiver_id in policy["receiver_ids"]}
    for role in ("ais", "adsb"):
        receiver_id = assignments.get(role)
        if receiver_id in projected_defaults:
            projected_defaults[receiver_id].append(role)
    check("service defaults derived from assignments", defaults == projected_defaults)

    station = yaml.safe_load((ROOT / "config" / "station.yaml").read_text(encoding="utf-8"))
    check("assignments persisted", isinstance(station.get("assignments"), dict))
    check("mission_assignments removed", "mission_assignments" not in station)
    check("receiver_defaults removed", "receiver_defaults" not in station)

    authority_source = (ROOT / "core" / "receiver_authority.py").read_text(encoding="utf-8")
    tree = ast.parse(authority_source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    check("authority has no Flask dependency", "flask" not in imports)
    check("authority never starts missions", "start_mission" not in authority_source)
    check("authority exposes transaction coordinator", "def apply_assignments(" in authority_source)
    check("authority exposes runtime verification", "def get_snapshot(" in authority_source)

    helper_source = (ROOT / "scripts" / "sdrcc_apply_receiver_roles.py").read_text(
        encoding="utf-8"
    )
    check("privileged helper is standalone", "from core" not in helper_source)
    check("privileged helper has rollback", "rollback" in helper_source.lower())

    app_source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    for route in (
        "/api/receiver-assignments",
        "/api/mission-assignments",
        "/api/receiver-defaults",
        "/api/receiver-monitor",
    ):
        check(f"route present {route}", route in app_source)
    check(
        "all assignment writers use common transaction",
        app_source.count("_apply_receiver_assignment_changes(") >= 6,
    )
    check(
        "transaction reserves through Receiver Manager",
        "_reserve_assignment_transaction_receivers" in app_source
        and "receiver_manager.reserve(" in app_source,
    )
    check(
        "service serial is never read from station role blocks",
        "station[ais_receiver][\"serial\"]" not in app_source,
    )

    html = (ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    check("one Receiver Assignments form", html.count('id="receiver-assignments-form"') == 1)
    check("old Mission Assignments form removed", "mission-assignments-form" not in html)
    check("old Receiver Defaults form removed", "receiver-defaults-form" not in html)
    print("VALIDATION PASS: v0.54.0a Receiver Assignment Authority")


if __name__ == "__main__":
    main()
