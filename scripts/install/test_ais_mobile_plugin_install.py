#!/usr/bin/env python3
"""Read-only unit tests for the SDRCC AIS-Catcher map-plugin installer."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).with_name("install_ais_mobile_plugin.py")
spec = importlib.util.spec_from_file_location("sdrcc_ais_map_installer", MODULE)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class MapPluginInstallTests(unittest.TestCase):
    def setup_paths(self, root):
        source = root / "atis-highlight.pjs"
        source.write_bytes(b'// SDRCC-ATIS-MOBILE-BRIDGE\nconsole.info("test");\n')
        folder = root / "AIS-catcher" / "plugins"
        folder.mkdir(parents=True)
        return source, folder / "sdrcc-mobile-atis.pjs"

    def test_initial_install_and_second_install_idempotent(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = self.setup_paths(Path(name))
            self.assertFalse(helper.check(source, target))
            self.assertIn("restored", helper.install(source, target))
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertTrue(helper.check(source, target))
            self.assertIn("already installed", helper.install(source, target))

    def test_existing_non_sdrcc_plugin_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = self.setup_paths(Path(name))
            target.write_bytes(b"other author's plugin")
            with self.assertRaisesRegex(RuntimeError, "another author's"):
                helper.install(source, target)
            self.assertEqual(target.read_bytes(), b"other author's plugin")

    def test_existing_symlink_is_never_followed(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = self.setup_paths(Path(name))
            foreign = Path(name) / "foreign.pjs"
            foreign.write_bytes(b"do not touch")
            target.symlink_to(foreign)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                helper.install(source, target)
            self.assertEqual(foreign.read_bytes(), b"do not touch")

    def test_missing_directory_is_explicit(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = self.setup_paths(Path(name))
            target = Path(name) / "missing" / "sdrcc-mobile-atis.pjs"
            with self.assertRaisesRegex(RuntimeError, "directory"):
                helper.install(source, target)

    def test_invalid_marker_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            source, target = self.setup_paths(Path(name))
            source.write_bytes(b"other source")
            with self.assertRaisesRegex(RuntimeError, "marker"):
                helper.install(source, target)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
