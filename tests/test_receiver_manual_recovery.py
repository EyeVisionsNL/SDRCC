"""Guarded one-receiver recovery must never erase an active owner or another RX."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import receiver_manager


class ReceiverManualRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.state_file = Path(self.tempdir.name) / "receiver_manager.json"
        self.patches = [
            patch.object(receiver_manager, "STATE_FILE", self.state_file),
            patch.object(receiver_manager, "get_device", side_effect=self.device),
            patch("core.device_manager.get_conflicting_services", return_value=["readsb.service"]),
            patch("core.receiver_hardware.scan", return_value={
                "ok": True, "ambiguous": False,
                "receivers": [{"serial": "24006572"}],
            }),
            patch("core.receiver_hardware.presence", return_value="PRESENT"),
            patch.object(receiver_manager.event_bus, "publish_receiver"),
        ]
        for helper in self.patches:
            helper.start()
            self.addCleanup(helper.stop)

    @staticmethod
    def device(receiver_id):
        if receiver_id in {"receiver02", "sdr2"}:
            return {
                "registry_id": "receiver02", "runtime_id": "sdr2",
                "serial": "24006572", "number": "RX02",
            }
        return None

    def write(self, document):
        self.state_file.write_text(json.dumps(document), encoding="utf-8")

    @staticmethod
    def stopped(_service):
        return {"active": False, "state": "failed"}

    def test_stale_owner_and_hardware_recovery_are_removed_only_from_rx02(self):
        self.write({
            "reservations": {
                "receiver02": {
                    "receiver_id": "receiver02", "mission_key": "old:weather",
                    "status": "ATTENTION", "handover": {"status": "ATTENTION", "services": []},
                },
                "receiver01": {
                    "receiver_id": "receiver01", "mission_key": "other:session",
                    "status": "RESERVED",
                },
            },
            "hardware_recovery": {
                "receiver02": {"status": "ACTION_REQUIRED", "services": ["readsb.service"]},
                "receiver01": {"status": "WAITING", "services": []},
            },
        })
        result = receiver_manager.recover_idle_receiver("receiver02", service_state=self.stopped)
        state = receiver_manager._load_state()
        self.assertTrue(result["ok"])
        self.assertTrue(result["released_stale_reservation"])
        self.assertTrue(result["cleared_hardware_recovery"])
        self.assertNotIn("receiver02", state["reservations"])
        self.assertNotIn("receiver02", state["hardware_recovery"])
        self.assertIn("receiver01", state["reservations"])
        self.assertIn("receiver01", state["hardware_recovery"])
        released = state["last_releases"]["receiver02"]
        self.assertEqual(released["handover"]["status"], "ABANDONED_OPERATOR_RECOVERY")

    def test_no_live_service_is_stopped_or_overwritten(self):
        self.write({"reservations": {
            "receiver02": {"receiver_id": "receiver02", "mission_key": "old:weather"}
        }})
        with self.assertRaisesRegex(RuntimeError, "not confirmed stopped"):
            receiver_manager.recover_idle_receiver(
                "sdr2", service_state=lambda _: {"active": True, "state": "active"}
            )
        self.assertIn("receiver02", receiver_manager._load_state()["reservations"])

    def test_missing_usb_refuses_to_clear_ownership(self):
        self.write({"hardware_recovery": {"receiver02": {"services": []}}})
        with patch("core.receiver_hardware.presence", return_value="MISSING"):
            with self.assertRaisesRegex(RuntimeError, "USB hardware missing"):
                receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        self.assertIn("receiver02", receiver_manager._load_state()["hardware_recovery"])

    def test_pending_binding_transaction_is_not_overwritten(self):
        self.write({"binding_transaction": {"mapping": {"receiver02": "24006572"}},
                    "hardware_recovery": {"receiver02": {"services": []}}})
        with self.assertRaisesRegex(RuntimeError, "binding transaction"):
            receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        self.assertIn("receiver02", receiver_manager._load_state()["hardware_recovery"])

    def test_manual_recovery_stops_only_confirmed_restart_loop(self):
        self.write({})
        state = {"active": False, "state": "activating", "sub_state": "auto-restart"}
        actions = []

        def action(operation, service):
            actions.append((operation, service))
            state.update(state="inactive", sub_state="dead")
            return True

        result = receiver_manager.recover_idle_receiver(
            "sdr2", service_state=lambda _: dict(state), service_action=action,
            wait_for_service=lambda *_: state["state"] == "inactive",
        )
        self.assertEqual(actions, [("stop", "readsb.service")])
        self.assertEqual(result["stopped_restart_loops"], ["readsb.service"])

    def test_manual_recovery_does_not_stop_loop_if_another_service_is_active(self):
        self.write({})
        def observe(service):
            if service == "readsb.service":
                return {"active": False, "state": "activating", "sub_state": "auto-restart"}
            return {"active": True, "state": "active"}
        with patch("core.device_manager.get_conflicting_services", return_value=["readsb.service", "voice.service"]):
            with patch.object(receiver_manager, "_result_ok") as action:
                with self.assertRaisesRegex(RuntimeError, "not confirmed stopped"):
                    receiver_manager.recover_idle_receiver(
                        "sdr2", service_state=observe, service_action=action, wait_for_service=lambda *_: True,
                    )
                action.assert_not_called()

    def _run_crash_worker(self, *, healthy=False, other_busy=False, reserved=False, idle=False, usb=False, reset_fails=False):
        self.write({})
        state = {"active": False, "state": "inactive" if idle else "activating",
                 "sub_state": "dead" if idle else "auto-restart", "restart_count": 3}
        actions = []
        logs = []

        def observe(service):
            if service == "readsb.service":
                return dict(state)
            return {"active": other_busy, "state": "active" if other_busy else "inactive"}

        def action(operation, service):
            actions.append((operation, service))
            if operation == "stop":
                state.update(active=False, state="inactive", sub_state="dead")
            elif healthy:
                state.update(active=True, state="active", sub_state="running")
            else:
                state.update(active=False, state="activating", sub_state="auto-restart")
            return True

        with patch.object(receiver_manager, "_crash_budgets", {}), \
             patch.object(receiver_manager, "get_assigned_device", side_effect=lambda plugin: self.device("sdr2") if plugin == "adsb" else None), \
             patch.object(receiver_manager, "hardware_ready", return_value=True), \
             patch.object(receiver_manager, "service_action_block", return_value={"reason": "reserved"} if reserved else None), \
             patch("core.device_manager.get_conflicting_services", return_value=["readsb.service", "voice.service"]):
            kwargs = dict(service_state=observe, service_action=action,
                          wait_for_service=lambda _, expected, __: state["state"] == expected,
                          verify=lambda _: {"healthy": healthy}, observe=lambda _: {"healthy": healthy},
                          log=logs.append)
            if usb:
                def reset(device):
                    self.assertEqual(device["serial"], "24006572")
                    self.assertEqual(state["state"], "inactive")
                    actions.append(("usb-reset", device["serial"]))
                    if reset_fails:
                        raise RuntimeError("test failure")
                    return "USB reset OK"
                kwargs["usb_reset"] = reset
            receiver_manager.recover_crashed_services(**kwargs)
            receiver_manager.recover_crashed_services(**kwargs)
            exhausted = receiver_manager.crash_recovery_exhausted("readsb.service")
        return actions, exhausted, logs

    def test_auto_recovery_restores_only_assigned_receiver(self):
        actions, exhausted, logs = self._run_crash_worker(healthy=True)
        self.assertEqual(actions, [("stop", "readsb.service"), ("start", "readsb.service")])
        self.assertFalse(exhausted)
        self.assertTrue(any("runtime verified" in item for item in logs))

    def test_auto_recovery_stops_after_two_unsuccessful_attempts(self):
        actions, exhausted, logs = self._run_crash_worker()
        self.assertEqual(actions, [
            ("stop", "readsb.service"), ("start", "readsb.service"),
            ("stop", "readsb.service"), ("start", "readsb.service"),
            ("stop", "readsb.service"),
        ])
        self.assertTrue(exhausted)
        self.assertTrue(any("retry budget exhausted" in item for item in logs))

    def test_auto_recovery_respects_other_services_reservation_and_manual_stop(self):
        for args in ({"other_busy": True}, {"reserved": True}, {"idle": True}):
            with self.subTest(args=args):
                actions, exhausted, _ = self._run_crash_worker(**args)
                self.assertEqual(actions, [])
                self.assertFalse(exhausted)

    def test_usb_auto_recovery_is_ordered_and_bounded(self):
        actions, exhausted, logs = self._run_crash_worker(usb=True, healthy=True)
        self.assertEqual(actions, [("stop", "readsb.service"), ("usb-reset", "24006572"), ("start", "readsb.service")])
        self.assertFalse(exhausted)
        actions, exhausted, logs = self._run_crash_worker(usb=True, reset_fails=True)
        self.assertEqual(actions.count(("usb-reset", "24006572")), 2)
        self.assertNotIn(("start", "readsb.service"), actions)
        self.assertTrue(exhausted)
        for args in ({"other_busy": True}, {"reserved": True}, {"idle": True}):
            self.assertEqual(self._run_crash_worker(usb=True, **args)[0], [])

    def test_manual_usb_reset_only_idle_receiver(self):
        self.write({})
        calls = []
        result = receiver_manager.recover_idle_receiver(
            "sdr2", service_state=self.stopped,
            usb_reset=lambda device: calls.append(device["serial"]) or "USB reset OK",
        )
        self.assertEqual(calls, ["24006572"])
        self.assertEqual(result["usb_reset"], "USB reset OK")
        with self.assertRaisesRegex(RuntimeError, "not confirmed stopped"):
            receiver_manager.recover_idle_receiver(
                "sdr2", service_state=lambda _: {"active": True, "state": "active"},
                usb_reset=lambda device: self.fail("live receiver reset"),
            )

    def test_failed_manual_usb_reset_preserves_recovery_evidence(self):
        self.write({"hardware_recovery": {"receiver02": {"services": ["readsb.service"]}}})
        def fail(device):
            raise RuntimeError("USB reset failed")
        with self.assertRaisesRegex(RuntimeError, "USB reset failed"):
            receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped, usb_reset=fail)
        self.assertIn("receiver02", receiver_manager._load_state()["hardware_recovery"])

    def test_idle_receiver_recovery_is_idempotent(self):
        self.write({})
        first = receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        second = receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertFalse(second["released_stale_reservation"])
        self.assertFalse(second["cleared_hardware_recovery"])


if __name__ == "__main__":
    unittest.main()
