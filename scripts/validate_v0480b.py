#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission_planner, mission_scheduler  # noqa: E402


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


sources = {item["plugin_id"]: item for item in mission_planner.get_sources(48)}
check("weather" in sources, "Mission Planner exposes Weather")
check("iss_voice" in sources, "Mission Planner exposes ISS Voice")
check(sources["iss_voice"]["execution_enabled"] is True, "ISS Voice execution contract is enabled")

now = datetime.now(timezone.utc)
base = {
    "receiver_role": "iss_voice",
    "automation_eligible": True,
    "execution_enabled": True,
    "priority": 3,
    "start": now + timedelta(hours=2),
    "maximum": now + timedelta(hours=2, minutes=5),
    "end": now + timedelta(hours=2, minutes=10),
    "sample_rate": 240_000,
    "pipeline": "iss_voice",
    "mode": "NFM",
    "decoder": "offline_fm",
    "max_elevation": 55.0,
    "azimuth": 180.0,
    "min_elevation": 20.0,
}
synthetic_iss = {
    **base,
    "plugin_id": "iss_voice",
    "mission_type": "iss_voice",
    "planner_source": "iss_passes",
    "name": "ISS (ZARYA)",
    "frequency": 437_800_000,
}
synthetic_weather = {
    **base,
    "plugin_id": "weather",
    "mission_type": "weather",
    "receiver_role": "weather",
    "planner_source": "weather_passes",
    "name": "METEOR-M2 3",
    "start": now + timedelta(hours=3),
    "maximum": now + timedelta(hours=3, minutes=5),
    "end": now + timedelta(hours=3, minutes=10),
    "frequency": 137_900_000,
}
blocked = {
    **synthetic_iss,
    "name": "BLOCKED ISS",
    "start": now + timedelta(hours=1),
    "maximum": now + timedelta(hours=1, minutes=5),
    "end": now + timedelta(hours=1, minutes=10),
    "execution_enabled": False,
}

original_get_candidates = mission_planner.get_candidates
original_get_executable = mission_planner.get_executable_candidates
original_load_state = mission_scheduler._load_state
try:
    mission_planner.get_candidates = lambda hours_ahead=48: [blocked, synthetic_weather, synthetic_iss]
    executable = mission_planner.get_executable_candidates(48)
    check([item["name"] for item in executable] == ["ISS (ZARYA)", "METEOR-M2 3"], "Planner builds one chronological executable queue")

    mission_planner.get_executable_candidates = lambda hours_ahead=48: executable
    mission_scheduler._load_state = lambda: {
        "mode": "AUTO",
        "observer_only": True,
        "updated": None,
    }
    status = mission_scheduler.get_scheduler_status(queue_limit=5, hours_ahead=48)
finally:
    mission_planner.get_candidates = original_get_candidates
    mission_planner.get_executable_candidates = original_get_executable
    mission_scheduler._load_state = original_load_state

next_pass = status.get("next_pass") or {}
check(next_pass.get("mission_type") == "iss_voice", "Scheduler selects earliest executable mission regardless of plugin")
check(next_pass.get("execution_enabled") is True, "Scheduler preserves execution contract")
check(next_pass.get("automation_eligible") is True, "Scheduler preserves automation contract")
check(status.get("observer", {}).get("detail") == "Wachten op volgende ISS Voice-passage", "Observer text follows selected mission type")
check(status.get("next_action") == "Observer: profiel ISS Voice voorbereiden", "Next action follows selected mission type")
check(status.get("preflight", {}).get("status") == "AUTOPILOT_OWNED", "Scheduler does not execute preflight")

planner_source = (ROOT / "core" / "mission_planner.py").read_text(encoding="utf-8")
scheduler_source = (ROOT / "core" / "mission_scheduler.py").read_text(encoding="utf-8")
check("def get_executable_candidates" in planner_source, "Planner publishes executable queue contract")
check("mission_planner.get_executable_candidates" in scheduler_source, "Scheduler consumes only planner executable queue")

# Inspect actual imports/calls instead of rejecting harmless metadata strings such
# as planner_source="weather_passes" in serialized mission records.
tree = ast.parse(scheduler_source)
imported_names: set[str] = set()
called_paths: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        imported_names.update(alias.name for alias in node.names)
    elif isinstance(node, ast.ImportFrom):
        module = node.module or ""
        imported_names.add(module)
        imported_names.update(f"{module}.{alias.name}" for alias in node.names)
    elif isinstance(node, ast.Call):
        parts: list[str] = []
        current = node.func
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        if parts:
            called_paths.add(".".join(reversed(parts)))

check(not any("mission_preflight" in name for name in imported_names | called_paths), "Scheduler contains no preflight execution authority")
check(not any(name.endswith("weather_passes") or ".weather_passes" in name for name in imported_names | called_paths), "Scheduler contains no Weather provider dependency")
check(not any(name.endswith("iss_passes") or ".iss_passes" in name for name in imported_names | called_paths), "Scheduler contains no ISS provider dependency")

print("\nv0.48.0b-fix1 validation PASS")
