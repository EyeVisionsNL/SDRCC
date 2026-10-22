#!/usr/bin/env python3
"""Non-invasive tests for the local SDRCC installation GUI.

Run: python3 -m unittest discover -s scripts/install -p 'test_gui_installer.py'
No SDR hardware, network access, sudo or installed services are required.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name("gui_installer.py")
spec = importlib.util.spec_from_file_location("sdrcc_gui_installer", MODULE)
gui = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gui
spec.loader.exec_module(gui)


class FakeProcess:
    def __init__(self, output, status=0):
        self.stdout = io.BytesIO(output.encode("utf-8"))
        self.stdin = io.BytesIO()
        self._status = status

    def wait(self):
        return self._status


class InstallerTests(unittest.TestCase):
    def test_stage_markers(self):
        state = gui.InstallState()
        state.add_line("==> Preflight")
        self.assertEqual(state.percent, 5)
        state.add_line("==> Final AIS-catcher setup")
        self.assertEqual(state.percent, 94)
        self.assertTrue(state.ais_stage)
        state.add_line("==> Preflight")
        self.assertEqual(state.percent, 94)

    def test_selection_validation_prevents_running(self):
        state = gui.InstallState()
        with self.assertRaises(ValueError):
            state.start({"satellite": "yes", "traffic_voice": True, "radio_receiver": True})
        self.assertFalse(state.started)
        with self.assertRaises(ValueError):
            state.start({"satellite": True, "traffic_voice": True})
        self.assertFalse(state.started)

    def test_ais_confirmation_and_defer(self):
        state = gui.InstallState()
        process = FakeProcess("")
        state.process = process
        state.awaiting_ais = True
        state.ais_reply("")
        self.assertFalse(state.awaiting_ais)
        self.assertEqual(process.stdin.getvalue(), b"\n")
        state.awaiting_ais = True
        state.ais_reply("d")
        self.assertEqual(process.stdin.getvalue(), b"\nd\n")
        with self.assertRaises(ValueError):
            state.ais_reply("")

    def test_bash_runner_uses_gui_flags_without_real_install(self):
        state = gui.InstallState()
        process = FakeProcess(
            "==> Preflight\n==> Optional SDRCC features\n"
            "==> Final AIS-catcher setup\nPASS: AIS configured.\n", 0)
        with patch.object(gui.subprocess, "Popen", return_value=process) as popen:
            state._run({"satellite": True, "traffic_voice": False,
                        "radio_receiver": True})
        cmd = popen.call_args.args[0]
        env = popen.call_args.kwargs["env"]
        self.assertEqual(cmd[-1], "--gui-choices")
        self.assertEqual(env["SDRCC_FEATURE_SATELLITE"], "1")
        self.assertEqual(env["SDRCC_FEATURE_TRAFFIC_VOICE"], "0")
        self.assertEqual(env["SDRCC_FEATURE_RADIO_RECEIVER"], "1")
        self.assertTrue(state.finished)
        self.assertEqual(state.exit_code, 0)
        self.assertEqual(state.percent, 100)

    def test_preview_never_invokes_installer(self):
        state = gui.InstallState(preview=True)
        choices = {"satellite": True, "traffic_voice": False, "radio_receiver": True}
        with patch.object(gui.subprocess, "Popen", side_effect=AssertionError("must not execute")), \
             patch.object(gui.time, "sleep", return_value=None):
            state.start(choices)
            # Let the simulator thread finish its short in-memory stage sequence.
            for _ in range(10000):
                if state.snapshot()["awaiting_ais"]:
                    break
                threading.Event().wait(0.001)
            else:
                self.fail("Preview never reached AIS simulation")
        snapshot = state.snapshot()
        self.assertTrue(snapshot["preview"])
        self.assertTrue(snapshot["ais_stage"])
        self.assertFalse(snapshot["finished"])
        self.assertEqual(snapshot["percent"], 94)
        state.ais_reply("")
        self.assertTrue(state.snapshot()["finished"])
        self.assertEqual(state.snapshot()["percent"], 100)
        self.assertIn("nothing was changed", state.snapshot()["stage"])

    def test_preview_defer_does_not_write_to_subprocess(self):
        state = gui.InstallState(preview=True)
        state.awaiting_ais = True
        with patch.object(gui.subprocess, "Popen", side_effect=AssertionError("must not execute")):
            state.ais_reply("d")
        self.assertTrue(state.finished)
        self.assertIn("simulated AIS deferred", state.lines[-1])
        self.assertIsNone(state.process)

    def test_failed_install_stays_visible(self):
        state = gui.InstallState()
        with patch.object(gui.subprocess, "Popen",
                          return_value=FakeProcess("FAIL: install error\n", 8)):
            state._run({"satellite": False, "traffic_voice": True,
                        "radio_receiver": False})
        self.assertTrue(state.finished)
        self.assertEqual(state.exit_code, 8)
        self.assertIn("failed", state.stage.lower())

    def test_deferred_ais_is_not_reported_as_fully_configured(self):
        state = gui.InstallState()
        output = ("==> Final AIS-catcher setup\n"
                  "DEFERRED: AIS is not ready. Resume with bash install.sh --ais-setup.\n"
                  "AIS setup deferred. Resume with: bash install.sh --ais-setup\n")
        with patch.object(gui.subprocess, "Popen",
                          return_value=FakeProcess(output)):
            state._run({"satellite": True, "traffic_voice": True,
                        "radio_receiver": True})
        self.assertIn("deferred", state.stage.lower())


if __name__ == "__main__":
    unittest.main()
