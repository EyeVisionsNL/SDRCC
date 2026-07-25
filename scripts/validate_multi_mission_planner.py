#!/usr/bin/env python3
from pathlib import Path
import inspect
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission_planner, mission_queue, mission_scheduler


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


plan = mission_planner.get_plan(1)
check(plan["version"] == "0.46.0e", "planner version")
check(plan["authority"] == "planning_only", "planner remains planning-only")
source_ids = {item["plugin_id"] for item in plan["sources"]}
check({"weather", "iss_voice"}.issubset(source_ids), "Weather and ISS Voice sources registered")
iss = next(item for item in plan["sources"] if item["plugin_id"] == "iss_voice")
check(iss["state"] == "foundation_only", "ISS Voice provider remains foundation-only")
check(iss["candidate_count"] == 0, "ISS Voice does not inject unvalidated passes")
check(all(item.get("plugin_id") == "weather" for item in plan["candidates"]), "existing candidates retain Weather identity")
check(all(item.get("automation_eligible") is True for item in plan["candidates"]), "Weather automation eligibility preserved")
queue = mission_queue.get_payload(limit=5, hours_ahead=1)
check(queue["source"] == "multi-mission-planner", "Mission Queue uses generic planner")
check(queue["planner_authority"] == "planning_only", "Mission Queue reports planner authority")
check("sources" in queue, "Mission Queue exposes source status")
status = mission_scheduler.get_scheduler_status(queue_limit=2, hours_ahead=1)
check(all(item.get("plugin_id") == "weather" for item in status["queue"]), "scheduler still selects only eligible Weather missions")
planner_source = inspect.getsource(mission_planner)
check("systemctl" not in planner_source, "planner contains no service-control authority")
check("reserve(" not in planner_source and "release(" not in planner_source, "planner contains no receiver authority")
print("\nMulti-Mission Planner Foundation validation PASS")
