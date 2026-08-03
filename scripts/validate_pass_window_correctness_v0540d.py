#!/usr/bin/env python3
"""Deterministic v0.54.0d pass-window, TLE and execution-contract checks."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from skyfield.api import EarthSatellite, load, wgs84

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import mission_planner, mission_queue, mission_scheduler, passes, satdump, tle, weather_planning


FIXTURE_TLE = """METEOR-M2 3
1 57166U 23091A   26211.87182029  .00000010  00000+0  23098-4 0  9995
2 57166  98.6056 265.9498 0004816  54.6366 305.5263 14.24050019160730
METEOR-M2 4
1 59051U 24039A   26211.86575183  .00000014  00000+0  25903-4 0  9990
2 59051  98.7046 170.6213 0007983  49.5298 310.6574 14.22433614125475
ISS (ZARYA)
1 25544U 98067A   26199.08891132  .00003768  00000+0  76429-4 0  9994
2 25544  51.6318 147.1664 0006793 308.8910  51.1472 15.49037991576544
"""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def base_candidate(*, profile_id: str, elevation: float, offset_hours: int) -> dict:
    start = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return {
        "name": profile_id,
        "plugin_id": "iss_voice" if profile_id == "iss_voice" else "weather",
        "mission_type": "iss_voice" if profile_id == "iss_voice" else "weather",
        "receiver_role": "iss_voice" if profile_id == "iss_voice" else "weather",
        "planning_profile_id": profile_id,
        "start": start,
        "maximum": start + timedelta(minutes=4),
        "end": start + timedelta(minutes=8),
        "max_elevation": elevation,
        "frequency": 137_900_000,
        "sample_rate": 1_000_000,
        "pipeline": "fixture",
        "mode": "TEST",
        "decoder": "fixture",
        "automation_eligible": True,
        "execution_enabled": True,
        "priority": 1,
        "norad_id": 57166,
        "tle_source": "CelesTrak",
        "tle_epoch": "2026-07-30T20:55:25+00:00",
        "tle_sha256": "fixture-hash",
    }


blocks = tle.parse_text(FIXTURE_TLE, expected_catalogs=tle.REQUIRED_CATALOGS)
check(set(blocks) == {25544, 57166, 59051}, "required NORAD catalogs parsed exactly")
check(all(tle.checksum_valid(blocks[key]["line1"]) for key in blocks), "line 1 checksums valid")
check(all(tle.checksum_valid(blocks[key]["line2"]) for key in blocks), "line 2 checksums valid")
broken = FIXTURE_TLE.replace("15.49037991576544", "15.49037991576545")
try:
    tle.parse_text(broken, expected_catalogs=tle.REQUIRED_CATALOGS)
except ValueError:
    pass
else:
    raise AssertionError("invalid checksum accepted")
print("PASS: invalid checksum rejected before file replacement")

ts = load.timescale()
iss_block = blocks[25544]
station = wgs84.latlon(51.908401, 4.351168, elevation_m=6)
geometry = passes.predict_satellite_passes(
    name="ISS (ZARYA)",
    line1=iss_block["line1"],
    line2=iss_block["line2"],
    station=station,
    planning={
        "minimum_peak_elevation": 20.0,
        "begin_elevation": 10.0,
        "close_elevation": 15.0,
    },
    hours_ahead=24,
    start_time=datetime(2026, 7, 19, tzinfo=timezone.utc),
    timescale=ts,
)
check(bool(geometry), "shared Skyfield predictor produces ISS windows")
window = geometry[0]
satellite = EarthSatellite(iss_block["line1"], iss_block["line2"], "ISS", ts)
start_altitude = (satellite - station).at(ts.from_datetime(window["start"])).altaz()[0].degrees
end_altitude = (satellite - station).at(ts.from_datetime(window["end"])).altaz()[0].degrees
check(abs(start_altitude - 10.0) < 0.2, "rising boundary uses configured begin angle")
check(abs(end_altitude - 15.0) < 0.2, "falling boundary uses configured close angle")
check(window["start"] < window["maximum"] < window["end"], "pass-window lifecycle order valid")

with TemporaryDirectory(prefix="sdrcc-v0540d-config-") as temp_name:
    temp = Path(temp_name)
    station_file = temp / "station.yaml"
    satellites_file = temp / "satellites.yaml"
    iss_file = temp / "iss_voice.yaml"
    station_file.write_text((ROOT / "config/station.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    satellites_file.write_text((ROOT / "config/satellites.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    iss_file.write_text((ROOT / "config/iss_voice.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    satellite_data = yaml.safe_load(satellites_file.read_text(encoding="utf-8"))
    satellite_data["custom_user_key"] = "preserve-me"
    satellites_file.write_text(yaml.safe_dump(satellite_data, sort_keys=False), encoding="utf-8")
    with patch.object(weather_planning, "STATION_FILE", station_file), \
         patch.object(weather_planning, "SATELLITES_FILE", satellites_file), \
         patch.object(weather_planning, "ISS_CONFIG_FILE", iss_file):
        configured = weather_planning.set_config({"profiles": {
            "meteor_m2_3": {"minimum_peak_elevation": 30, "begin_elevation": 7, "close_elevation": 8},
            "meteor_m2_4": {"minimum_peak_elevation": 45, "begin_elevation": 12, "close_elevation": 13},
            "iss_voice": {"minimum_peak_elevation": 25, "begin_elevation": 5, "close_elevation": 6},
        }})
        profiles = configured["profiles"]
        check(profiles["meteor_m2_3"]["minimum_peak_elevation"] == 30.0, "METEOR-M2 3 profile persists independently")
        check(profiles["meteor_m2_4"]["begin_elevation"] == 12.0, "METEOR-M2 4 profile persists independently")
        check(profiles["iss_voice"]["close_elevation"] == 6.0, "ISS Voice profile persists independently")
        preserved = yaml.safe_load(satellites_file.read_text(encoding="utf-8"))
        check(preserved["custom_user_key"] == "preserve-me", "unrelated user configuration preserved")
        policy = mission_planner.get_policy()
        approved, rejected = mission_planner._apply_policy([
            base_candidate(profile_id="meteor_m2_3", elevation=35, offset_hours=1),
            base_candidate(profile_id="meteor_m2_4", elevation=35, offset_hours=2),
            base_candidate(profile_id="iss_voice", elevation=26, offset_hours=3),
        ], policy)
        check({item["planning_profile_id"] for item in approved} == {"meteor_m2_3", "iss_voice"}, "per-profile peak gates approve independently")
        check(len(rejected) == 1 and rejected[0]["planning_profile_id"] == "meteor_m2_4", "per-profile peak gate rejects only matching satellite")

raw = base_candidate(profile_id="meteor_m2_3", elevation=70, offset_hours=1)
raw.update({"minimum_peak_elevation": 30.0, "begin_elevation": 7.0, "close_elevation": 8.0})
pinned_serialized = mission_scheduler._serialize_pass(raw)
pinned_serialized["start_epoch"] -= 70
pinned_serialized["maximum_epoch"] -= 70
pinned_serialized["end_epoch"] -= 70
pinned_serialized["start"] = datetime.fromtimestamp(pinned_serialized["start_epoch"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
pinned_serialized["maximum"] = datetime.fromtimestamp(pinned_serialized["maximum_epoch"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
pinned_serialized["end"] = datetime.fromtimestamp(pinned_serialized["end_epoch"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
with patch.object(mission_planner, "get_candidates", return_value=[raw]), \
     patch.object(mission_queue.receiver_manager, "get_status", return_value={"reservations": {}}), \
     patch.object(mission_queue, "get_assignment", return_value="sdr1"), \
     patch.object(mission_queue, "_load_state", return_value={"overrides": {}}), \
     patch.object(mission_queue, "_save_state", return_value=None):
    queue = mission_queue.get_queue(
        limit=10,
        hours_ahead=48,
        active_pass_key=mission_queue.get_pass_key(pinned_serialized),
        pinned_pass=pinned_serialized,
    )
check(len(queue) == 1, "pinned execution contract replaces recalculated orbit duplicate")
check(queue[0]["queue_key"] == mission_queue.get_pass_key(pinned_serialized), "Planner, Queue and execution share one pass key")
check(queue[0]["status"] == "IN PROGRESS", "active pinned mission remains visible in Mission Queue")
check(queue[0]["tle_sha256"] == "fixture-hash", "selected mission retains immutable TLE fingerprint")

with patch.object(mission_queue, "get_queue", return_value=[]), \
     patch.object(mission_planner, "get_sources", return_value=[]), \
     patch.object(mission_planner, "get_policy", return_value={"minimum_elevation": 40.0, "profiles": {}}), \
     patch.object(tle, "get_status", return_value={"state": "CURRENT"}):
    queue_payload = mission_queue.get_payload()
check(queue_payload["planner_version"] == mission_planner.VERSION, "Mission Queue reports the active Planner version")

target = deepcopy(pinned_serialized)
target["start_epoch"] = 2_000_000_000
target["maximum_epoch"] = target["start_epoch"] + 120
target["end_epoch"] = target["start_epoch"] + 300
with patch.object(satdump, "check_recording_allowed", return_value=(True, "OK")), \
     patch.object(satdump, "get_assigned_device", return_value={"id": "sdr1", "number": "SDR1", "serial": "05419737", "name": "SDR1"}), \
     patch.object(satdump.config_core, "get_weather_rf_config", return_value={
         "lna_agc": True, "gain_mode": "auto", "gain_db": 0,
         "dc_block": True, "iq_swap": False, "fill_missing": True, "rs_usecheck": True,
     }):
    record = satdump.build_record_command(target)
    check(record["timeout_seconds"] == 300, "SatDump timeout equals planned pass window without hidden extension")
    satdump.align_timeout_to_pass_end(record, now_epoch=target["start_epoch"] + 11)
    check(record["timeout_seconds"] == 289, "late SatDump launch still stops at planned falling edge")

planner_source = inspect.getsource(mission_planner)
passes_source = inspect.getsource(passes)
downloader_source = (ROOT / "core/downloader.py").read_text(encoding="utf-8")
app_source = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
planner_js = (ROOT / "dashboard/static/js/mission_planner.js").read_text(encoding="utf-8")
mission_js = (ROOT / "dashboard/static/js/mission.js").read_text(encoding="utf-8")
html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
check("systemctl" not in planner_source + passes_source, "planning layer contains no service-control authority")
check("GROUP=weather" not in downloader_source, "TLE downloader requests only the three required catalogs")
check("tle.parse_text" in downloader_source and "_replace_transaction" in downloader_source, "TLE update validates before atomic replacement")
check("pinned_pass=target or None" in app_source, "Dashboard API preserves selected pass contract")
check("profiles" in planner_js and "begin_elevation" in planner_js and "close_elevation" in planner_js, "Mission Planner edits all per-satellite window values")
check("Remaining" in mission_js and "ACTIVE PASS" in mission_js, "receiver cards retain active pass and remaining time")
check('data-action="update_tle"' not in html and "Refresh TLE &amp; planning" in html, "TLE control moved from System to Mission Planner")

print("\nv0.54.0d Pass Window Correctness validation PASS")
