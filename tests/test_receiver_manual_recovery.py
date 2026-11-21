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

    def test_idle_receiver_recovery_is_idempotent(self):
        self.write({})
        first = receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        second = receiver_manager.recover_idle_receiver("sdr2", service_state=self.stopped)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertFalse(second["released_stale_reservation"])
        self.assertFalse(second["cleared_hardware_recovery"])


if __name__ == "__main__":
    unittest.main()
