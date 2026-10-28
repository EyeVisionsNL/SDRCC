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

    def test_satdump_newer_than_tagged_stable_is_not_called_up_to_date(self):
        releases = {
            "ais_release": {"version": "0.70"},
            "satdump_release": {"version": "1.2.2"},
            "readsb_upstream": {"version": "3.16.20"},
            "airband_release": {"version": "6.2.0"},
            "errors": {},
        }
        with patch.object(updates, "release", return_value=releases), \
             patch.object(updates, "command", return_value=""), \
             patch.object(updates, "_apt_version", return_value=None), \
             patch.object(updates, "installed_satdump_version", return_value=("1.2.3", "binary")), \
             patch.object(updates, "installed_airband_version", return_value=("5.2.0", "SDRCC patched")), \
             patch.object(updates.shutil, "which", return_value="/usr/bin/satdump"), \
             patch.object(updates, "worker_status", return_value={}):
            rows = updates.snapshot()["software"]
        satdump = next(row for row in rows if row["id"] == "satdump")
        self.assertEqual(satdump["status"], "ahead")
        self.assertEqual(satdump["latest"], "1.2.2")
        self.assertFalse(satdump["can_install"])

    def test_pin_safety_guards_and_compatibility(self):
        from scripts.install import upgrade_radio_runtimes as runtime
        self.assertEqual(runtime.READSB_VERSION, "3.16.20")
        self.assertEqual(runtime.READSB_NEW,
                         "dadfa3307a1951b7ef687cfe3fd66cdb708a4f6f")
        self.assertEqual(runtime.AIRBAND_SHA,
                         "66d3076819312c7eae7662028234988dc71d0be5")
        with patch.object(runtime.subprocess, "run") as systemctl:
            systemctl.return_value.returncode = 0
            with self.assertRaisesRegex(RuntimeError, "Stop readsb.service"):
                runtime.inactive("readsb.service")
        root = Path(__file__).resolve().parents[1]
        traffic = (root / "core/traffic_voice.py").read_text()
        self.assertIn('"5.2.0": "61c5c406', traffic)
        self.assertIn('"6.2.0": "66d30768', traffic)
        self.assertIn('if (chosen_version not in allowed_backends', traffic)
        airband = (root / "scripts/install/provision_external.sh").read_text()
        self.assertIn('AIRBAND_TAG="v6.2.0"', airband)
        self.assertIn('READSB_COMMIT="dadfa330', airband)
        self.assertIn('patch_rtlsdr_airband_auto_gain.py', airband)
        self.assertIn('patch_rtlsdr_airband_scan_interval.py', airband)
        self.assertIn('rollback package', runtime.update_readsb.__doc__ or
                      (root / "scripts/install/upgrade_radio_runtimes.py").read_text())

    def test_launcher_failure_distinguishes_sudo_and_systemd(self):
        forbidden = updates.explain_launch_failure(
            1, "", "sudo: a password is required")
        self.assertEqual(forbidden["code"], "sudo_permission")
        self.assertIn("sudo", forbidden["message"])
        not_allowed = updates.explain_launch_failure(
            1, "", "sorry, user eyevisions is not allowed to execute")
        self.assertEqual(not_allowed["code"], "sudo_permission")
        service = updates.explain_launch_failure(
            1, '{"ok":false,"code":"systemd_launch_failed",'
               '"message":"Unit sdrcc-external-update.service already exists"}',
            "")
        self.assertEqual(service["code"], "systemd_launch_failed")
        self.assertIn("already exists", service["message"])
        unknown = updates.explain_launch_failure(7, "", "")
        self.assertEqual(unknown["code"], "launch_failed")

    def test_external_launcher_retries_stale_failed_systemd_unit(self):
        from scripts import sdrcc_external_update as helper
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace

        events = []
        def fake_run(args, timeout=30, **kw):
            events.append(args)
            if args[0] == "/usr/bin/systemd-run" and sum(
                    1 for cmd in events if cmd[0] == "/usr/bin/systemd-run") == 1:
                return SimpleNamespace(
                    returncode=1, stdout="", stderr="Unit sdrcc-external-update.service already exists")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        captured = StringIO()
        with patch.object(helper, "run", side_effect=fake_run), \
             patch.object(helper, "active", return_value=False), \
             patch.object(helper, "status"), \
             redirect_stdout(captured):
            code = helper.launch("rtl-airband")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(captured.getvalue())["ok"])
        self.assertEqual(sum(1 for x in events if x[0] == "/usr/bin/systemd-run"), 2)
        self.assertTrue(any(x[:2] == ["/usr/bin/systemctl", "reset-failed"]
                            for x in events))

    def test_airband_cmake_executes_in_tagged_source_checkout(self):
        from scripts.install import upgrade_radio_runtimes as runtime
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        commands = []
        with TemporaryDirectory() as tmp:
            stage = Path(tmp)
            source = stage / "source"
            built = stage / "build/src/rtl_airband"
            def fake_call(args, *, cwd=None, timeout=180, env=None):
                commands.append((tuple(str(part) for part in args), cwd))
                if args[0] == "cmake" and "--build" in args:
                    built.parent.mkdir(parents=True, exist_ok=True)
                    built.write_bytes(
                        b"automatic tuner gain enabled\x00"
                        b"scan_interval_ms must be 100..500 ms")
                    built.chmod(0o755)
                if str(args[0]).endswith("/scripts/find_version"):
                    if cwd != source:
                        raise RuntimeError("version resolver needs source cwd")
                    return "v6.2.0-dirty\n"
                return ""
            with patch.object(runtime, "git_checkout", return_value=runtime.AIRBAND_SHA) as git, \
                 patch.object(runtime, "call", side_effect=fake_call):
                candidate = runtime.build_airband_candidate(
                    Path(__file__).resolve().parents[1], stage)
            self.assertEqual(candidate, built)
            git.assert_called_once_with(
                source, runtime.AIRBAND_URL, runtime.AIRBAND_SHA,
                branch=runtime.AIRBAND_TAG)
            config = next((item for item in commands
                           if item[0][0] == "cmake" and "-S" in item[0]), None)
            self.assertIsNotNone(config)
            self.assertEqual(config[1], source)
            self.assertTrue(any(item[0][0].endswith("/scripts/find_version")
                                and item[1] == source for item in commands))

    def test_clean_installer_uses_airband_source_as_cmake_cwd(self):
        source = (Path(__file__).resolve().parents[1] /
                  "scripts/install/provision_external.sh").read_text(encoding="utf-8")
        self.assertIn('cd "$WORK/airband"', source)
        self.assertIn('scripts/find_version', source)

    def test_airband_validator_uses_sdrcc_venv_not_system_python(self):
        from scripts.install import upgrade_radio_runtimes as runtime
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        import os

        with TemporaryDirectory() as tmp:
            project = Path(tmp)
            interpreter = project / "venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            interpreter.chmod(0o755)
            proposed = "traffic_voice:\n  backend:\n    version: 6.2.0\n"
            calls = []
            def validated(args, **kwargs):
                calls.append((args, kwargs))
                return SimpleNamespace(
                    returncode=0,
                    stdout='{"ok": true, "errors": []}\n',
                    stderr="")
            with patch.object(runtime.subprocess, "run", side_effect=validated):
                runtime.validate_airband_configuration(project, proposed)
            self.assertEqual(len(calls), 1)
            args, kwargs = calls[0]
            self.assertEqual(args[:2], [str(interpreter), "-I"])
            self.assertEqual(args[2], "-c")
            self.assertIn("from core import traffic_voice", args[3])
            self.assertEqual(kwargs["input"], proposed)
            self.assertEqual(kwargs["cwd"], project)
            self.assertTrue(kwargs["capture_output"])
            self.assertNotIn("pip", args)
            with patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1,
                    stdout='{"ok": false, "errors": ["invalid backend version"]}\n',
                    stderr="")):
                with self.assertRaisesRegex(RuntimeError, "invalid backend version"):
                    runtime.validate_airband_configuration(project, proposed)
            with patch.object(runtime.subprocess, "run", return_value=SimpleNamespace(
                    returncode=1, stdout="", stderr="No module named 'openpyxl'")):
                with self.assertRaisesRegex(RuntimeError, "openpyxl"):
                    runtime.validate_airband_configuration(project, proposed)
            interpreter.unlink()
            with patch.object(runtime.subprocess, "run") as process:
                with self.assertRaisesRegex(RuntimeError, "SDRCC Python venv is unavailable"):
                    runtime.validate_airband_configuration(project, proposed)
            process.assert_not_called()

    def test_readsb_upgrade_preflight_shows_actual_blocker(self):
        installed = "3.16.15"
        output = "readsb version: 3.16.15 wiedehopf git: cc0d099"
        def command(args, timeout=5):
            if "-W" in args:
                return "install ok installed\n"
            if "-S" in args:
                return "readsb: /usr/bin/readsb\n"
            raise AssertionError("Unexpected subprocess call")
        with patch.object(updates, "command", side_effect=command), \
             patch.object(updates.shutil, "which", return_value="/usr/bin/readsb"):
            eligible, reason = updates.readsb_upgrade_preflight(installed, output, "3.16.20")
            self.assertTrue(eligible, reason)
            self.assertIn("ready", reason)
            eligible, reason = updates.readsb_upgrade_preflight(
                installed, "readsb version: 3.16.15 wiedehopf git: other", "3.16.20")
            self.assertFalse(eligible)
            self.assertIn("commit differs", reason)
        with patch.object(updates, "command", return_value="no packages found matching readsb"), \
             patch.object(updates.shutil, "which", return_value="/usr/bin/readsb"):
            eligible, reason = updates.readsb_upgrade_preflight(installed, output, "3.16.20")
            self.assertFalse(eligible)
            self.assertIn("not registered as a Debian package", reason)
        with patch.object(updates, "command", side_effect=lambda args, timeout=5:
                          "install ok installed" if "-W" in args else
                          "otherpackage: /usr/local/bin/readsb"), \
             patch.object(updates.shutil, "which", return_value="/usr/local/bin/readsb"):
            eligible, reason = updates.readsb_upgrade_preflight(installed, output, "3.16.20")
            self.assertFalse(eligible)
            self.assertIn("not owned by the readsb package", reason)
        with patch.object(updates, "command") as command:
            eligible, reason = updates.readsb_upgrade_preflight(installed, output, "3.16.21")
            self.assertFalse(eligible)
            self.assertIn("needs review", reason)
            command.assert_not_called()

    def test_readsb_upgrade_worker_rechecks_same_ownership_guard(self):
        from scripts.install import upgrade_radio_runtimes as runtime
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertIn("readsb_upgrade_preflight(version, output, READSB_VERSION)", source)
        self.assertIn("raise RuntimeError(why)", source)

    def test_product_arguments_are_hardcoded_and_updates_are_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        app = (root / "dashboard/app.py").read_text()
        helper = (root / "scripts/sdrcc_external_update.py").read_text()
        ui = (root / "dashboard/static/js/external_updates.js").read_text()
        installer = (root / "install.sh").read_text()
        self.assertIn('ALLOWED = {"ais-catcher", "satdump", "readsb", "rtl-airband"}', helper)
        self.assertIn('if product not in {"ais-catcher", "satdump", "readsb", "rtl-airband"}:', app)
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
