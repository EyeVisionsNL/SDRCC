#!/usr/bin/env python3
"""Validate SDRCC v0.55.0b Marine Voice execution and rollback contracts."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
import json
import os
import struct
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(os.environ.get("SDRCC_ROOT") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT))


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


class FakeServices:
    def __init__(self, states, fail=()):
        self.states = dict(states)
        self.fail = set(fail)
        self.actions = []

    def state(self, service):
        active = bool(self.states.get(service, False))
        return {"service": service, "active": active, "state": "active" if active else "inactive"}

    def action(self, action, service):
        self.actions.append((action, service))
        failed = (action, service) in self.fail
        if not failed:
            self.states[service] = action == "start"
        return SimpleNamespace(returncode=1 if failed else 0, stderr="forced failure" if failed else "")

    def wait(self, service, expected, timeout):
        del timeout
        return bool(self.states.get(service, False)) == (expected == "active")


def static_validation():
    required = [
        "config/traffic_voice.yaml",
        "core/traffic_voice.py",
        "core/traffic_voice_audio.py",
        "core/traffic_voice_controller.py",
        "scripts/traffic_voice_prepare.py",
        "systemd/sdrcc-traffic-voice.service.in",
        "dashboard/static/css/traffic_voice.css",
        "dashboard/static/js/traffic_voice.js",
        "docs/traffic-voice-marine-v0550b.md",
    ]
    for relative in required:
        check((ROOT / relative).is_file(), f"required file present: {relative}")

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

    app = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    check('@app.route("/api/traffic-voice/action", methods=["POST"])' in app, "bounded Marine action endpoint present")
    check("service_action=run_systemctl" in app, "action injects existing dashboard systemctl path")
    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    check('id="traffic-voice-start"' in html and 'id="traffic-voice-stop"' in html, "Marine Start and Voice Stop controls present")
    check("Airband Voice + ADS-B" in html, "Airband card coexists with Marine controls")
    return required


def runtime_validation():
    from core import config, device_manager, execution_factory, plugin_manager, plugin_registry
    from core import receiver_manager, receiver_registry, traffic_voice, traffic_voice_audio, traffic_voice_controller

    validation = traffic_voice.validate_configuration()
    check(validation["ok"], "Marine Voice configuration validates")
    plugin = plugin_registry.get_plugin("traffic_voice")
    check(plugin["status"] == "active" and plugin["executor"] == "service", "Traffic Voice is an active service plugin")
    check(plugin["handover_services"] == ["sdrcc-traffic-voice.service"], "voice service participates in Receiver Manager handover")
    check(len(plugin_registry.get_plugins(include_planned=False)) == 5, "five active plugins and one planned plugin")

    plan = execution_factory.build_plan("traffic_voice")
    check(plan["targets"] == ["sdrcc-traffic-voice.service"], "execution plan delegates the registered voice service")
    manager = plugin_manager.get_plugin("traffic_voice")
    check(manager["control"]["endpoint"] == "/api/traffic-voice/action", "Plugin Manager points to bounded Traffic Voice endpoint")
    check(manager["control"]["actions"] == ["start", "stop"], "Traffic Voice exposes only Start and Stop")

    # This validator exercises the Marine renderer in isolation. Voice may be
    # stopped with Airband selected, in which case assignment reconciliation is
    # intentionally deferred until Start. That valid stopped state must not make
    # the Marine regression test fail the installer.
    runtime_payload = config.load_traffic_voice()
    marine_payload = json.loads(json.dumps(runtime_payload))
    marine_payload["traffic_voice"]["selected_mode"] = "marine_ais"
    assignments = config.get_receiver_assignments()
    marine_context = receiver_registry.resolve_id(assignments.get("ais"))
    marine_candidates = [
        receiver["id"] for receiver in receiver_registry.get_receivers()
        if receiver["id"] != marine_context
    ]
    check(len(marine_candidates) == 1, "Marine validation resolves one opposite receiver")
    marine_assignments = {**assignments, "traffic_voice": marine_candidates[0]}
    with (
        patch.object(config, "load_traffic_voice", return_value=marine_payload),
        patch.object(config, "get_receiver_assignments", return_value=marine_assignments),
    ):
        rendered = traffic_voice.render_rtlsdr_airband_config()
    check('serial = "24006572";' in rendered, "current opposite receiver serial is rendered")
    check("index =" not in rendered, "backend never selects a dongle by unstable index")
    check('modulation = "nfm";' in rendered and 'type = "udp_stream";' in rendered, "NFM and localhost audio backend rendered")
    check('modulation = "nfm";' in rendered and "freqs = (" in rendered, "selected Marine channel configuration rendered")

    swapped = {**assignments, "ais": "sdr2", "adsb": "sdr1", "traffic_voice": "sdr1"}
    with (
        patch.object(config, "load_traffic_voice", return_value=marine_payload),
        patch.object(config, "get_receiver_assignments", return_value=swapped),
    ):
        swapped_rendered = traffic_voice.render_rtlsdr_airband_config()
    check('serial = "05419737";' in swapped_rendered, "voice serial follows a swapped AIS assignment dynamically")

    metrics = "\n".join((
        'channel_dbfs_signal_level{freq="156.550",label="CH11 Traffic"} -31.0',
        'channel_dbfs_noise_level{freq="156.550",label="CH11 Traffic"} -48.5',
        'channel_activity_counter{freq="156.550",label="CH11 Traffic"} 42',
        'channel_squelch_counter{freq="156.550",label="CH11 Traffic"} 7',
    ))
    parsed = traffic_voice.parse_statistics(metrics)
    check(len(parsed) == 1 and parsed[0]["snr_db"] == 17.5, "Prometheus channel signal/noise derives SNR")
    check(parsed[0]["frequency_hz"] == 156550000, "upstream MHz metric label normalizes to hertz")
    check(parsed[0]["possible_active"] is True, "activity is explicitly labelled possible, not certain")

    pcm = traffic_voice_audio.float32_to_pcm16(struct.pack("<ffff", -1.5, -0.5, 0.5, 1.5))
    check(struct.unpack("<hhhh", pcm) == (-32767, -16384, 16384, 32767), "float32 localhost audio clamps to PCM16")

    # Controller transactions are intentionally stateful. Run every Marine
    # transaction below against a disposable config authority so the validator
    # can never change the operator's selected mode or receiver settings.
    production_config_path = Path(config.TRAFFIC_VOICE_CONFIG)
    production_config_bytes = production_config_path.read_bytes()
    config_sandbox = tempfile.TemporaryDirectory(prefix="sdrcc-tv-config-")
    sandbox_config_path = Path(config_sandbox.name) / "traffic_voice.yaml"
    sandbox_config_path.write_bytes(production_config_bytes)
    config_path_patch = patch.object(config, "TRAFFIC_VOICE_CONFIG", sandbox_config_path)
    config_path_patch.start()

    base_states = {
        traffic_voice_controller.VOICE_SERVICE: False,
        traffic_voice_controller.AIS_SERVICE: True,
        traffic_voice_controller.ADSB_SERVICE: True,
    }
    services = FakeServices(base_states)
    stored = dict(assignments)

    def write(changes):
        stored.update(changes)
        return dict(stored)

    ready_mission = {"active_job": None, "phase": "READY"}
    free_manager = {"canonical_reservations": {}}
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-session-") as directory:
        session_file = Path(directory) / "traffic_voice_session.json"
        with (
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(config, "get_receiver_assignments", side_effect=lambda: dict(stored)),
            patch.object(config, "set_plugin_assignments", side_effect=write),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            result = traffic_voice_controller.start_marine(
                service_state=services.state, service_action=services.action, wait_for_service=services.wait,
            )
            check(session_file.is_file(), "Marine start persists the preceding service topology")
            check(result["ok"] and services.states[traffic_voice_controller.VOICE_SERVICE], "normal Marine transaction starts voice")
            check(not services.states[traffic_voice_controller.ADSB_SERVICE] and services.states[traffic_voice_controller.AIS_SERVICE], "Marine transaction keeps AIS and stops ADS-B")
            stopped = traffic_voice_controller.stop(
                service_state=services.state,
                service_action=services.action,
                wait_for_service=services.wait,
            )
            check(not session_file.exists(), "successful Stop clears the completed topology session")
    check(stopped["ok"] and not services.states[traffic_voice_controller.VOICE_SERVICE], "Stop stops the voice service")
    check(services.states[traffic_voice_controller.ADSB_SERVICE] and services.states[traffic_voice_controller.AIS_SERVICE], "Stop restores previously active ADS-B and preserves prior AIS state")
    check(stopped["previous_state_restored"], "Stop reports exact previous-state restoration")

    inactive_services = FakeServices({
        traffic_voice_controller.VOICE_SERVICE: False,
        traffic_voice_controller.AIS_SERVICE: False,
        traffic_voice_controller.ADSB_SERVICE: False,
    })
    stored.clear()
    stored.update(assignments)
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-inactive-") as directory:
        session_file = Path(directory) / "traffic_voice_session.json"
        with (
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(config, "get_receiver_assignments", side_effect=lambda: dict(stored)),
            patch.object(config, "set_plugin_assignments", side_effect=write),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            traffic_voice_controller.start_marine(
                service_state=inactive_services.state,
                service_action=inactive_services.action,
                wait_for_service=inactive_services.wait,
            )
            inactive_stopped = traffic_voice_controller.stop(
                service_state=inactive_services.state,
                service_action=inactive_services.action,
                wait_for_service=inactive_services.wait,
            )
    check(inactive_stopped["ok"], "Stop succeeds when AIS and ADS-B were initially inactive")
    check(not inactive_services.states[traffic_voice_controller.AIS_SERVICE] and not inactive_services.states[traffic_voice_controller.ADSB_SERVICE], "Stop does not start services that were inactive before Marine Voice")

    stored.clear()
    stored.update({**assignments, "traffic_voice": "sdr1"})
    failed = FakeServices(base_states, fail={("start", traffic_voice_controller.VOICE_SERVICE)})
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-failed-start-") as directory:
        session_file = Path(directory) / "traffic_voice_session.json"
        with (
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(config, "get_receiver_assignments", side_effect=lambda: dict(stored)),
            patch.object(config, "set_plugin_assignments", side_effect=write),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            try:
                traffic_voice_controller.start_marine(
                    service_state=failed.state, service_action=failed.action, wait_for_service=failed.wait,
                )
            except RuntimeError:
                rolled_back = True
            else:
                rolled_back = False
            failed_session_cleared = not session_file.exists()
    check(rolled_back, "failed voice start fails the transaction")
    check(stored["traffic_voice"] == "sdr1" and failed.states[traffic_voice_controller.ADSB_SERVICE], "failed transaction restores assignment and ADS-B state")
    check(not failed.states[traffic_voice_controller.VOICE_SERVICE], "failed transaction does not strand voice active")
    check(failed_session_cleared, "successful failed-start rollback clears its topology session")

    restore_failure = FakeServices(base_states, fail={("start", traffic_voice_controller.ADSB_SERVICE)})
    stored.clear()
    stored.update(assignments)
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-restore-retry-") as directory:
        session_file = Path(directory) / "traffic_voice_session.json"
        with (
            patch.object(traffic_voice_controller, "SESSION_FILE", session_file),
            patch.object(config, "get_receiver_assignments", side_effect=lambda: dict(stored)),
            patch.object(config, "set_plugin_assignments", side_effect=write),
            patch.object(traffic_voice_controller.mission_engine, "get_mission_status", return_value=ready_mission),
            patch.object(traffic_voice_controller.receiver_manager, "get_status", return_value=free_manager),
            patch.object(traffic_voice_controller.receiver_manager, "service_action_block", return_value=None),
        ):
            traffic_voice_controller.start_marine(
                service_state=restore_failure.state,
                service_action=restore_failure.action,
                wait_for_service=restore_failure.wait,
            )
            try:
                traffic_voice_controller.stop(
                    service_state=restore_failure.state,
                    service_action=restore_failure.action,
                    wait_for_service=restore_failure.wait,
                )
            except RuntimeError:
                restore_failed = True
            else:
                restore_failed = False
            retained_for_retry = session_file.is_file()
            restore_failure.fail.clear()
            retried = traffic_voice_controller.stop(
                service_state=restore_failure.state,
                service_action=restore_failure.action,
                wait_for_service=restore_failure.wait,
            )
            cleared_after_retry = not session_file.exists()
    check(restore_failed and retained_for_retry, "failed ADS-B restore retains durable state for retry")
    check(retried["ok"] and restore_failure.states[traffic_voice_controller.ADSB_SERVICE], "retry restores previously active ADS-B")
    check(cleared_after_retry, "successful restore retry clears durable state")

    blocked_services = FakeServices({
        traffic_voice_controller.VOICE_SERVICE: False,
        traffic_voice_controller.AIS_SERVICE: False,
        traffic_voice_controller.ADSB_SERVICE: False,
    })
    with patch.object(
        traffic_voice_controller.receiver_manager,
        "get_status",
        return_value={"canonical_reservations": {
            "receiver02": {"mission_key": "test:mission"},
        }},
    ):
        try:
            traffic_voice_controller.stop(
                service_state=blocked_services.state,
                service_action=blocked_services.action,
                wait_for_service=blocked_services.wait,
            )
        except RuntimeError:
            stop_blocked = True
        else:
            stop_blocked = False
    check(stop_blocked, "Stop cannot override an active Receiver Manager handover restore intent")

    conflicts = device_manager.get_conflicting_services("sdr2")
    check("sdrcc-traffic-voice.service" in conflicts, "Receiver Runtime conflict discovery includes Traffic Voice")

    old_state = receiver_manager.STATE_FILE
    old_publish = receiver_manager.event_bus.publish_receiver
    with tempfile.TemporaryDirectory(prefix="sdrcc-tv-handover-") as directory:
        receiver_manager.STATE_FILE = Path(directory) / "receiver_manager.json"
        receiver_manager.event_bus.publish_receiver = lambda *args, **kwargs: None
        handover_services = FakeServices({
            "readsb.service": False,
            "sdrcc-traffic-voice.service": True,
        })
        try:
            receiver_manager.begin_handover(
                "sdr2",
                mission_key="test:traffic-voice",
                services=conflicts,
                service_state=handover_services.state,
                service_action=handover_services.action,
                wait_for_service=handover_services.wait,
                release_delay_seconds=0,
            )
            restored = receiver_manager.restore_handover(
                mission_key="test:traffic-voice",
                service_state=handover_services.state,
                service_action=handover_services.action,
                wait_for_service=handover_services.wait,
            )
        finally:
            receiver_manager.STATE_FILE = old_state
            receiver_manager.event_bus.publish_receiver = old_publish
    check(restored["ok"], "existing Receiver Manager restores the voice handover")
    check(handover_services.actions == [
        ("stop", "sdrcc-traffic-voice.service"),
        ("start", "sdrcc-traffic-voice.service"),
    ], "handover leaves inactive ADS-B untouched and restores only prior active voice")

    config_path_patch.stop()
    config_sandbox.cleanup()
    check(
        production_config_path.read_bytes() == production_config_bytes,
        "Marine validation preserves the operator's Traffic Voice configuration",
    )

    return {
        "version": traffic_voice.VERSION,
        "backend_target": plan["targets"][0],
        "current_voice_serial": "24006572",
        "swapped_voice_serial": "05419737",
        "normal_actions": services.actions,
        "rollback_actions": failed.actions,
        "handover_actions": handover_services.actions,
    }


def main():
    try:
        static = static_validation()
        runtime = runtime_validation()
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASS: SDRCC v0.55.0b Marine Voice")
    print(json.dumps({"static": static, "runtime": runtime}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
