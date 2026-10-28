#!/usr/bin/env python3
"""Offline regression for SDRCC's opt-in external updates.

No network access, package changes, sudo, systemd or RTL-SDR hardware needed.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
        self.assertTrue(by_id["ais-catcher"]["available"])
        self.assertFalse(by_id["ais-catcher"]["can_install"], "unmanaged AIS source must not be upgraded")
        self.assertFalse(by_id["satdump"]["can_install"])
        self.assertFalse(by_id["readsb"]["can_install"])
        self.assertFalse(by_id["rtl-airband"]["can_install"])

    def test_matching_asset_requires_current_ubuntu_platform(self):
        release = {"assets": [
            {"name": "ais-catcher_ubuntu_resolute_amd64.deb",
             "digest": "sha256:" + "e" * 64,
             "url": "https://github.com/jvde-github/AIS-catcher/releases/download/v0.71/ais-catcher_ubuntu_resolute_amd64.deb"}]}
        with patch("pathlib.Path.read_text", return_value='ID=ubuntu\nVERSION_CODENAME=resolute\n'), \
             patch.object(updates, "command", return_value="amd64\n"):
            self.assertIsNotNone(updates.matching_ais_asset(release))
        with patch("pathlib.Path.read_text", return_value='ID=debian\nVERSION_CODENAME=trixie\n'), \
             patch.object(updates, "command", return_value="amd64\n"):
            self.assertIsNone(updates.matching_ais_asset(release))

    def test_satdump_installed_version_uses_supported_cli_subcommand(self):
        with patch.object(updates, "command",
                          return_value="This is SatDump v1.2.2\n") as called:
            self.assertEqual(
                updates.installed_satdump_version(None, "/usr/bin/satdump"),
                ("1.2.2", "binary"))
        called.assert_called_once_with(["/usr/bin/satdump", "version"], timeout=4)
        with patch.object(updates, "command", return_value="unknown option"):
            self.assertEqual(
                updates.installed_satdump_version(None, "/usr/bin/satdump"),
                (None, "non-apt-unverified"))

    def test_latest_upstream_versions_are_read_only_and_validated(self):
        def fake_response(data):
            response = MagicMock()
            response.read.return_value = data.encode()
            response.__enter__.return_value = response
            return response
        for tag, api, page, prefix in (
            ("1.2.2", updates.SATDUMP_RELEASE_API, updates.SATDUMP_PAGE, ""),
            ("v6.2.0", updates.AIRBAND_RELEASE_API, updates.AIRBAND_PAGE, "v"),
        ):
            data = json.dumps({"tag_name": tag, "draft": False, "prerelease": False})
            with patch.object(updates, "urlopen", return_value=fake_response(data)):
                self.assertEqual(
                    updates._github_stable_release(api, page, prefix)["version"],
                    tag.lstrip("v"))
        with patch.object(updates, "urlopen",
                          return_value=fake_response("3.16.20\n")):
            self.assertEqual(updates._readsb_development_version()["version"], "3.16.20")
        with patch.object(updates, "urlopen",
                          return_value=fake_response("main\n")):
            with self.assertRaises(ValueError):
                updates._readsb_development_version()
        with patch.object(updates, "urlopen", return_value=fake_response(
                json.dumps({"tag_name": "nightly", "prerelease": True}))):
            with self.assertRaises(ValueError):
                updates._github_stable_release(
                    updates.SATDUMP_RELEASE_API, updates.SATDUMP_PAGE)

    def test_updates_are_detected_without_enabling_unreviewed_installs(self):
        releases = {
            "ais_release": {"version": "0.70"},
            "satdump_release": {"version": "1.2.2"},
            "readsb_upstream": {"version": "3.16.20"},
            "airband_release": {"version": "6.2.0"},
            "errors": {},
        }
        def mock_command(args, timeout=5):
            if args[0] == "AIS-catcher":
                return "AIS-catcher v0.70"
            if args[0] == "readsb":
                return "readsb version: 3.16.15 wiedehopf git cc0d099"
            return ""
        with patch.object(updates, "release", return_value=releases), \
             patch.object(updates, "command", side_effect=mock_command), \
             patch.object(updates, "_apt_version", return_value=None), \
             patch.object(updates, "installed_satdump_version", return_value=("1.2.2", "binary")), \
             patch.object(updates, "installed_airband_version", return_value=("5.2.0", "SDRCC patched")), \
             patch.object(updates, "apt_ais_installed", return_value=False), \
             patch.object(updates.shutil, "which", side_effect=lambda name: "/usr/bin/" + name), \
             patch.object(updates, "worker_status", return_value={}):
            info = updates.snapshot()
        status = {item["id"]: item for item in info["software"]}
        self.assertEqual(status["ais-catcher"]["status"], "current")
        self.assertEqual(status["satdump"]["status"], "current")
        self.assertEqual(status["readsb"]["latest"], "3.16.20")
        self.assertEqual(status["readsb"]["status"], "review")
        self.assertEqual(status["rtl-airband"]["latest"], "6.2.0")
        self.assertEqual(status["rtl-airband"]["status"], "review")
        self.assertFalse(status["readsb"]["can_install"])
        self.assertFalse(status["rtl-airband"]["can_install"])

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
        self.assertIn("hashlib.sha256()", helper)
        self.assertIn("matching_ais_asset(latest)", helper)
        self.assertNotIn('"-p", "-M"', helper)
        self.assertIn("backup / \"config\"", helper)
        self.assertIn("window.confirm(", ui)
        self.assertIn("sdrcc-external-update ais-catcher", installer)
        self.assertIn("sdrcc-external-update satdump", installer)
        self.assertNotIn("shell=True", helper)


if __name__ == "__main__":
    unittest.main()
