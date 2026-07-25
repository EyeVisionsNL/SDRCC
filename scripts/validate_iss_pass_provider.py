#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import inspect
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import iss_passes, mission_planner, mission_queue, mission_scheduler


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")

status = iss_passes.get_status()
check(status["tle_present"] is True, "ISS TLE present and valid")
check(status["state"] == "active", "ISS pass provider active")
passes = iss_passes.get_passes(48)
check(len(passes) > 0, "ISS passes predicted in 48-hour horizon")
check(all(item["start"].tzinfo is not None for item in passes), "ISS pass times are timezone-aware")
check(all(item["start"] < item["maximum"] < item["end"] for item in passes), "ISS lifecycle order valid")
check(all(item["max_elevation"] >= item["min_elevation"] for item in passes), "ISS minimum elevation respected")
check(all(item["frequency"] == 437800000 for item in passes), "ISS downlink frequency preserved")

plan = mission_planner.get_plan(48)
check(plan["version"] == "0.46.0f", "planner version")
iss_source = next(item for item in plan["sources"] if item["plugin_id"] == "iss_voice")
check(iss_source["candidate_count"] == len(passes), "ISS source candidate count reported")
iss_candidates = [item for item in plan["candidates"] if item["plugin_id"] == "iss_voice"]
check(len(iss_candidates) == len(passes), "ISS candidates enter generic planner")
check(all(item["automation_eligible"] is False for item in iss_candidates), "ISS automation remains disabled")
check(all(item["execution_enabled"] is False for item in iss_candidates), "ISS execution remains disabled")
check(all(item["receiver_role"] == "iss_voice" for item in iss_candidates), "ISS receiver role preserved")

payload = mission_queue.get_payload(limit=50, hours_ahead=48)
queue_iss = [item for item in payload["queue"] if item["plugin_id"] == "iss_voice"]
check(len(queue_iss) > 0, "ISS appears in Mission Queue")
check(all(item["automation_eligible"] is False for item in queue_iss), "Mission Queue keeps ISS non-automatic")

scheduler = mission_scheduler.get_scheduler_status(queue_limit=10, hours_ahead=48)
check(all(item["plugin_id"] == "weather" for item in scheduler["queue"]), "scheduler excludes non-eligible ISS missions")

source = inspect.getsource(iss_passes) + inspect.getsource(mission_planner)
check("systemctl" not in source, "pass provider contains no service authority")
check("reserve(" not in source and "release(" not in source, "pass provider contains no receiver authority")
check("rtl_sdr" not in source and "rtl_fm" not in source, "pass provider contains no RF execution")
print("\nISS Pass Prediction Foundation validation PASS")
