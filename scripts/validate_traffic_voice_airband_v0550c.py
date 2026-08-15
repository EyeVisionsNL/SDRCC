#!/usr/bin/env python3
"""Validate SDRCC v0.55.0c Airband execution and atomic mode switching."""

from __future__ import annotations

import ast
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
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
    def __init__(self, states):
        self.states = dict(states)
        self.actions = []
        self.fail_next_voice_start = False

    def state(self, service):
        active = bool(self.states.get(service, False))
        return {
            "service": service,
            "active": active,
            "state": "active" if active else "inactive",
        }

    def action(self, action, service):
        self.actions.append((action, service))
        if action == "start" and service == "sdrcc-traffic-voice.service" and self.fail_next_voice_start:
            self.fail_next_voice_start = False
            return SimpleNamespace(returncode=1, stdout="", stderr="forced switch failure")
        self.states[service] = action == "start"
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def wait(self, service, expected, timeout):
        del timeout
        return bool(self.states.get(service, False)) == (expected == "active")


def static_validation():
    required = [
        "config/traffic_voice.yaml",
        "core/traffic_voice.py",
        "core/traffic_voice_controller.py",
        "dashboard/app.py",
        "dashboard/templates/index.html",
        "dashboard/static/js/traffic_voice.js",
        "docs/traffic-voice-airband-v0550c.md",
    ]
    for relative in required:
        check((ROOT / relative).is_file(), f"required file present: {relative}")

    check((ROOT / "VERSION").read_text(encoding="utf-8").strip() == "0.55.0e", "release version is 0.55.0e")
    controller_path = ROOT / "core/traffic_voice_controller.py"
    tree = ast.parse(controller_path.read_text(encoding="utf-8"), filename=str(controller_path))
    imports = {
        alias.name
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    check("subprocess" not in imports, "controller has no subprocess authority")
    check("run_systemctl" not in calls, "controller uses injected service authority")
    check(not {"reserve", "begin_handover", "open_device"}.intersection(calls), "controller creates no competing receiver or SDR ownership")

    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    application = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    check('id="traffic-voice-start-airband"' in html, "Airband start control present")
    check("Switch to Airband + ADS-B" in javascript, "direct mode-switch label present")
    check('"start_airband"' in application and "start_airband" in javascript, "bounded Airband action is wired")
    check("PLANNED" not in html[html.index('data-traffic-mode="airband_adsb"'):html.index('data-traffic-mode="airband_adsb"') + 1000], "Airband card is no longer planned")
    return required


def configuration_and_render_validation():
    from core import config, traffic_voice

    raw = config.load_traffic_voice()
    validation = traffic_voice.validate_configuration(raw)
    check(validation["ok"], "dual-mode Traffic Voice configuration validates")
    settings = raw["traffic_voice"]
    marine = settings["modes"]["marine_ais"]
    airband = settings["modes"]["airband_adsb"]
    check(marine["execution_enabled"] and airband["execution_enabled"], "Marine and Airband execution are explicitly enabled")
    check(len(airband["channels"]) == 13, "all 13 Airband favourites are preserved")
    check(settings["backend"]["audio_sample_rate_hz"] == 16000, "shared AM/NFM audio bridge remains 16 kHz")

    assignments = config.get_receiver_assignments()
    airband_payload = deepcopy(raw)
    airband_payload["traffic_voice"]["selected_mode"] = "airband_adsb"
    airband_payload["traffic_voice"]["modes"]["airband_adsb"]["tuning_mode"] = "scan"
    airband_payload["traffic_voice"]["backend"]["open_squelch"] = False
    airband_assignments = {
        **assignments,
        "adsb": "sdr2",
        "traffic_voice": "sdr1",
    }
    with (
        patch.object(config, "load_traffic_voice", return_value=airband_payload),
        patch.object(config, "get_receiver_assignments", return_value=airband_assignments),
    ):
        rendered = traffic_voice.render_rtlsdr_airband_config()
    check('serial = "05419737";' in rendered, "Airband voice uses the receiver opposite ADS-B")
    check('modulation = "am";' in rendered, "Airband backend renders AM modulation")
    check('freqs = ( 139.100000' in rendered and "121.500000" in rendered, "Airband scan renders the complete favourite bank")
    check("118.200000" in rendered and "122.991667" in rendered, "8.33 kHz channel carriers reach the SDR backend")
    check('type = "udp_stream";' in rendered, "Airband reuses the existing localhost audio transport")

    swapped_assignments = {
        **assignments,
        "adsb": "sdr1",
        "traffic_voice": "sdr2",
    }
    with (
        patch.object(config, "load_traffic_voice", return_value=airband_payload),
        patch.object(config, "get_receiver_assignments", return_value=swapped_assignments),
    ):
        swapped = traffic_voice.render_rtlsdr_airband_config()
    check('serial = "24006572";' in swapped, "Airband receiver follows a swapped ADS-B assignment dynamically")

    stopped_snapshot_assignments = {**airband_assignments, "traffic_voice": "sdr2"}
    with (
        patch.object(config, "load_traffic_voice", return_value=airband_payload),
        patch.object(config, "get_receiver_assignments", return_value=stopped_snapshot_assignments),
    ):
        stopped_snapshot = traffic_voice.get_snapshot(
            service_reader=lambda service: {"service": service, "active": False, "state": "inactive"},
            audio_reader=lambda: {"ok": True, "available": False, "stream_state": "WAITING"},
        )
        running_snapshot = traffic_voice.get_snapshot(
            service_reader=lambda service: {"service": service, "active": True, "state": "active"},
            audio_reader=lambda: {"ok": True, "available": False, "stream_state": "WAITING"},
        )
    check(stopped_snapshot["ok"], "stopped Voice may defer its selected-mode assignment until Start")
    check(not running_snapshot["ok"], "running Voice fails closed on an assignment-policy mismatch")

    return raw, assignments


def transaction_validation(raw, assignments):
    from core import config, traffic_voice, traffic_voice_controller

    initial_states = {
        traffic_voice_controller.VOICE_SERVICE: False,
        traffic_voice_controller.AIS_SERVICE: True,
        traffic_voice_controller.ADSB_SERVICE: True,
    }
    ready_mission = {"active_job": None, "phase": "READY"}
    free_manager = {"canonical_reservations": {}}

    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-airband-") as directory:
        config_path = Path(directory) / "traffic_voice.yaml"
        config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        session_file = Path(directory) / "traffic_voice_session.json"
        stored = dict(assignments)

        def read_assignments():
            return dict(stored)

        def write_assignments(changes):
            stored.update(changes)
            return dict(stored)

        services = FakeServices(initial_states)
        with (
            patch.object(config, "TRAFFIC_VOICE_CONFIG", config_path),
            patch.object(config, "get_receiver_assignments", side_effect=read_assignments),
            patch.object(config, "set_plugin_assignments", side_effect=write_assignments),
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            marine = traffic_voice_controller.start_marine(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(marine["ok"] and services.states[traffic_voice_controller.VOICE_SERVICE], "Marine starts before the direct switch")
            check(services.states[traffic_voice_controller.AIS_SERVICE] and not services.states[traffic_voice_controller.ADSB_SERVICE], "Marine topology is active")

            switched = traffic_voice_controller.start_airband(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            session = json.loads(session_file.read_text(encoding="utf-8"))
            selected = config.load_traffic_voice()["traffic_voice"]["selected_mode"]
            check(switched["ok"] and switched["mode_switched"], "Marine switches directly to Airband")
            check(selected == "airband_adsb" and session["mode"] == "airband_adsb", "selected mode and durable session move to Airband")
            check(not services.states[traffic_voice_controller.AIS_SERVICE] and services.states[traffic_voice_controller.ADSB_SERVICE], "Airband keeps ADS-B and stops AIS")
            check(stored["traffic_voice"] == "sdr1", "Airband Voice assignment moves opposite ADS-B")
            check(session["previous_services"][traffic_voice_controller.AIS_SERVICE]["active"], "switch retains the original AIS baseline")
            check(session["previous_services"][traffic_voice_controller.ADSB_SERVICE]["active"], "switch retains the original ADS-B baseline")

            before_marine_channel = config.load_traffic_voice()["traffic_voice"]["modes"]["marine_ais"]["selected_channel_id"]
            air_settings = traffic_voice.save_receiver_settings({
                "tuning_mode": "fixed",
                "selected_channel_id": "rtm_tower",
            })
            after_document = config.load_traffic_voice()
            check(air_settings["mode_id"] == "airband_adsb" and air_settings["selected_channel_id"] == "rtm_tower", "receiver controls follow the selected Airband mode")
            check(after_document["traffic_voice"]["modes"]["marine_ais"]["selected_channel_id"] == before_marine_channel, "Airband controls do not overwrite Marine channel settings")

            stopped = traffic_voice_controller.stop(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(stopped["previous_state_restored"] and not session_file.exists(), "Stop completes and clears the durable switch session")
            check(services.states == initial_states, "Stop after a mode switch restores the exact pre-start services")
            check(stored["traffic_voice"] == assignments.get("traffic_voice"), "Stop restores the exact pre-start Voice assignment")

            direct = traffic_voice_controller.start_airband(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(direct["ok"] and services.states[traffic_voice_controller.VOICE_SERVICE], "Airband also starts directly from stopped Voice")
            check(not services.states[traffic_voice_controller.AIS_SERVICE] and services.states[traffic_voice_controller.ADSB_SERVICE], "direct Airband start applies the ADS-B topology")
            traffic_voice_controller.stop(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(services.states == initial_states, "Stop after direct Airband restores the exact pre-start services")

        expected_switch_actions = [
            ("stop", traffic_voice_controller.VOICE_SERVICE),
            ("stop", traffic_voice_controller.AIS_SERVICE),
            ("start", traffic_voice_controller.ADSB_SERVICE),
            ("start", traffic_voice_controller.VOICE_SERVICE),
        ]
        check(
            all(action in services.actions for action in expected_switch_actions),
            "Airband switch uses the bounded stop-context-start order",
        )


def failed_switch_validation(raw, assignments):
    from core import config, traffic_voice_controller

    ready_mission = {"active_job": None, "phase": "READY"}
    free_manager = {"canonical_reservations": {}}
    initial_states = {
        traffic_voice_controller.VOICE_SERVICE: False,
        traffic_voice_controller.AIS_SERVICE: True,
        traffic_voice_controller.ADSB_SERVICE: True,
    }
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-airband-fail-") as directory:
        config_path = Path(directory) / "traffic_voice.yaml"
        config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        session_file = Path(directory) / "traffic_voice_session.json"
        stored = dict(assignments)

        def write_assignments(changes):
            stored.update(changes)
            return dict(stored)

        services = FakeServices(initial_states)
        with (
            patch.object(config, "TRAFFIC_VOICE_CONFIG", config_path),
            patch.object(config, "get_receiver_assignments", side_effect=lambda: dict(stored)),
            patch.object(config, "set_plugin_assignments", side_effect=write_assignments),
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            traffic_voice_controller.start_marine(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            services.fail_next_voice_start = True
            try:
                traffic_voice_controller.start_airband(
                    service_state=services.state,
                    service_action=services.action,
                    wait_for_service=services.wait,
                )
            except RuntimeError:
                failed = True
            else:
                failed = False
            session = json.loads(session_file.read_text(encoding="utf-8"))
            selected = config.load_traffic_voice()["traffic_voice"]["selected_mode"]
            check(failed, "failed Airband Voice start fails the switch transaction")
            check(selected == "marine_ais" and session["mode"] == "marine_ais", "failed switch restores the preceding selected mode and session")
            check(services.states[traffic_voice_controller.VOICE_SERVICE], "failed switch restores the preceding active Voice service")
            check(services.states[traffic_voice_controller.AIS_SERVICE] and not services.states[traffic_voice_controller.ADSB_SERVICE], "failed switch restores the Marine traffic topology")
            check(stored["traffic_voice"] == assignments.get("traffic_voice"), "failed switch restores the Marine Voice assignment")

            traffic_voice_controller.stop(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(services.states == initial_states, "Stop still restores the original baseline after a failed switch")


def main():
    try:
        static = static_validation()
        raw, assignments = configuration_and_render_validation()
        transaction_validation(raw, assignments)
        failed_switch_validation(raw, assignments)
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASS: SDRCC v0.55.0e Airband Voice regression")
    print(json.dumps({
        "static": static,
        "modes": ["marine_ais", "airband_adsb"],
        "audio_sample_rate_hz": 16000,
        "receiver_authority": "receiver_manager",
        "service_authority": "existing_dashboard_systemctl_path",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
