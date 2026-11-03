#!/usr/bin/env python3
"""Offline regression tests for SDRCC's read-only local external software inventory."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest import TestCase, main
from unittest.mock import patch
from core import external_updates as inventory


class InventoryTests(TestCase):
    def test_missing_optional_components(self):
        with patch.object(inventory.shutil, "which", return_value=None), \
             patch.object(inventory, "AIRBAND_BINARY", Path("/nonexistent/sdrcc-test-airband")):
            data = inventory.snapshot(refresh=True)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["software"]), 4)
        self.assertTrue(all(row["status"] == "missing" for row in data["software"]))

    def test_local_version_detection_without_upstream_access(self):
        binaries = {"AIS-catcher": "/usr/bin/AIS-catcher", "satdump": "/usr/bin/satdump",
                    "readsb": "/usr/bin/readsb"}

        def command(args, timeout=5):
            return {"AIS-catcher": "AIS-catcher v0.70", "satdump": "SatDump version 1.2.2",
                    "readsb": "readsb version: 3.16.20"}.get(Path(args[0]).name, "")

        with TemporaryDirectory() as directory:
            binary = Path(directory) / "rtl_airband"
            binary.write_text("stub")
            provenance = Path(directory) / "BUILD-PROVENANCE"
            provenance.write_text("RTLSDR-Airband 6.2.0\n")
            with patch.object(inventory.shutil, "which", side_effect=binaries.get), \
                 patch.object(inventory, "command", side_effect=command), \
                 patch.object(inventory, "AIRBAND_BINARY", binary), \
                 patch.object(inventory, "AIRBAND_PROVENANCE", provenance):
                rows = inventory.snapshot()["software"]
        self.assertEqual({row["id"]: row["installed"] for row in rows},
                         {"ais-catcher": "0.70", "satdump": "1.2.2",
                          "readsb": "3.16.20", "rtl-airband": "6.2.0"})
        self.assertTrue(all(row["status"] == "installed" for row in rows))
        self.assertTrue(all("can_install" not in row and "latest" not in row for row in rows))

    def test_unverified_binary_is_not_reported_as_current(self):
        with patch.object(inventory.shutil, "which",
                          side_effect=lambda name: "/usr/bin/readsb" if name == "readsb" else None), \
             patch.object(inventory, "command", return_value="unrecognised"), \
             patch.object(inventory, "AIRBAND_BINARY", Path("/nonexistent/sdrcc-test-airband")):
            rows = inventory.snapshot()["software"]
        self.assertEqual(next(row for row in rows if row["id"] == "readsb")["status"], "unknown")


if __name__ == "__main__":
    main()
