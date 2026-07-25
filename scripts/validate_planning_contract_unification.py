#!/usr/bin/env python3
"""Validate v0.47.0a planning contract unification."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission_planner, mission_queue


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


policy = mission_planner.get_policy()
minimum = float(policy["minimum_elevation"])
check(policy["scope"] == "all_mission_types", "planning policy applies to all mission types")
check(policy["source"].endswith("weather_planning.minimum_elevation"), "single persisted policy source retained compatibly")

# Deterministic provider test: one pass below and one above the policy.
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
base = {
    "name": "TEST",
    "start": now + timedelta(hours=1),
    "maximum": now + timedelta(hours=1, minutes=5),
    "end": now + timedelta(hours=1, minutes=10),
    "frequency": 1,
}
low = dict(base, max_elevation=minimum - 1.0, plugin_id="iss_voice", mission_type="iss_voice")
high = dict(base, start=now + timedelta(hours=2), maximum=now + timedelta(hours=2, minutes=5),
            end=now + timedelta(hours=2, minutes=10), max_elevation=minimum + 1.0,
            plugin_id="iss_voice", mission_type="iss_voice")

approved, rejected = mission_planner._apply_policy([low, high], policy)
check(len(approved) == 1 and approved[0]["max_elevation"] >= minimum, "central planner approves only passes at or above limit")
check(len(rejected) == 1 and rejected[0]["planning_decision"] == "BELOW_LIMIT", "central planner rejects below-limit pass")
check(approved[0]["min_elevation"] == minimum, "approved candidate carries central limit")

plan = mission_planner.get_plan(48)
check(plan["version"] == "0.47.0a", "planner version")
check(plan["authority"] == "planning_only", "planner remains planning-only")
check(all(float(item["max_elevation"]) >= minimum for item in plan["candidates"]), "all live planner candidates satisfy central elevation policy")
check(all(item["planning_decision"] == "ELIGIBLE" for item in plan["candidates"]), "planner emits explicit eligibility decision")

sources = {item["plugin_id"]: item for item in plan["sources"]}
check(sources["weather"]["minimum_elevation"] == minimum, "Weather reports central elevation policy")
check(sources["iss_voice"]["minimum_elevation"] == minimum, "ISS reports central elevation policy")
check(sources["iss_voice"]["execution_enabled"] is False, "ISS execution remains disabled")

payload = mission_queue.get_payload(limit=50, hours_ahead=48)
check(payload["planner_version"] == "0.47.0a", "Mission Queue reports unified planner version")
check(payload["minimum_elevation"] == minimum, "Mission Queue reports central elevation policy")
check(all(float(item["max_elevation"]) >= minimum for item in payload["queue"]), "Mission Queue excludes below-limit passes")
check(all(item.get("decision") for item in payload["queue"]), "Mission Queue owns display decisions")
check(all(item.get("decision_reason") for item in payload["queue"]), "Mission Queue owns decision reasons")

js = (ROOT / "dashboard/static/js/mission_planner.js").read_text(encoding="utf-8")
check("elevation < minimumElevation" not in js, "UI contains no duplicate elevation decision")
check("item.decision" in js and "item.decision_reason" in js, "UI consumes API decisions")

planner_source = (ROOT / "core/mission_planner.py").read_text(encoding="utf-8")
iss_source = (ROOT / "core/iss_passes.py").read_text(encoding="utf-8")
check("systemctl" not in planner_source and "receiver_manager" not in planner_source, "planner has no service or receiver authority")
check('config.get("minimum_elevation"' not in iss_source, "ISS provider no longer owns a separate elevation limit")

print("\nPlanning Contract Unification validation PASS")
