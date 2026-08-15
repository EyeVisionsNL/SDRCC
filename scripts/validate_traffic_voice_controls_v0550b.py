#!/usr/bin/env python3
"""Validate v0.55.0b-r3 channel banks and receiver controls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys
import tempfile
from unittest.mock import patch

import yaml


ROOT = Path(os.environ.get("SDRCC_ROOT") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT))


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


class FakeServices:
    def __init__(self, *, voice_active):
        self.states = {
            "sdrcc-traffic-voice.service": bool(voice_active),
            "ais-catcher.service": True,
            "readsb.service": False,
        }
        self.actions = []

    def state(self, service):
        active = bool(self.states.get(service, False))
        return {
            "service": service,
            "active": active,
            "state": "active" if active else "inactive",
        }

    def action(self, action, service):
        self.actions.append((action, service))
        self.states[service] = action == "start"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def wait(self, service, expected, timeout):
        del timeout
        return bool(self.states.get(service, False)) == (expected == "active")


def validate_static_ui():
    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    application = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    for control_id in (
        "traffic-voice-tuning-mode",
        "traffic-voice-channel-select",
        "traffic-voice-gain",
        "traffic-voice-squelch",
        "traffic-voice-apply-settings",
        "traffic-voice-open-squelch",
        "traffic-voice-audio-toggle",
    ):
        check(f'id="{control_id}"' in html, f"UI control present: {control_id}")
    check('id="traffic-voice-audio" preload="none"' in html, "native misleading streaming duration controls removed")
    check("selectFixedChannel" in javascript, "channel rows are clickable fixed-channel controls")
    check("apply_settings" in javascript and '"apply_settings"' in application, "bounded settings action is wired")
    check("config/traffic_voice.yaml" in application, "API reports the single settings authority")


def validate_banks_and_rendering():
    from core import config, traffic_voice

    raw = config.load_traffic_voice()
    validation = traffic_voice.validate_configuration(raw)
    check(validation["ok"], "expanded Traffic Voice configuration validates")
    settings = raw["traffic_voice"]
    check(
        settings.get("channel_source") == "RT-950PRO_CPS_ChannelListChirpData_laatste.csv",
        "uploaded CHIRP list is recorded as channel source",
    )
    marine = settings["modes"]["marine_ais"]
    airband = settings["modes"]["airband_adsb"]
    check(marine["channel_bank"] == "coen_rotterdam", "local Rotterdam bank selected")
    check(len(marine["channels"]) == 27, "all 27 local Marine favourites included")
    check(len({item["id"] for item in marine["channels"]}) == 27, "Marine channel IDs are unique")
    check(len({float(item["frequency_mhz"]) for item in marine["channels"]}) == 27, "Marine frequencies are unique")
    check({"V61_BOTLEK", "V60_WAALH", "VLAARDING", "ROEIERS", "BOLUDA"}.issubset(
        {item["label"] for item in marine["channels"]}
    ), "local port favourites are preserved")
    check(airband["channel_bank"] == "coen_zestienhoven", "Zestienhoven bank selected")
    check(len(airband["channels"]) == 13, "all 13 aviation favourites included")
    check(airband["execution_enabled"] is False, "Airband execution remains fail-closed")
    check({"MIL_TOWE", "MIL_TACT", "MIL_L-L"}.issubset(
        {item["label"] for item in airband["channels"]}
    ), "three military AM favourites are preserved")
    air_tuning = {
        round(float(item["channel_mhz"]), 3): round(float(item["frequency_mhz"]), 6)
        for item in airband["channels"]
    }
    check(air_tuning[118.205] == 118.2, "RTM Tower channel designator maps to SDR carrier")
    check(air_tuning[122.18] == 122.175, "RTM Delivery channel designator maps to SDR carrier")
    check(air_tuning[122.99] == 122.991667, "RTM Approach channel designator maps to SDR carrier")
    check(air_tuning[121.205] == 121.2, "Schiphol West channel designator maps to SDR carrier")

    rendered = traffic_voice.render_rtlsdr_airband_config()
    check(rendered.count("frequency_mhz") == 0, "backend receives rendered frequencies, not YAML field names")
    check('labels = ( "CH16_NOOD"' in rendered and '"BOLUDA"' in rendered, "scan render contains the full named Marine bank")
    check("squelch_snr_threshold = 6.0;" in rendered, "configured normal squelch is rendered")

    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-controls-") as directory:
        config_path = Path(directory) / "traffic_voice.yaml"
        config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        with patch.object(config, "TRAFFIC_VOICE_CONFIG", config_path):
            fixed = traffic_voice.save_receiver_settings({
                "tuning_mode": "fixed",
                "selected_channel_id": "vlaarding",
                "gain_db": 38.6,
                "squelch_snr_db": 8.5,
                "open_squelch": False,
            })
            fixed_render = traffic_voice.render_rtlsdr_airband_config()
            check(fixed["selected_channel_id"] == "vlaarding", "fixed channel persists through the single config authority")
            check('freqs = ( 157.000000 );' in fixed_render, "fixed-channel render contains only the selected channel")
            check("gain = 38.6;" in fixed_render and "squelch_snr_threshold = 8.5;" in fixed_render, "gain and squelch controls reach the backend render")

            opened = traffic_voice.save_receiver_settings({"open_squelch": True})
            open_render = traffic_voice.render_rtlsdr_airband_config()
            check(opened["open_squelch"], "open-squelch test state persists explicitly")
            check("squelch_snr_threshold = 0.0;" in open_render, "open squelch renders the backend-supported zero SNR threshold")

            try:
                traffic_voice.save_receiver_settings({"gain_db": 31.0})
            except ValueError:
                rejected_gain = True
            else:
                rejected_gain = False
            check(rejected_gain, "unsupported tuner gain fails closed")


def validate_settings_transaction():
    from core import config, traffic_voice, traffic_voice_controller

    original = config.load_traffic_voice()
    assignments = config.get_receiver_assignments()
    free_manager = {"canonical_reservations": {}}
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-transaction-") as directory:
        config_path = Path(directory) / "traffic_voice.yaml"
        config_path.write_text(yaml.safe_dump(original, sort_keys=False), encoding="utf-8")
        with (
            patch.object(config, "TRAFFIC_VOICE_CONFIG", config_path),
            patch.object(config, "get_receiver_assignments", return_value=assignments),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
        ):
            stopped = FakeServices(voice_active=False)
            stored = traffic_voice_controller.apply_receiver_settings(
                {"tuning_mode": "fixed", "selected_channel_id": "ch11_vts"},
                service_state=stopped.state,
                service_action=stopped.action,
                wait_for_service=stopped.wait,
            )
            check(stored["ok"] and not stopped.actions, "stopped Voice stores settings without touching services")

            running = FakeServices(voice_active=True)
            applied = traffic_voice_controller.apply_receiver_settings(
                {"gain_db": 42.1, "squelch_snr_db": 7.5},
                service_state=running.state,
                service_action=running.action,
                wait_for_service=running.wait,
            )
            check(applied["ok"] and running.actions == [
                ("stop", traffic_voice_controller.VOICE_SERVICE),
                ("start", traffic_voice_controller.VOICE_SERVICE),
            ], "running Voice restarts only its existing service")
            check(running.states[traffic_voice_controller.VOICE_SERVICE], "Voice returns active after settings apply")
            check(running.states[traffic_voice_controller.AIS_SERVICE] and not running.states[traffic_voice_controller.ADSB_SERVICE], "settings apply leaves AIS and ADS-B untouched")

            before_failure = deepcopy(config.load_traffic_voice())
            flaky = FakeServices(voice_active=True)
            start_attempts = 0

            def flaky_action(action, service):
                nonlocal start_attempts
                flaky.actions.append((action, service))
                if action == "start" and service == traffic_voice_controller.VOICE_SERVICE:
                    start_attempts += 1
                    if start_attempts == 1:
                        return SimpleNamespace(returncode=1, stdout="", stderr="forced first restart failure")
                flaky.states[service] = action == "start"
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            try:
                traffic_voice_controller.apply_receiver_settings(
                    {"gain_db": 49.6},
                    service_state=flaky.state,
                    service_action=flaky_action,
                    wait_for_service=flaky.wait,
                )
            except RuntimeError:
                failed = True
            else:
                failed = False
            check(failed, "failed Voice restart fails the settings transaction")
            check(config.load_traffic_voice() == before_failure, "failed settings transaction restores the exact YAML document")
            check(flaky.states[traffic_voice_controller.VOICE_SERVICE], "failed settings transaction restores prior active Voice")

            with patch.object(
                traffic_voice_controller.receiver_manager,
                "get_status",
                return_value={"canonical_reservations": {
                    "receiver02": {"mission_key": "test:handover"},
                }},
            ):
                try:
                    traffic_voice_controller.apply_receiver_settings(
                        {"squelch_snr_db": 5.0},
                        service_state=stopped.state,
                        service_action=stopped.action,
                        wait_for_service=stopped.wait,
                    )
                except RuntimeError:
                    blocked = True
                else:
                    blocked = False
            check(blocked, "Receiver Manager handover blocks live settings changes")


def main():
    try:
        validate_static_ui()
        validate_banks_and_rendering()
        validate_settings_transaction()
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASS: SDRCC v0.55.0b-r3 Traffic Voice controls")
    print(json.dumps({
        "marine_channels": 27,
        "airband_channels": 13,
        "settings_authority": "config/traffic_voice.yaml",
        "service_authority": "existing_dashboard_systemctl_path",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
