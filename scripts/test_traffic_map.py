#!/usr/bin/env python3
"""Isolated read-only traffic-map normalization tests; no SDR or services."""
import unittest
from unittest.mock import patch

from core import traffic_map


class TrafficMapTests(unittest.TestCase):
    def test_vessel_with_no_position_is_not_plotted(self):
        self.assertEqual(traffic_map.vessels({"ships":[{"mmsi":"123456789","lat":51.9}]}), [])

    def test_vessel_freshness_validation_and_dedup(self):
        live={"mmsi":"123456789","shipname":"Test ship","lat":51.9,"lon":4.34,
              "validated":1,"last_signal":12,"sog":9.8,"cog":110}
        bad={**live,"mmsi":"987654321","last_signal":800}
        result=traffic_map.vessels({"ships":[live,live,bad,{**live,"mmsi":"123","lat":91}]})
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["id"],"123456789")
        self.assertEqual(result[0]["speed_knots"],9.8)

    def test_aircraft_position_freshness_and_altitude(self):
        items=[
            {"hex":"4ca123","flight":"KLM123 ","lat":51.91,"lon":4.31,
             "seen_pos":2,"alt_baro":9000,"track":200,"gs":180},
            {"hex":"4ca124","lat":51.9,"lon":4.3,"seen_pos":99},
            {"hex":"4ca125","lat":None,"lon":4.3,"seen_pos":2},
        ]
        planes=traffic_map.aircraft({"aircraft":items})
        self.assertEqual(len(planes),1)
        self.assertEqual(planes[0]["altitude_ft"],9000)
        self.assertEqual(planes[0]["name"],"KLM123")

    def test_invalid_coords_nonfinite_and_placeholder(self):
        self.assertEqual(traffic_map.vessels({"ships":[
            {"mmsi":"123456789","lat":"NaN","lon":4.3},
            {"mmsi":"123456788","lat":51.9,"lon":True},
        ]}),[])

    def test_sources_missing_are_empty_not_simulated(self):
        with patch.object(traffic_map.receiver_monitor,"_read_ais_ships",return_value=(None,None)), \
             patch.object(traffic_map.receiver_monitor,"_read_json_file",return_value=(None,None)), \
             patch.object(traffic_map.config,"get_home_position",return_value={"configured":False}):
            out=traffic_map.snapshot()
        self.assertTrue(out["read_only"])
        self.assertFalse(out["ais"]["available"])
        self.assertFalse(out["adsb"]["available"])
        self.assertEqual(out["ais"]["targets"],[])
        self.assertEqual(out["center"],[4.35,51.91])

    def test_live_both_and_home_location(self):
        with patch.object(traffic_map.receiver_monitor,"_read_ais_ships",return_value=(
                {"ships":[{"mmsi":"123456789","lat":51.91,"lon":4.32}]}, "local")), \
             patch.object(traffic_map.receiver_monitor,"_read_json_file",return_value=(
                {"aircraft":[{"hex":"4ca123","lat":51.92,"lon":4.33,"seen_pos":0}]}, "/mock")), \
             patch.object(traffic_map,"_fresh_adsb_file",return_value=True), \
             patch.object(traffic_map.config,"get_home_position",return_value={
                 "configured":True,"latitude":51.93,"longitude":4.28}):
            out=traffic_map.snapshot()
        self.assertEqual(out["ais"]["count"],1)
        self.assertEqual(out["adsb"]["count"],1)
        self.assertEqual(out["center"],[4.28,51.93])

    def test_stale_adsb_file_is_never_plotted(self):
        with patch.object(traffic_map.receiver_monitor,"_read_ais_ships",return_value=(None,None)), \
             patch.object(traffic_map.receiver_monitor,"_read_json_file",return_value=(
                 {"aircraft":[{"hex":"4ca123","lat":51.92,"lon":4.33,"seen_pos":0}]}, "/old")), \
             patch.object(traffic_map,"_fresh_adsb_file",return_value=False):
            out=traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"],0)
        self.assertFalse(out["adsb"]["available"])


if __name__ == "__main__":
    unittest.main()
