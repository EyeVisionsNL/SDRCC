#!/usr/bin/env python3
"""Offline regression for SDRCC's opt-in external updates.

No network access, package changes, sudo, systemd or RTL-SDR hardware needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

from core import external_updates as updates


class ExternalUpdateTests(unittest.TestCase):
    def setUp(self):
        updates._CACHE.update({"checked_at": 0.0, "ais_release": None, "error": None})

    def test_ais_version_parser_rejects_unrelated_text(self):
        self.assertEqual(updates.ais_version("AIS-catcher v0.70\n"), "0.70")
        self.assertEqual(updates.ais_version("AIS-catcher 0.71.3"), "0.71.3")
        self.assertIsNone(updates.ais_version("not a version 2026.10"))
        self.assertEqual(updates.version_tuple("0.70"), (0, 70, 0))
        self.assertIsNone(updates.version_tuple("develop"))

    def test_apt_policy_parsing_and_version_ordering(self):
        with patch.object(updates, "command", return_value="satdump:\n  Installed: 1.2.2-1\n  Candidate: 1.2.3-1\n"):
            self.assertEqual(updates._apt_version("satdump", "Installed"), "1.2.2-1")
            self.assertEqual(updates._apt_version("satdump", "Candidate"), "1.2.3-1")
        with patch.object(updates.subprocess, "run") as fake:
            fake.return_value.returncode = 0
            self.assertTrue(updates._apt_newer("1.2.2", "1.2.3"))
            self.assertEqual(fake.call_args.args[0][:2], ["/usr/bin/dpkg", "--compare-versions"])
        self.assertFalse(updates._apt_newer(None, "1.2.3"))

    def test_release_tag_must_be_a_real_version(self):
        def request(tag):
            payload = json.dumps({"tag_name": tag, "html_url": "https://github.com/jvde-github/AIS-catcher/releases/tag/" + tag})
            response = MagicMock()
            response.read.return_value = payload.encode()
            response.__enter__.return_value = response
            return response
        with patch.object(updates, "urlopen", return_value=request("v0.71")):
            self.assertEqual(updates._check_ais_release()["version"], "0.71")
        with patch.object(updates, "urlopen", return_value=request("main;rm -rf /")):
            with self.assertRaises(ValueError):
                updates._check_ais_release()

    def test_snapshot_disables_custom_binaries_and_source_satdump(self):
        def command(args, timeout=5):
            name = args[0]
            if name == "AIS-catcher":
                return "AIS-catcher v0.70"
            if name.endswith("dpkg-query"):
                return ""
            return ""
        with patch.object(updates, "command", side_effect=command), \
             patch.object(updates, "release", return_value={"ais_release": {
                 "version": "0.71", "tag": "v0.71",
                 "url": "https://github.com/jvde-github/AIS-catcher/releases/tag/v0.71"}}), \
             patch.object(updates, "_apt_version", return_value=None), \
             patch.object(updates.shutil, "which", side_effect=lambda binary:
                 "/usr/bin/satdump" if binary == "satdump" else "/usr/bin/AIS-catcher"), \
             patch.object(updates, "worker_status", return_value={}):
            info = updates.snapshot()
        by_id = {row["id"]: row for row in info["software"]}
        self.assertTrue(by_id["ais-catcher"]["can_install"])
        self.assertFalse(by_id["satdump"]["can_install"])
        self.assertFalse(by_id["readsb"]["can_install"])
        self.assertFalse(by_id["rtl-airband"]["can_install"])

    def test_product_arguments_are_hardcoded_and_updates_are_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "dashboard/app.py").read_text()
        helper = (root / "scripts/sdrcc_external_update.py").read_text()
        ui = (root / "dashboard/static/js/external_updates.js").read_text()
        installer = (root / "install.sh").read_text()
        self.assertIn('ALLOWED = {"ais-catcher", "satdump"}', helper)
        self.assertIn('if product not in {"ais-catcher", "satdump"}:', app)
        self.assertIn("receiver_manager.service_control_serialized", app)
        self.assertIn("_update_receiver_runtime_blockers()", app)
        self.assertIn("--only-upgrade", helper)
        self.assertIn("backup / \"config\"", helper)
        self.assertIn("window.confirm(", ui)
        self.assertIn("sdrcc-external-update ais-catcher", installer)
        self.assertIn("sdrcc-external-update satdump", installer)
        self.assertNotIn("shell=True", helper)


if __name__ == "__main__":
    unittest.main()
