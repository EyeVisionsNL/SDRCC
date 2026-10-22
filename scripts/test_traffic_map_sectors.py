#!/usr/bin/env python3
"""Offline tests for the installed AIS-Catcher VTS Rijnmond sector bridge."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core import traffic_map_sectors


def feature(name, channel):
    return {
        "type": "Feature",
        "properties": {"name": name, "vhfchannel": channel},
        "geometry": {"type": "Polygon", "coordinates": [[
            [4.3, 51.9], [4.4, 51.9], [4.4, 51.91], [4.3, 51.9]
        ]]},
    }


class SectorBridgeTests(unittest.TestCase):
    def test_reads_installed_plugin_literals_without_running_javascript(self):
        data = {"type": "FeatureCollection", "features": [feature("Sector Botlek", "61")]}
        plugin = ("// v17.1\nvar RWS_DATA = " + json.dumps(data) + ";\n"
                  + "var COLORS = {'61': '#e5007e', '10':'#ff3030'};\n"
                  + "RWS_DATA.features.push("
                  + json.dumps(feature("Sector Hartelkanaal", "10")) + ");\n"
                  + "throw new Error('this JavaScript must never execute');\n")
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "vts-sectoren.pjs"
            path.write_text(plugin, encoding="utf-8")
            result = traffic_map_sectors.snapshot(path)
        self.assertTrue(result["available"])
        self.assertEqual(result["count"], 2)
        features = result["geojson"]["features"]
        self.assertEqual([f["properties"]["vhfchannel"] for f in features], ["61", "10"])
        self.assertEqual([f["properties"]["color"] for f in features], ["#e5007e", "#ff3030"])
        self.assertEqual(features[0]["properties"]["source"], "Rijkswaterstaat vts-deelsector_v")

    def test_missing_plugin_is_optional_and_does_not_break_map(self):
        with TemporaryDirectory() as tmp:
            response = traffic_map_sectors.snapshot(Path(tmp) / "absent.pjs")
        self.assertTrue(response["ok"])
        self.assertFalse(response["available"])
        self.assertEqual(response["geojson"]["features"], [])

    def test_rejects_unparseable_source_and_never_returns_random_features(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.pjs"
            path.write_text("var RWS_DATA = {bad JS expression}", encoding="utf-8")
            response = traffic_map_sectors.snapshot(path)
        self.assertFalse(response["available"])
        self.assertEqual(response["count"], 0)

    def test_refuses_unbounded_plugin_file(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "too_large.pjs"
            path.write_text("A" * (traffic_map_sectors._MAX_BYTES + 1))
            self.assertFalse(traffic_map_sectors.snapshot(path)["available"])


if __name__ == "__main__":
    unittest.main()
