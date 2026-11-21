"""Updater must distinguish an empty hardware observation from a live recovery intent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import receiver_manager

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/install/check_update.py"


class SourcePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source = root / "source"
        self.project = root / "installed"
        (self.source / "scripts/install").mkdir(parents=True)
        self.project.mkdir()
        (self.source / "VERSION").write_text("0.70.9\\n")
        digest = hashlib.sha256((self.source / "VERSION").read_bytes()).hexdigest()
        (self.source / "scripts/install/update_manifest.json").write_text(
            json.dumps({"VERSION": [digest]})
        )
        self.state = self.project / "data/state/receiver_manager.json"
        self.state.parent.mkdir(parents=True)

    def check(self, state=None):
        if state is not None:
            self.state.write_text(json.dumps(state))
        return subprocess.run(
            [sys.executable, str(CHECK), str(self.source), str(self.project)],
            capture_output=True, text=True, timeout=10, check=False,
        )

    def test_empty_hardware_recovery_waiting_does_not_block(self):
        result = self.check({"hardware_recovery": {
            "receiver02": {"services": [], "status": "WAITING", "runtime_generation": "old"}
        }})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS:", result.stdout)

    def test_real_service_recovery_remains_blocked(self):
        result = self.check({"hardware_recovery": {
            "receiver02": {"services": ["readsb.service"], "status": "WAITING"}
        }})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hardware_recovery: receiver02", result.stderr)

    def test_action_required_recovery_even_empty_stays_blocked(self):
        result = self.check({"hardware_recovery": {
            "receiver02": {"services": [], "status": "ACTION_REQUIRED"}
        }})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hardware_recovery", result.stderr)

    def test_invalid_recovery_record_fails_closed(self):
        result = self.check({"hardware_recovery": {
            "receiver02": {"services": "invalid", "status": "WAITING"}
        }})
        self.assertNotEqual(result.returncode, 0)

    def test_receiver_reservation_cannot_be_bypassed(self):
        result = self.check({"reservations": {
            "receiver02": {"mission_key": "weather"}
        }, "hardware_recovery": {
            "receiver02": {"services": [], "status": "WAITING"}
        }})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reservations", result.stderr)

    def test_pending_binding_transaction_cannot_be_bypassed(self):
        result = self.check({"binding_transaction": {"mapping": {"receiver02": "NEW"}}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("binding_transaction", result.stderr)

    def test_locally_modified_source_remains_blocked(self):
        (self.project / "VERSION").write_text("tampered\\n")
        result = self.check({})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("locally modified source VERSION", result.stderr)


class HardwareTickTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name) / "receiver_manager.json"
        self.previous = receiver_manager._previous_active
        self.addCleanup(setattr, receiver_manager, "_previous_active", self.previous)
        receiver_manager._previous_active = {}

    def tick_missing(self):
        with (
            patch.object(receiver_manager, "STATE_FILE", self.state),
            patch("core.receiver_hardware.scan", return_value={"ok": True, "ambiguous": False}),
            patch.object(receiver_manager, "get_devices", return_value=[
                {"registry_id": "receiver02", "presence": "MISSING"}
            ]),
            patch("core.device_manager.get_conflicting_services", return_value=["readsb.service"]),
            patch.object(receiver_manager, "bind_hardware", return_value={"ok": True}),
        ):
            receiver_manager.hardware_tick(
                service_state=lambda _: {"state": "inactive", "active": False},
                service_action=lambda *_: True,
                wait_for_service=lambda *_: True,
                stop_receiver=lambda *_: None,
                privileged_apply=lambda *_: {"ok": True},
            )
            return receiver_manager._load_state()

    def test_missing_usb_does_not_create_empty_recovery(self):
        state = self.tick_missing()
        self.assertFalse(state.get("hardware_recovery"))

    def test_previous_empty_recovery_is_cleared_during_tick(self):
        self.state.write_text(json.dumps({"hardware_recovery": {
            "receiver02": {"status": "WAITING", "services": []}
        }}))
        state = self.tick_missing()
        self.assertFalse(state.get("hardware_recovery"))

    def test_missing_usb_with_previous_live_service_retains_intent(self):
        receiver_manager._previous_active = {"receiver02": ["readsb.service"]}
        state = self.tick_missing()
        self.assertEqual(
            state["hardware_recovery"]["receiver02"]["services"], ["readsb.service"]
        )

    def test_dashboard_gate_matches_source_preflight_semantics(self):
        self.assertFalse(receiver_manager.has_pending_hardware_recovery({
            "receiver02": {"services": [], "status": "WAITING"}
        }))
        self.assertTrue(receiver_manager.has_pending_hardware_recovery({
            "receiver02": {"services": ["readsb.service"], "status": "WAITING"}
        }))
        self.assertTrue(receiver_manager.has_pending_hardware_recovery({
            "receiver02": {"services": [], "status": "ACTION_REQUIRED"}
        }))


if __name__ == "__main__":
    unittest.main()
