#!/usr/bin/env python3
"""Deterministic validator for v0.54.0e Mission Control status clarity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import types


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


try:
    import skyfield.api  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    skyfield = types.ModuleType("skyfield")
    skyfield_api = types.ModuleType("skyfield.api")
    skyfield_api.EarthSatellite = object
    skyfield_api.load = types.SimpleNamespace()
    skyfield_api.wgs84 = types.SimpleNamespace()
    skyfield.api = skyfield_api
    sys.modules["skyfield"] = skyfield
    sys.modules["skyfield.api"] = skyfield_api


from core import iss_voice_runtime, mission_queue  # noqa: E402


errors: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"PASS: {label}")
    else:
        print(f"FAIL: {label}")
        errors.append(label)


def candidate(
    name: str,
    plugin_id: str,
    receiver_role: str,
    start: datetime,
    end: datetime,
) -> dict:
    return {
        "name": name,
        "plugin_id": plugin_id,
        "mission_type": plugin_id,
        "receiver_role": receiver_role,
        "planner_source": f"{plugin_id}_passes",
        "automation_eligible": True,
        "execution_enabled": True,
        "priority": 5,
        "start": start,
        "maximum": start + (end - start) / 2,
        "end": end,
        "max_elevation": 70.0,
        "minimum_peak_elevation": 40.0,
        "begin_elevation": 10.0,
        "close_elevation": 10.0,
        "planning_profile_id": plugin_id,
        "planning_decision": "ELIGIBLE",
        "planning_reason": "Deterministic validator candidate.",
        "frequency": 145_800_000 if plugin_id == "iss_voice" else 137_900_000,
        "mode": "NFM" if plugin_id == "iss_voice" else "QPSK",
        "pipeline": "wideband_iq_offline_fm" if plugin_id == "iss_voice" else "meteor_m2_lrpt",
    }


def validate_queue_projection() -> None:
    now = datetime.now(timezone.utc)
    weather = candidate(
        "METEOR-M2 4", "weather", "weather",
        now + timedelta(minutes=5), now + timedelta(minutes=12),
    )
    iss = candidate(
        "ISS (ZARYA)", "iss_voice", "iss_voice",
        now + timedelta(minutes=6), now + timedelta(minutes=11),
    )
    later = candidate(
        "ISS LATER", "iss_voice", "iss_voice",
        now + timedelta(minutes=14), now + timedelta(minutes=18),
    )
    candidates = [weather, iss, later]
    weather_key = mission_queue.get_pass_key(weather)
    iss_key = mission_queue.get_pass_key(iss)

    originals = {
        "get_candidates": mission_queue.mission_planner.get_candidates,
        "get_policy": mission_queue.mission_planner.get_policy,
        "get_sources": mission_queue.mission_planner.get_sources,
        "get_assignment": mission_queue.get_assignment,
        "get_scheduler_config": mission_queue.get_scheduler_config,
        "receiver_status": mission_queue.receiver_manager.get_status,
        "tle_status": mission_queue.tle.get_status,
        "load_state": mission_queue._load_state,
        "save_state": mission_queue._save_state,
    }
    overrides: dict[str, dict] = {}
    try:
        mission_queue.mission_planner.get_candidates = lambda hours: list(candidates)
        mission_queue.mission_planner.get_policy = lambda: {
            "minimum_elevation": 40.0,
            "profiles": {},
        }
        mission_queue.mission_planner.get_sources = lambda hours: []
        mission_queue.get_assignment = lambda role: "sdr1" if role == "weather" else "sdr2"
        mission_queue.get_scheduler_config = lambda: {
            "preflight_seconds": 300,
            "prepare_seconds": 90,
            "lock_seconds": 30,
        }
        mission_queue.receiver_manager.get_status = lambda: {"reservations": {}}
        mission_queue.tle.get_status = lambda: {"state": "CURRENT"}
        mission_queue._load_state = lambda: {"overrides": overrides}
        mission_queue._save_state = lambda state: None

        queue = mission_queue.get_queue(active_pass_key=weather_key, controller_status="RECORDING")
        first, blocked, third = queue
        check(first["status"] == "IN PROGRESS", "active first mission remains IN PROGRESS")
        check(first["live_mission_status"] == "RECORDING", "active queue exposes RECORDING")
        check(first["overlap_warning"] is True, "active mission exposes overlap warning")
        check(first["blocking"] == [iss_key], "active mission names the blocked queue key")
        check(blocked["status"] == "BLOCKED", "later cross-receiver mission is BLOCKED")
        check(blocked["blocked_by"] == weather_key, "blocked mission names its blocker")
        check(blocked["blocked_by_name"] == "METEOR-M2 4", "blocked mission names blocker satellite")
        check(blocked["blocked_by_receiver"] == "SDR1", "blocked mission names blocker receiver")
        check(blocked["conflict_scope"] == "mission_engine", "cross-receiver overlap reports global runtime scope")
        check(blocked["overlap_seconds"] == 300, "overlap duration is exact")
        check(blocked["decision_class"] == "blocked", "Planner receives blocked decision class")
        check(third["status"] == "QUEUED", "non-overlapping later mission remains queued")

        payload = mission_queue.get_payload(active_pass_key=weather_key, controller_status="RECORDING")
        check(payload["blocked"] == 1, "payload counts one blocked mission")
        check(payload["overlap_warnings"] == 1, "payload counts one blocking mission")

        overrides[weather_key] = {"skipped": True}
        skipped_queue = mission_queue.get_queue()
        check(skipped_queue[0]["status"] == "SKIPPED", "skipped mission does not occupy automation lane")
        check(skipped_queue[1]["status"] == "NEXT", "second mission becomes NEXT when blocker is skipped")
        check(skipped_queue[1]["blocked_by"] is None, "skipped blocker leaves no blocked metadata")

        same_receiver = [
            candidate(
                "METEOR FIRST", "weather", "weather",
                now + timedelta(minutes=20), now + timedelta(minutes=27),
            ),
            candidate(
                "METEOR SECOND", "weather", "weather",
                now + timedelta(minutes=21), now + timedelta(minutes=25),
            ),
        ]
        overrides.clear()
        candidates[:] = same_receiver
        same_queue = mission_queue.get_queue()
        check(same_queue[1]["status"] == "BLOCKED", "same-receiver overlap is blocked")
        check(same_queue[1]["conflict_scope"] == "receiver", "same-receiver overlap retains receiver scope")
    finally:
        mission_queue.mission_planner.get_candidates = originals["get_candidates"]
        mission_queue.mission_planner.get_policy = originals["get_policy"]
        mission_queue.mission_planner.get_sources = originals["get_sources"]
        mission_queue.get_assignment = originals["get_assignment"]
        mission_queue.get_scheduler_config = originals["get_scheduler_config"]
        mission_queue.receiver_manager.get_status = originals["receiver_status"]
        mission_queue.tle.get_status = originals["tle_status"]
        mission_queue._load_state = originals["load_state"]
        mission_queue._save_state = originals["save_state"]


def validate_iss_timing() -> None:
    original_paths = (
        iss_voice_runtime.STATE_DIR,
        iss_voice_runtime.STATE_FILE,
        iss_voice_runtime.LOCK_FILE,
    )
    with TemporaryDirectory() as directory:
        root = Path(directory)
        iss_voice_runtime.STATE_DIR = root
        iss_voice_runtime.STATE_FILE = root / "iss_voice_runtime.json"
        iss_voice_runtime.LOCK_FILE = root / "iss_voice_runtime.lock"
        now = datetime.now().astimezone()
        try:
            iss_voice_runtime.begin(
                phase="RECORDING",
                queue_key="iss_voice:ISS (ZARYA):test",
                start_epoch=int((now - timedelta(seconds=10)).timestamp()),
                end_epoch=int((now + timedelta(seconds=50)).timestamp()),
                capture_started_at=(now - timedelta(seconds=10)).isoformat(timespec="seconds"),
                duration_seconds=60,
            )
            status = iss_voice_runtime.get_status()
            check(status["queue_key"].startswith("iss_voice:"), "ISS runtime retains queue key")
            check(9 <= status["elapsed_seconds"] <= 12, "ISS runtime reports live elapsed time")
            check(48 <= status["remaining_seconds"] <= 51, "ISS runtime reports live remaining time")
            check(14 <= status["progress"] <= 20, "ISS runtime reports bounded recording progress")
        finally:
            (
                iss_voice_runtime.STATE_DIR,
                iss_voice_runtime.STATE_FILE,
                iss_voice_runtime.LOCK_FILE,
            ) = original_paths


def validate_integration_sources() -> None:
    app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    mission_js = (ROOT / "dashboard" / "static" / "js" / "mission.js").read_text(encoding="utf-8")
    scheduler_js = (ROOT / "dashboard" / "static" / "js" / "scheduler.js").read_text(encoding="utf-8")
    dashboard_js = (ROOT / "dashboard" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    controls_css = (ROOT / "dashboard" / "static" / "css" / "controls.css").read_text(encoding="utf-8")
    control_css = (ROOT / "dashboard" / "static" / "css" / "mission_control_v034.css").read_text(encoding="utf-8")
    template = (ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    executor = (ROOT / "core" / "iss_voice_executor.py").read_text(encoding="utf-8")
    operations = (ROOT / "core" / "mission_operations.py").read_text(encoding="utf-8")

    check('"iss_voice": iss_runtime' in app, "status API exposes existing ISS observer")
    check("iss_active_key" in app and "iss_runtime.get(\"phase\")" in app, "Queue uses ISS runtime identity and phase")
    check("queue_key=target.get(\"queue_key\")" in executor, "ISS executor publishes queue identity")
    check('"remaining_seconds": iss.get("remaining_seconds")' in operations, "Mission Operations preserves ISS remaining time")
    check("MissionState?.subscribe" in mission_js, "Mission cards consume the observer snapshot")
    check('phase = missedStart ? "NOT STARTED" : "MISSION OVERLAP"' in mission_js, "receiver card distinguishes warning from missed start")
    check("updateMissionEngine(data);" in dashboard_js, "dashboard passes both Weather and ISS status")
    check('rawStatus === "BLOCKED"' in scheduler_js, "Mission Queue renders BLOCKED state")
    check("mission-queue-warning" in controls_css, "Mission Queue has compact overlap warning style")
    check("mission-receiver-card-v034.is-recording" in control_css, "receiver card has recording accent")
    check("mission-receiver-card-v034.is-blocked" in control_css, "receiver card has blocked accent")
    check("mission_cards_v034.js" not in template, "obsolete duplicate card patch is no longer loaded")
    cache_busts = template.count("v=0.54.0e") + template.count("v=0.54.0f")
    check(cache_busts >= 3, "changed Mission Control assets are cache-busted")


validate_queue_projection()
validate_iss_timing()
validate_integration_sources()

if errors:
    raise SystemExit(f"FAIL: {len(errors)} v0.54.0e validation check(s) failed")

print("PASS: v0.54.0e Mission Control status clarity validation complete")
