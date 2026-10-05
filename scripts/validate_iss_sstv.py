#!/usr/bin/env python3
"""Validate ISS SSTV event planning, pinned decoder and unchanged voice RF profile."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import importlib
import importlib.metadata
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sstv
from PIL import Image
from core import iss_sstv, iss_voice, mission_planner, mission_recordings


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


check(importlib.metadata.version("sstv") == iss_sstv.DECODER_VERSION, "pinned sstv decoder version is installed")
check(iss_sstv.decoder_status("robot36")["available"], "Robot 36 decoder is ready")
check(iss_sstv.decoder_status("pd120")["available"], "PD120 decoder is ready")

voice = iss_voice.validate_config()
check(voice["ok"], "existing ISS Voice config still validates")
check(int(voice["config"]["downlink_frequency_hz"]) == 437800000, "ISS Voice stays at 437.800 MHz")
check(iss_voice.capture_gain_db(voice["config"]) == 20.7, "ISS Voice keeps the configured manual gain")
check(voice["config"]["squelch_enabled"] is False, "ISS Voice squelch is not changed by SSTV")

requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
prepare_audio = (ROOT / "scripts/install/prepare_audio_comparison.sh").read_text(encoding="utf-8")
check("sstv==0.1.0" in requirements, "fresh installs pin the tested SSTV decoder")
check("prepare_iss_sstv_decoder.sh" in prepare_audio, "managed updates run the SSTV decoder setup helper")

event = {
    **iss_sstv.DEFAULT_EVENT,
    "enabled": True,
    "name": "Validator SSTV event",
    "start_utc": "2026-10-02T09:00:00Z",
    "end_utc": "2026-10-06T15:55:00Z",
    "frequency_hz": 437550000,
    "mode": "robot36",
}
start = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
pass_inside = {
    "name": "ISS (ZARYA)", "start": start,
    "maximum": start.replace(minute=2), "end": start.replace(minute=4),
    "max_elevation": 70.0, "frequency": 437800000,
    "planning_profile_id": "iss_voice", "duration_seconds": 240,
}
outside_start = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
pass_outside = {
    **pass_inside,
    "start": outside_start,
    "maximum": outside_start.replace(minute=2),
    "end": outside_start.replace(minute=4),
}
voice_config = {
    "enabled": True, "planner_enabled": True, "execution_enabled": True,
    "execution_backend_enabled": True, "receiver_claim_enabled": True,
    "planning_priority": 3, "mission_type": "iss_voice",
    "downlink_frequency_hz": 437800000, "modulation": "NFM",
}
with (
    patch.object(mission_planner, "_iss_config", return_value=voice_config),
    patch.object(mission_planner.iss_passes, "get_passes", return_value=[pass_inside, pass_outside]),
    patch.object(mission_planner.iss_sstv, "get_settings", return_value=event),
    patch.object(mission_planner.iss_sstv, "decoder_status", return_value={"available": True}),
):
    candidates = mission_planner._iss_candidates(48)
    check(len(candidates) == 2, "ISS provider returns both event and ordinary passes")
    sstv_pass = next(item for item in candidates if item["mission_type"] == "iss_sstv")
    voice_pass = next(item for item in candidates if item["mission_type"] == "iss_voice")
    check(sstv_pass["frequency"] == 437550000, "event pass switches to the SSTV downlink")
    check(sstv_pass["receiver_role"] == "iss_voice", "SSTV uses the existing ISS receiver handover")
    check(voice_pass["frequency"] == 437800000, "voice pass outside the event keeps its existing frequency")
    check(sstv_pass["pipeline"] == "wideband_iq_offline_sstv", "event pass is routed to the SSTV decoder pipeline")

with TemporaryDirectory(prefix="sdrcc-iss-sstv-") as temporary:
    root = Path(temporary).resolve()
    previous_root = iss_sstv.RECORDINGS_ROOT
    previous_inventory_root = mission_recordings.ROOT
    try:
        iss_sstv.RECORDINGS_ROOT = root
        mission_recordings.ROOT = root
        wav = root / "robot36-test.wav"
        Image.new("RGB", (320, 240), (20, 100, 210)).save(root / "reference.png")
        sstv.encode_to_wav_file(Image.new("RGB", (320, 240), (20, 100, 210)), str(wav), sstv.Mode.ROBOT_36)
        decoded = iss_sstv.decode_wav(wav, mode="robot36", event=event)
        check(decoded["image_count"] == 1, "synthetic Robot 36 transmission decodes into one image")
        check(Path(decoded["images"][0]["path"]).is_file(), "decoded image is saved as a PNG")
        check((root / "sstv_decode.json").is_file(), "decoder result metadata is written")
        inventory = mission_recordings.inventory()
        check(
            any(row["kind"] == "image" and row["name"].endswith(".png") for row in inventory["recordings"]),
            "decoded PNG appears in the existing Mission Recordings inventory",
        )
    finally:
        iss_sstv.RECORDINGS_ROOT = previous_root
        mission_recordings.ROOT = previous_inventory_root

with TemporaryDirectory(prefix="sdrcc-iss-sstv-api-") as temporary:
    from core import update_manager, traffic_voice_denoise
    dashboard = importlib.import_module("dashboard.app")
    event_file = Path(temporary) / "iss_sstv_event.json"
    client = dashboard.app.test_client()
    with (
        patch.object(iss_sstv, "EVENT_FILE", event_file),
        patch.object(dashboard, "get_mission_data_for_status", return_value={"state": "READY", "phase": "READY"}),
        patch.object(dashboard.mission_scheduler_core, "get_scheduler_status", return_value={"observer": {"phase": "WAIT FOR PASS"}}),
    ):
        current = client.get("/api/iss-sstv/settings")
        check(current.status_code == 200 and current.json["settings"]["frequency_hz"] == 437550000, "SSTV settings endpoint returns the event preset")
        saved_event = {**event, "name": "Saved API event", "enabled": False}
        saved = client.post("/api/iss-sstv/settings", json=saved_event)
        check(saved.status_code == 200 and event_file.is_file(), "SSTV settings endpoint persists operator changes")
        blocked_settings = {**saved_event, "name": "Must not change during pass"}
        with patch.object(dashboard.mission_scheduler_core, "get_scheduler_status", return_value={"observer": {"phase": "PASS ACTIVE"}}):
            blocked = client.post("/api/iss-sstv/settings", json=blocked_settings)
        check(blocked.status_code == 409, "SSTV event settings are locked during an active pass")

    ready_audio = {"speex": {"available": True}, "rnnoise": {"available": True}}
    with (
        patch.object(traffic_voice_denoise, "capabilities", return_value=ready_audio),
        patch.object(iss_sstv, "decoder_status", return_value={"available": True}),
    ):
        check(not update_manager.audio_setup_required(), "Update Manager sees complete audio and SSTV setup")
    with (
        patch.object(traffic_voice_denoise, "capabilities", return_value=ready_audio),
        patch.object(iss_sstv, "decoder_status", return_value={"available": False}),
    ):
        check(update_manager.audio_setup_required(), "Update Manager offers setup completion when SSTV decoder is missing")

print("\nISS SSTV validation PASS")
