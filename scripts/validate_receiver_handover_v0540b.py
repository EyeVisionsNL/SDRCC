#!/usr/bin/env python3
"""Regression validation for SDRCC v0.54.0b Receiver Handover."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


class FakeServices:
    def __init__(self, states, *, fail_start=(), fail_stop=()):
        self.states = dict(states)
        self.fail_start = set(fail_start)
        self.fail_stop = set(fail_stop)
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
        failed = (
            action == "start" and service in self.fail_start
        ) or (
            action == "stop" and service in self.fail_stop
        )
        if not failed:
            self.states[service] = action == "start"
        return SimpleNamespace(
            returncode=1 if failed else 0,
            stderr="forced failure" if failed else "",
        )

    def wait(self, service, expected, timeout):
        del timeout
        return bool(self.states.get(service, False)) == (expected == "active")


def reservation(status, receiver="sdr1"):
    return (status.get("reservations") or {}).get(receiver) or {}


def run_behaviour_tests():
    from core import receiver_manager
    from core import state as receiver_state

    original_state_file = receiver_manager.STATE_FILE
    original_sdr2_file = receiver_state.SDR2_STATE_FILE
    original_publish = receiver_manager.event_bus.publish_receiver

    with tempfile.TemporaryDirectory(prefix="sdrcc-handover-") as directory:
        temporary = Path(directory)
        receiver_manager.STATE_FILE = temporary / "receiver_manager.json"
        receiver_state.SDR2_STATE_FILE = temporary / "sdr2.json"
        events = []
        receiver_manager.event_bus.publish_receiver = (
            lambda level, title, detail, data=None: events.append(
                {"level": level, "title": title, "detail": detail, "data": data}
            )
        )

        try:
            receiver_state.set_sdr2_state(
                status="idle", profile="manual", locked=False, process=None
            )
            ais = FakeServices({
                "ais-catcher-control.service": True,
                "ais-catcher.service": True,
            })
            status = receiver_manager.begin_handover(
                "sdr1",
                mission_key="test:ais-order",
                mission_id="mission-ais",
                reason="validator",
                services=[
                    "ais-catcher-control.service",
                    "ais-catcher.service",
                ],
                service_state=ais.state,
                service_action=ais.action,
                wait_for_service=ais.wait,
                previous_profile="manual",
                release_delay_seconds=0,
            )
            check(
                "AIS stop order is control then main",
                ais.actions == [
                    ("stop", "ais-catcher-control.service"),
                    ("stop", "ais-catcher.service"),
                ],
            )
            handover = reservation(status).get("handover") or {}
            check("handover intent persisted", handover.get("status") == "READY")
            check(
                "original service states persisted",
                all(item.get("was_active") for item in handover.get("services") or []),
            )

            receiver_manager.activate(
                mission_key="test:ais-order", mission_id="mission-ais"
            )
            block = receiver_manager.service_action_block("ais", "restart")
            check("AIS restart blocked while receiver reserved", bool(block))
            check(
                "AIS stop remains allowed while receiver reserved",
                receiver_manager.service_action_block("ais", "stop") is None,
            )

            restored = receiver_manager.restore_handover(
                mission_key="test:ais-order",
                service_state=ais.state,
                service_action=ais.action,
                wait_for_service=ais.wait,
                detail="validator restored",
            )
            check("AIS handover restored", restored.get("ok") is True)
            check(
                "AIS restore order is main then control",
                ais.actions[-2:] == [
                    ("start", "ais-catcher.service"),
                    ("start", "ais-catcher-control.service"),
                ],
            )
            check(
                "previous profile restored exactly",
                receiver_state.get_sdr2_state().get("profile") == "manual",
            )
            check(
                "receiver released only after successful restore",
                receiver_manager.is_available("sdr1"),
            )

            events.clear()
            receiver_manager.reserve(
                "sdr1", mission_key="test:idempotent", reason="validator"
            )
            receiver_manager.reserve(
                "sdr1", mission_key="test:idempotent", reason="validator"
            )
            reserve_events = [
                event for event in events if event["title"] == "Receiver gereserveerd"
            ]
            check("idempotent reserve emits one event", len(reserve_events) == 1)
            receiver_manager.release(
                mission_key="test:idempotent", detail="validator cleanup"
            )

            inactive = FakeServices({"readsb.service": False})
            receiver_manager.begin_handover(
                "sdr2",
                mission_key="test:inactive",
                services=["readsb.service"],
                service_state=inactive.state,
                service_action=inactive.action,
                wait_for_service=inactive.wait,
                release_delay_seconds=0,
            )
            receiver_manager.restore_handover(
                mission_key="test:inactive",
                service_state=inactive.state,
                service_action=inactive.action,
                wait_for_service=inactive.wait,
                detail="validator inactive",
            )
            check("inactive service is neither stopped nor started", inactive.actions == [])

            attention_runtime = FakeServices({"readsb.service": True})
            receiver_manager.begin_handover(
                "sdr2",
                mission_key="test:attention",
                services=["readsb.service"],
                service_state=attention_runtime.state,
                service_action=attention_runtime.action,
                wait_for_service=attention_runtime.wait,
                release_delay_seconds=0,
            )
            attention_runtime.fail_start.add("readsb.service")
            attention = receiver_manager.restore_handover(
                mission_key="test:attention",
                service_state=attention_runtime.state,
                service_action=attention_runtime.action,
                wait_for_service=attention_runtime.wait,
            )
            check("restore failure returns ATTENTION", attention.get("attention") is True)
            status = receiver_manager.get_status()
            check("ATTENTION reservation remains owned", not receiver_manager.is_available("sdr2"))
            check("manager exposes attention_required", status.get("attention_required") is True)
            try:
                receiver_manager.release(mission_key="test:attention")
            except RuntimeError:
                release_blocked = True
            else:
                release_blocked = False
            check("ATTENTION receiver cannot be released", release_blocked)

            attention_runtime.fail_start.clear()
            recovered = receiver_manager.recover_handovers(
                service_state=attention_runtime.state,
                service_action=attention_runtime.action,
                wait_for_service=attention_runtime.wait,
            )
            check("crash recovery retries unfinished handover", recovered.get("recovered") == 1)
            check("crash recovery releases restored receiver", receiver_manager.is_available("sdr2"))

            failed_stop = FakeServices(
                {"readsb.service": True}, fail_stop={"readsb.service"}
            )
            try:
                receiver_manager.begin_handover(
                    "sdr2",
                    mission_key="test:failed-stop",
                    services=["readsb.service"],
                    service_state=failed_stop.state,
                    service_action=failed_stop.action,
                    wait_for_service=failed_stop.wait,
                    release_delay_seconds=0,
                )
            except RuntimeError:
                preparation_failed = True
            else:
                preparation_failed = False
            check("failed service stop aborts handover", preparation_failed)
            check("failed stop does not strand receiver", receiver_manager.is_available("sdr2"))

            dependent = FakeServices({
                "ais-catcher-control.service": True,
                "ais-catcher.service": True,
            })
            receiver_manager.begin_handover(
                "sdr1",
                mission_key="test:dependent-restore",
                services=[
                    "ais-catcher-control.service",
                    "ais-catcher.service",
                ],
                service_state=dependent.state,
                service_action=dependent.action,
                wait_for_service=dependent.wait,
                release_delay_seconds=0,
            )
            dependent.fail_start.add("ais-catcher.service")
            dependent_result = receiver_manager.restore_handover(
                mission_key="test:dependent-restore",
                service_state=dependent.state,
                service_action=dependent.action,
                wait_for_service=dependent.wait,
            )
            check("failed AIS main restore requires attention", dependent_result.get("attention") is True)
            check(
                "AIS control restore is blocked when main restore fails",
                ("start", "ais-catcher-control.service") not in dependent.actions,
            )
            dependent.fail_start.clear()
            receiver_manager.recover_handovers(
                service_state=dependent.state,
                service_action=dependent.action,
                wait_for_service=dependent.wait,
            )
            check("dependent AIS recovery later completes", receiver_manager.is_available("sdr1"))

            interrupted = FakeServices({"readsb.service": True})

            def interrupted_stop(action, service):
                interrupted.actions.append((action, service))
                interrupted.states[service] = False
                raise KeyboardInterrupt("simulated process death after systemctl stop")

            try:
                receiver_manager.begin_handover(
                    "sdr2",
                    mission_key="test:stop-crash-window",
                    services=["readsb.service"],
                    service_state=interrupted.state,
                    service_action=interrupted_stop,
                    wait_for_service=interrupted.wait,
                    release_delay_seconds=0,
                )
            except KeyboardInterrupt:
                pass
            crashed = reservation(receiver_manager.get_status(), "sdr2")
            crashed_service = (crashed.get("handover") or {}).get("services", [{}])[0]
            check("stop intent is durable before systemctl returns", crashed_service.get("stop_status") == "STOPPING")
            check("crash window remains receiver-owned", not receiver_manager.is_available("sdr2"))
            recovered = receiver_manager.recover_handovers(
                service_state=interrupted.state,
                service_action=interrupted.action,
                wait_for_service=interrupted.wait,
            )
            check("crash window restores service from durable intent", recovered.get("recovered") == 1)
            check("crash window recovery restarts stopped service", interrupted.states["readsb.service"] is True)

            class LateClaim(FakeServices):
                def __init__(self):
                    super().__init__({"readsb.service": False})
                    self.observations = 0

                def state(self, service):
                    self.observations += 1
                    if self.observations > 1:
                        self.states[service] = True
                    return super().state(service)

            late_claim = LateClaim()
            try:
                receiver_manager.begin_handover(
                    "sdr2",
                    mission_key="test:late-claim",
                    services=["readsb.service"],
                    service_state=late_claim.state,
                    service_action=late_claim.action,
                    wait_for_service=late_claim.wait,
                    release_delay_seconds=0,
                )
            except RuntimeError:
                late_claim_blocked = True
            else:
                late_claim_blocked = False
            check("new service claim during handover aborts mission", late_claim_blocked)
            check("aborted late claim does not strand receiver", receiver_manager.is_available("sdr2"))

            payload = json.loads(receiver_manager.STATE_FILE.read_text(encoding="utf-8"))
            check("handover uses existing Receiver Manager state file", set(payload) == {"reservations", "last_releases"})
            receiver_manager.STATE_FILE.write_text("{broken", encoding="utf-8")
            try:
                receiver_manager.is_available("sdr1")
            except RuntimeError:
                corrupt_blocked = True
            else:
                corrupt_blocked = False
            check("corrupt Receiver Manager state fails closed", corrupt_blocked)
            receiver_manager.STATE_FILE.write_text("[]", encoding="utf-8")
            try:
                receiver_manager.get_status()
            except RuntimeError:
                wrong_schema_blocked = True
            else:
                wrong_schema_blocked = False
            check("wrong Receiver Manager schema fails closed", wrong_schema_blocked)
        finally:
            receiver_manager.STATE_FILE = original_state_file
            receiver_state.SDR2_STATE_FILE = original_sdr2_file
            receiver_manager.event_bus.publish_receiver = original_publish


def run_integration_tests():
    from core import device_manager, plugin_registry, receiver_contexts

    app = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    manager = (ROOT / "core" / "receiver_manager.py").read_text(encoding="utf-8")
    executor = (ROOT / "core" / "iss_voice_executor.py").read_text(encoding="utf-8")
    controlled = (ROOT / "core" / "controlled_iq_capture.py").read_text(encoding="utf-8")
    satdump = (ROOT / "core" / "satdump.py").read_text(encoding="utf-8")
    contexts = (ROOT / "core" / "receiver_contexts.py").read_text(encoding="utf-8")

    check(
        "AIS companion services have explicit handover order",
        plugin_registry.get_plugin_handover_services("ais") == [
            "ais-catcher-control.service",
            "ais-catcher.service",
        ],
    )
    check(
        "AIS Execution Plan target remains compatible",
        plugin_registry.get_plugin_services("ais") == ["ais-catcher.service"],
    )
    check(
        "device conflicts use handover metadata",
        device_manager.get_conflicting_services("sdr1", exclude_role="weather") == [
            "ais-catcher-control.service",
            "ais-catcher.service",
        ],
    )
    check("Weather uses shared handover", "receiver_manager.begin_handover(" in app)
    check("ISS executor uses shared handover", "receiver_manager.begin_handover(" in executor)
    check("Controlled Capture uses shared handover", "receiver_manager.begin_handover(" in controlled)
    check("Record NOW uses shared handover", "receiver_manager.begin_handover(" in satdump)
    check("Record NOW reports restore ATTENTION as failure", "Record NOW receiverherstel vereist aandacht" in satdump)
    check(
        "manual service Start and Restart are fail-closed",
        "receiver_manager.service_action_block(plugin_id, systemctl_action)" in app,
    )
    check(
        "startup recovery precedes stale release",
        app.index("receiver_manager.recover_handovers(")
        < app.index("stale_reservations = ["),
    )
    check(
        "runtime API does not trigger crash recovery",
        "def get_reconciled_receiver_manager_status(*, recover=False):" in app
        and "get_reconciled_receiver_manager_status(recover=True)" in app,
    )
    check("hardcoded ADS-B profile restore removed", 'set_active_profile("adsb")' not in app and 'profile="adsb"' not in satdump)
    check("legacy local ISS restore loop removed", "for service in reversed(stopped_services)" not in executor)
    check("legacy local Controlled Capture restore loop removed", "for service in reversed(stopped_services)" not in controlled)
    check("Receiver Manager owns durable handover methods", all(token in manager for token in (
        "def begin_handover(", "def restore_handover(", "def recover_handovers(", "def service_action_block("
    )))
    snapshot = receiver_contexts.get_snapshot()
    check("Receiver Contexts projects Receiver Manager", snapshot.get("authority") == "receiver_manager")
    check("Receiver Contexts has no duplicate state file", "receiver_contexts.json" not in contexts)


def main():
    run_behaviour_tests()
    run_integration_tests()
    print("VALIDATION PASS: SDRCC v0.54.0b Receiver Handover")


if __name__ == "__main__":
    main()
