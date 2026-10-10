#!/usr/bin/env python3
"""Regression tests for update safety after a finished or paused satellite pass.

Imports only the relevant function AST nodes to avoid importing the live dashboard
or requiring running receivers, SatDump, systemd or a Flask environment.
Run with: python3 scripts/validate_update_autopilot_idle_v0657.py
"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "dashboard" / "app.py"
FUNCTIONS = {
    "reconcile_idle_autopilot_runtime",
    "_update_receiver_runtime_blockers",
}


def load_functions():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS
    ]
    if {node.name for node in selected} != FUNCTIONS:
        raise AssertionError("Required update guard functions were not found")
    return compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec")


FUNCTION_CODE = load_functions()


class IdleAutopilotUpdateTests(unittest.TestCase):
    def setUp(self):
        self.runtime = {
            "pass_key": "test-pass",
            "target_pass": {"mission_type": "weather"},
            "prepared": False,
            "locked": False,
            "record_started": False,
            "process": None,
            "iss_execution_active": False,
            "iss_execution_result": None,
        }
        self.mission = {"phase": "READY", "active_job": None}
        self.simulator = {"active": False}
        self.scheduler = {"mode": "MANUAL"}
        self.restore = Mock(return_value={"ok": True})
        self.reset = Mock()
        self.log = Mock()
        self.context = {
            "autopilot_runtime": self.runtime,
            "mission_engine_core": SimpleNamespace(get_mission_status=lambda: self.mission),
            "mission_simulator": SimpleNamespace(
                get_status=lambda: {"simulator": self.simulator}
            ),
            "mission_scheduler_core": SimpleNamespace(
                get_scheduler_status=lambda: self.scheduler
            ),
            "restore_autopilot_receiver": self.restore,
            "reset_autopilot_runtime": self.reset,
            "write_log": self.log,
        }
        exec(FUNCTION_CODE, self.context)

    def reconcile(self):
        return self.context["reconcile_idle_autopilot_runtime"]()

    def blockers(self):
        return self.context["_update_receiver_runtime_blockers"]()

    def test_finished_weather_on_manual_clears_stale_flags(self):
        self.runtime.update(prepared=True, locked=True, record_started=True)
        self.assertTrue(self.reconcile())
        self.restore.assert_called_once()
        self.reset.assert_called_once()

    def test_finished_weather_on_auto_can_also_clear(self):
        self.runtime["record_started"] = True
        self.scheduler["mode"] = "AUTO"
        self.assertTrue(self.reconcile())
        self.reset.assert_called_once()

    def test_prepared_future_pass_on_auto_is_not_reset(self):
        self.runtime["prepared"] = True
        self.scheduler["mode"] = "AUTO"
        self.assertFalse(self.reconcile())
        self.restore.assert_not_called()

    def test_paused_preparation_with_no_running_job_is_released(self):
        self.runtime.update(prepared=True, locked=True)
        self.scheduler["mode"] = "PAUSED"
        self.assertTrue(self.reconcile())
        self.restore.assert_called_once()

    def test_real_mission_is_never_reset(self):
        self.runtime["record_started"] = True
        self.mission["active_job"] = {"mission_id": "real"}
        self.assertFalse(self.reconcile())
        self.restore.assert_not_called()
        self.assertIn("mission_job", self.blockers())

    def test_process_still_present_is_never_reset(self):
        self.runtime["record_started"] = True
        self.runtime["process"] = object()
        self.assertFalse(self.reconcile())
        self.assertIn("satdump_process", self.blockers())

    def test_iss_thread_pending_result_is_never_reset(self):
        self.runtime["record_started"] = True
        self.runtime["target_pass"] = {"mission_type": "iss_sstv"}
        self.assertFalse(self.reconcile())
        self.restore.assert_not_called()

    def test_iss_finished_with_result_can_clear(self):
        self.runtime["record_started"] = True
        self.runtime["target_pass"] = {"mission_type": "iss_voice"}
        self.runtime["iss_execution_result"] = {"ok": True}
        self.assertTrue(self.reconcile())

    def test_receiver_handover_failure_still_blocks(self):
        self.runtime["locked"] = True
        self.restore.return_value = {"ok": False, "errors": ["restore failed"]}
        self.assertFalse(self.reconcile())
        self.reset.assert_not_called()
        self.assertIn("receiver_locked", self.blockers())

    def test_non_idle_engine_state_never_resets(self):
        self.runtime["prepared"] = True
        self.mission["phase"] = "LOCK RECEIVER"
        self.assertFalse(self.reconcile())

    def test_active_simulator_never_resets(self):
        self.runtime["prepared"] = True
        self.simulator["active"] = True
        self.assertFalse(self.reconcile())
        self.assertIn("mission_simulator", self.blockers())


if __name__ == "__main__":
    unittest.main()
