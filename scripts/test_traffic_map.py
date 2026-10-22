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
        bad={**live,"mmsi":"987654321","last_signal":1900}
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
             patch.object(traffic_map.receiver_monitor,"_read_json_url",return_value=(None,None)), \
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
             patch.object(traffic_map,"_fresh_adsb_file",return_value=False), \
             patch.object(traffic_map.receiver_monitor,"_read_json_url",return_value=(None,None)):
            out=traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"],0)
        self.assertFalse(out["adsb"]["available"])


    def test_history_window_matches_ais_receiver_monitor(self):
        """A ship seen ten minutes ago should appear, one older than half an hour should not."""
        base = {"mmsi": "123456789", "lat": 51.9, "lon": 4.34, "validated": 1}
        rows = traffic_map.vessels({"ships": [
            {**base, "last_signal": 800},
            {**base, "mmsi": "987654321", "last_signal": 1801},
            {**base, "mmsi": "111222333", "validated": 0, "last_signal": 15},
        ]})
        self.assertEqual([row["id"] for row in rows], ["123456789"])
        self.assertEqual(traffic_map.AIS_MAX_AGE, 1800)

    def test_readsb_non_icao_and_last_position(self):
        """Recent position retained by tar1090 should be visible; old positions must not."""
        items = [
            {"hex": "~4ca123", "flight": "TEST123", "seen": 4,
             "lastPosition": {"lat": 51.93, "lon": 4.3, "seen_pos": 35}},
            {"hex": "4ca124", "seen": 1,
             "lastPosition": {"lat": 51.95, "lon": 4.4, "seen_pos": 85}},
        ]
        rows = traffic_map.aircraft({"aircraft": items})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "~4ca123")

    def test_local_tar1090_fallback_for_missing_positions(self):
        """Fallback to live loopback tar1090 if readsb's local file plots nothing."""
        local = {"aircraft": [{"hex": "4ca123", "seen": 0}]}
        web = {"now": 5000, "aircraft": [
            {"hex": "4ca123", "lat": 51.91, "lon": 4.31, "seen_pos": 3},
            {"hex": "4ca124", "lat": 51.91, "lon": 4.41, "seen_pos": 4},
        ]}
        with patch.object(traffic_map.receiver_monitor, "_read_ais_ships", return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_file",
                          return_value=(local, "/run/readsb/aircraft.json")), \
             patch.object(traffic_map, "_fresh_adsb_file", return_value=True), \
             patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(web, traffic_map.ADSB_HTTP_URLS[0])) as http, \
             patch.object(traffic_map.time, "time", return_value=5010):
            out = traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"], 2)
        self.assertEqual(out["adsb"]["source_count"], 2)
        self.assertTrue(out["adsb"]["available"])
        http.assert_called_once_with(traffic_map.ADSB_HTTP_URLS)

    def test_stale_http_response_does_not_invent_live_aircraft(self):
        with patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_file",
                          return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=({"now": 4900, "aircraft": [
                              {"hex": "4ca123", "lat": 51.9, "lon": 4.3, "seen_pos": 3},
                          ]}, traffic_map.ADSB_HTTP_URLS[0])), \
             patch.object(traffic_map.time, "time", return_value=5000):
            out = traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"], 0)
        self.assertFalse(out["adsb"]["available"])

    def test_local_aircraft_does_not_fetch_http_unnecessarily(self):
        local = {"aircraft": [
            {"hex": "4ca123", "lat": 51.9, "lon": 4.3, "seen_pos": 5},
        ]}
        with patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_file",
                          return_value=(local, "/run/readsb/aircraft.json")), \
             patch.object(traffic_map, "_fresh_adsb_file", return_value=True), \
             patch.object(traffic_map.receiver_monitor, "_read_json_url") as http:
            out = traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"], 1)
        http.assert_not_called()



if __name__ == "__main__":
    unittest.main()
