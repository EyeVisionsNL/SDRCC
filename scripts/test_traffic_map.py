#!/usr/bin/env python3
"""Isolated read-only traffic-map normalization tests; no SDR or services."""
import unittest
from unittest.mock import patch

from core import traffic_map


class TrafficMapTests(unittest.TestCase):
    def test_render_profiles_and_conservative_offshore_names(self):
        profiles = [
            ("WTG 014", None, 12, "offshore_wtg"),
            ("WTG-07", None, 11, "offshore_wtg"),
            ("WIND TURBINE 11", None, 12, "offshore_wtg"),
            ("P15", None, 11, "offshore_platform"),
            ("P15-A", None, 12, "offshore_platform"),
            ("K14", None, 11, "offshore_platform"),
            ("OFFSHORE PLATFORM P15", None, 12, "offshore_platform"),
            ("Q13A-A PLATFORM", 0, 12, "offshore_platform"),
            ("Q13A-A PLATFORM", 0, None, "vessel"),
            ("Q13A-A PLATFORM", 55, 5, "police"),
            ("PLATFORM SUPPLY", 70, 2, "cargo"),
            ("RPA12", None, None, "port_authority"),
            ("RPA 10", 55, 5, "port_authority"),
            ("P1", None, None, "vessel"),
            ("P15", None, None, "vessel"),
            ("P15", 55, 5, "police"),
            ("P1", 55, 5, "police"),
            ("P12", None, 5, "police"),
            ("POLITIE 3", None, 3, "police"),
            ("WTG 17", 70, 2, "cargo"),
            ("WIND SERVICE", 70, 2, "cargo"),
            ("P1500 CONTAINER", 70, 2, "cargo"),
            ("TEST TANKER", 80, 2, "tanker"),
            ("TEST CARGO", 70, None, "cargo"),
            ("UNKNOWN", None, None, "vessel"),
        ]
        for name, shiptype, shipclass, expected in profiles:
            with self.subTest(name=name):
                self.assertEqual(traffic_map.display_profile(name, shiptype, shipclass), expected)

    def test_offshore_facilities_never_generate_normal_ship_hulls(self):
        raw = {"lat": 51.9, "lon": 4.3, "validated": 1, "heading": 15,
               "to_bow": 90, "to_stern": 20, "to_port": 6, "to_starboard": 6}
        items = traffic_map.vessels({"ships": [
            {**raw, "mmsi": "992440001", "shipname": "WTG 19", "shipclass": 12},
            {**raw, "mmsi": "992440002", "shipname": "P15", "shipclass": 12},
            {**raw, "mmsi": "244120000", "shipname": "TEST TANKER", "shiptype": 80},
        ]})
        self.assertEqual([x["render_profile"] for x in items],
                         ["offshore_wtg", "offshore_platform", "tanker"])
        self.assertFalse(items[0]["hull_available"])
        self.assertFalse(items[1]["hull_available"])
        self.assertTrue(items[2]["hull_available"])

    def test_q13a_a_platform_mmsi_aton_without_heading(self):
        ship=traffic_map.vessels({"ships":[{
            "mmsi":"992456974","shipname":"Q13A-A PLATFORM",
            "shipclass":12,"shiptype":0,"status":15,
            "lat":52.19112,"lon":4.13618,"last_signal":855,
        }]})[0]
        self.assertEqual(ship["render_profile"],"offshore_platform")
        self.assertTrue(ship["is_offshore_structure"])
        self.assertFalse(ship["hull_available"])

    def test_rpa12_reference_dimensions_and_identity_protection(self):
        ship=traffic_map.vessels({"ships":[{
            "mmsi":"244050469","shipname":"RPA12","shipclass":5,
            "shiptype":99,"lat":51.93,"lon":4.34,"cog":186.3,
            "speed":4.5, "last_signal":10,
        }]})[0]
        self.assertEqual(ship["render_profile"],"port_authority")
        self.assertTrue(ship["hull_available"])
        self.assertEqual(ship["length_m"],28.8)
        self.assertEqual(ship["beam_m"],8.20)
        self.assertAlmostEqual(ship["hull_heading"],186.3)
        self.assertEqual(ship["hull_geometry_source"],
                         "Published dimensions; approximate AIS position offset")
        self.assertTrue(ship["hull_bearing_approximate"])
        self.assertAlmostEqual(ship["to_bow"],14.39)
        self.assertAlmostEqual(ship["to_stern"],14.39)
        other=traffic_map.vessels({"ships":[{
            "mmsi":"244050468","shipname":"RPA12","shipclass":5,
            "shiptype":99,"lat":51.93,"lon":4.34,"cog":186.3,
            "speed":4.5,
        }]})[0]
        self.assertEqual(other["render_profile"],"port_authority")
        self.assertFalse(other["hull_available"])
        self.assertIsNone(other["hull_geometry_source"])
        no_course=traffic_map.vessels({"ships":[{
            "mmsi":"244050469","shipname":"RPA 12","shipclass":5,
            "shiptype":99,"lat":51.93,"lon":4.34,"speed":0,
        }]})[0]
        self.assertFalse(no_course["hull_available"])
        with_ais=traffic_map.vessels({"ships":[{
            "mmsi":"244050469","shipname":"RPA12","shipclass":5,
            "shiptype":55,"lat":51.93,"lon":4.34,"heading":85,
            "to_bow":20,"to_stern":8,"to_port":4,"to_starboard":4,
        }]})[0]
        self.assertTrue(with_ais["hull_available"])
        self.assertEqual(with_ais["hull_geometry_source"],"AIS dimensions")
        self.assertEqual(with_ais["length_m"],28)

    def test_entire_confirmed_rpa_fleet_mmsi_classification(self):
        known = [
            ("246537000", "RPA 6", 26.0, 6.0),
            ("244050426", "RPA10", 29.0, 8.0),
            ("244100055", "RPA 11", 28.0, 8.0),
            ("244050469", "RPA12", 28.78, 8.20),
            ("244757000", "RPA 16", 31.33, 8.22),
        ]
        self.assertEqual(len(traffic_map._RPA_FLEET_MMSI), 5)
        for mmsi, name, length, beam in known:
            with self.subTest(mmsi=mmsi):
                self.assertEqual(
                    traffic_map.display_profile(
                        name, 55, 5, mmsi=mmsi), "port_authority")
                self.assertEqual(
                    traffic_map.display_profile(
                        "UNKNOWN", 55, 5, mmsi=mmsi), "port_authority")
                vessel = traffic_map.vessels({"ships": [{
                    "mmsi":mmsi, "shipname":name, "shiptype":99,
                    "shipclass":5, "lat":51.9, "lon":4.3,
                    "cog":135.0, "speed":5.5,
                }]})[0]
                self.assertEqual(vessel["render_profile"], "port_authority")
                self.assertTrue(vessel["hull_available"])
                self.assertAlmostEqual(vessel["length_m"],round(length,1))
                self.assertAlmostEqual(vessel["beam_m"],round(beam,1))
                self.assertEqual(vessel["hull_geometry_source"],
                                 "Published dimensions; approximate AIS position offset")
                self.assertTrue(vessel["hull_bearing_approximate"])
                # No made-up dimensions if only the MMSI matches.
                unnamed = traffic_map.vessels({"ships": [{
                    "mmsi":mmsi, "shipname":"UNKNOWN", "shiptype":55,
                    "shipclass":5, "lat":51.9, "lon":4.3, "cog":135, "speed":5,
                }]})[0]
                self.assertEqual(unnamed["render_profile"], "port_authority")
                self.assertFalse(unnamed["hull_available"])
        for name in ("RPA1","RPA 8","RPA 13","RPA 15","RPA 20","RPA ZERO"):
            self.assertEqual(traffic_map.display_profile(name,None,5),
                             "port_authority")

    def test_rpa_identity_safety_and_ais_dimensions_take_precedence(self):
        # MMSI 246537000 formerly belonged to police vessel P5.
        self.assertEqual(traffic_map.display_profile(
            "P5", 55, 5, mmsi="246537000"), "police")
        self.assertEqual(traffic_map.display_profile(
            "WATERPOLITIE P5", 55, 5, mmsi="246537000"), "police")
        self.assertEqual(traffic_map.display_profile(
            "RPA 6", 55, 12, mmsi="246537000"), "vessel")
        self.assertEqual(traffic_map.display_profile(
            "CARGO", 70, 2, mmsi="246537000"), "cargo")
        self.assertEqual(traffic_map.display_profile(
            "RPA 10", 55, 5, mmsi="244050426"), "port_authority")
        wrong = traffic_map.vessels({"ships": [{
            "mmsi":"244050426", "shipname":"RPA 11",
            "shipclass":5,"lat":51.9,"lon":4.3,"speed":5, "cog":135,
        }]})[0]
        self.assertFalse(wrong["hull_available"])
        unknown = traffic_map.vessels({"ships": [{
            "mmsi":"244070288", "shipname":"RPA13",
            "shipclass":5,"lat":51.9,"lon":4.3,"speed":5,"cog":135,
        }]})[0]
        self.assertEqual(unknown["render_profile"], "port_authority")
        self.assertFalse(unknown["hull_available"])
        real_ais = traffic_map.vessels({"ships": [{
            "mmsi":"244100055","shipname":"RPA11",
            "shipclass":5,"lat":51.9,"lon":4.3,"heading":280,
            "to_bow":18,"to_stern":6,"to_port":4.4,"to_starboard":4.4,
        }]})[0]
        self.assertTrue(real_ais["hull_available"])
        self.assertEqual(real_ais["hull_geometry_source"],"AIS dimensions")
        self.assertEqual(real_ais["length_m"],24)
        no_bearing = traffic_map.vessels({"ships": [{
            "mmsi":"244757000", "shipname":"RPA16",
            "shipclass":5,"lat":51.9,"lon":4.3, "speed":0,
        }]})[0]
        self.assertFalse(no_bearing["hull_available"])

    def test_platform_p15_c_real_ais_type_99_snapshot(self):
        # Screenshot from AIS-Catcher, 2026-10-23: P15 C is type 99 Other,
        # not an AtoN, with steady destination and speed zero.
        result = traffic_map.vessels({"ships": [{
            "mmsi": "245453000", "shipname": "PLATFORM P15 C",
            "shipclass": 0, "shiptype": 99, "callsign": "PCQK",
            "lat": 52.12, "lon": 4.10, "last_signal": 1754,
            "speed": 0, "status": 6, "destination": "STEADY OBJECT",
            "to_bow": 38, "to_stern": 11, "to_port": 8,
            "to_starboard": 8, "heading": 165,
        }]})[0]
        self.assertEqual(result["id"], "245453000")
        self.assertEqual(result["render_profile"], "offshore_platform")
        self.assertTrue(result["is_offshore_structure"])
        self.assertFalse(result["hull_available"])
        self.assertEqual(result["shiptype"], 99)
        self.assertEqual(result["destination"], "STEADY OBJECT")

    def test_p15_police_and_moving_boats_never_become_platforms(self):
        self.assertEqual(traffic_map.display_profile(
            "P15", 55, 5, "6", mmsi="244600015",
            speed_knots=0, destination="STEADY OBJECT"), "police")
        self.assertEqual(traffic_map.display_profile(
            "PLATFORM P15 C", 55, 5, "6", mmsi="244600015",
            speed_knots=0, destination="STEADY OBJECT"), "police")
        self.assertEqual(traffic_map.display_profile(
            "P15", 99, 0, "6", mmsi="245453000",
            speed_knots=0, destination="STEADY OBJECT"), "vessel")
        self.assertEqual(traffic_map.display_profile(
            "PLATFORM P15 C", 99, 0, "0", mmsi="245453000",
            speed_knots=8, destination="STEADY OBJECT"), "vessel")
        self.assertEqual(traffic_map.display_profile(
            "PLATFORM SERVICE", 70, 2, "6", mmsi="244900001",
            speed_knots=0, destination="STEADY OBJECT"), "cargo")
        self.assertEqual(traffic_map.display_profile(
            "PLATFORM P15 C", 99, 0, "0", mmsi="245453000",
            speed_knots=0, destination="STEADY OBJECT"), "offshore_platform")
        self.assertEqual(traffic_map.display_profile(
            "PLATFORM P15 C", 99, 0, "6", mmsi="245453000",
            speed_knots=None, destination="STEADY OBJECT"), "vessel")

    def test_mstx_names_and_callsigns_are_water_taxis(self):
        for name in ("MSTX 12","MSTX12","MSTX-13","mstx 31","MSTX/10"):
            with self.subTest(name=name):
                self.assertEqual(traffic_map.display_profile(name,1900,7),"watertaxi")
        self.assertEqual(traffic_map.display_profile(
            "FAST WATER TAXI",1900,7,callsign="MSTX 12"),"watertaxi")
        for name in ("AMSTX 12","MSTXELLENT","OTHER FAST FERRY"):
            with self.subTest(name=name):
                self.assertEqual(traffic_map.display_profile(name,1900,7),"vessel")
        self.assertEqual(traffic_map.display_profile("MSTX 12",55,5),"police")
        self.assertEqual(traffic_map.display_profile(
            "MSTX 12",1900,12,mmsi="992440001"),"vessel")

    def test_mstx_12_real_11m_dimensions_are_preserved(self):
        item=traffic_map.vessels({"ships":[{
            "mmsi":"244020742","shipname":"MSTX 12","callsign":"PD3993",
            "shiptype":1900,"shipclass":7,"lat":51.91,"lon":4.35,
            "speed":19.7,"cog":86.3,"to_bow":8,"to_stern":3,
            "to_port":1.5,"to_starboard":1.5,
        }]})[0]
        self.assertEqual(item["render_profile"],"watertaxi")
        self.assertEqual(item["length_m"],11)
        self.assertEqual(item["beam_m"],3)
        self.assertTrue(item["hull_available"])
        self.assertAlmostEqual(item["hull_heading"],86.3)
        self.assertFalse(item["is_offshore_structure"])

    def test_krve_hsc_names_and_ais_precedence(self):
        for name in ("KRVE 65", "KRVE65", "krve-31", "K.R.V.E. 62", "KRVE/80"):
            with self.subTest(name=name):
                self.assertEqual(
                    traffic_map.display_profile(name, 1900, 7), "krve")
        self.assertEqual(traffic_map.display_profile(
            "CREW TENDER", 40, None, callsign="KRVE 61"), "krve")
        self.assertEqual(traffic_map.display_profile(
            "KRVE 65", None, 7), "krve")
        for name in ("AKRVE 65", "KRVELESS", "KRVEBOAT"):
            self.assertEqual(traffic_map.display_profile(name, 1900, 7), "vessel")
        self.assertEqual(traffic_map.display_profile(
            "KRVE 65", 52, 5), "tug",
            "non-HSC KRVE boats must retain existing classification")
        self.assertEqual(traffic_map.display_profile(
            "KRVE 65", 55, 5), "police")
        self.assertEqual(traffic_map.display_profile(
            "KRVE 65", 1900, 12, mmsi="992440001"), "vessel")
        self.assertEqual(traffic_map.display_profile(
            "MSTX 12", 1900, 7), "watertaxi")

    def test_krve_hsc_short_real_ais_hull(self):
        krve=traffic_map.vessels({"ships":[{
            "mmsi":"244456065","shipname":"KRVE 65",
            "shiptype":1900,"shipclass":7,"lat":51.93,"lon":4.35,
            "speed":13.4,"cog":75.0,"to_bow":7,"to_stern":3,
            "to_port":1.8,"to_starboard":1.8,
        }]})[0]
        self.assertEqual(krve["render_profile"],"krve")
        self.assertTrue(krve["hull_available"])
        self.assertEqual(krve["length_m"],10)
        self.assertEqual(krve["beam_m"],3.6)
        self.assertFalse(krve["is_offshore_structure"])

    def test_class_b_recreation_profile_is_strictly_scoped(self):
        examples=[
            ("PLEASURE 1",3,37,"pleasure"),
            ("SAILING YACHT",3,36,"pleasure"),
            ("MY BOAT",3,None,"pleasure"),
            ("MY BOAT",3,0,"pleasure"),
            ("MY BOAT",3,99,"pleasure"),
            ("P15",3,99,"vessel"),
            ("P1",3,37,"vessel"),
            ("CLASS B TUG",3,52,"tug"),
            ("CLASS B TANKER",3,80,"tanker"),
            ("CLASS B CARGO",3,70,"cargo"),
            ("POLICE",3,55,"police"),
            ("MSTX 12",3,37,"watertaxi"),
            ("KRVE 65",3,36,"vessel"),
            ("RPA 12",3,37,"port_authority"),
            ("MY BOAT",3,60,"vessel"),
            ("MY BOAT",2,37,"cargo"),
            ("P15",12,37,"offshore_platform"),
        ]
        for name,cls,kind,expected in examples:
            with self.subTest(name=name,cls=cls,kind=kind):
                self.assertEqual(traffic_map.display_profile(
                    name,kind,cls),expected)

    def test_pleasure_fallback_preserves_existing_vessel_geometry(self):
        all_ships=[
            {"mmsi":"244901101","shipname":"PLEASURE 1","shipclass":3,
             "shiptype":37,"lat":51.9,"lon":4.3,"speed":3,"cog":76},
            {"mmsi":"244901102","shipname":"PLEASURE 2","shipclass":3,
             "shiptype":36,"lat":51.91,"lon":4.31,"heading":190,"speed":0,
             "length":9,"width":3.4},
            {"mmsi":"244901103","shipname":"PLEASURE 3","shipclass":3,
             "lat":51.92,"lon":4.32,"speed":0},
            {"mmsi":"244901104","shipname":"PLEASURE 4","shipclass":3,
             "shiptype":37,"lat":51.93,"lon":4.33,"heading":90,
             "to_bow":6,"to_stern":2,"to_port":1.4,"to_starboard":1.5},
            {"mmsi":"244901105","shipname":"TUG","shipclass":5,
             "shiptype":52,"lat":51.93,"lon":4.35},
            {"mmsi":"244901106","shipname":"CARGO","shipclass":2,
             "shiptype":70,"lat":51.93,"lon":4.36,"heading":90},
        ]
        rows=traffic_map.vessels({"ships":all_ships})
        self.assertEqual([row["render_profile"] for row in rows],
                         ["pleasure"]*4+["tug","cargo"])
        self.assertEqual([row["hull_available"] for row in rows],
                         [True,True,True,True,False,False])
        self.assertEqual((rows[0]["length_m"],rows[0]["beam_m"]),(11,3.2))
        self.assertEqual((rows[0]["to_bow"],rows[0]["to_stern"]),(5.5,5.5))
        self.assertIn("Illustrative",rows[0]["hull_geometry_source"])
        self.assertEqual(rows[0]["hull_heading"],76)
        self.assertTrue(rows[0]["hull_bearing_approximate"])
        self.assertEqual((rows[1]["length_m"],rows[1]["beam_m"]),(9,3.4))
        self.assertEqual(rows[1]["hull_heading"],190)
        self.assertFalse(rows[1]["hull_bearing_approximate"])
        self.assertEqual(rows[2]["hull_heading"],0)
        self.assertTrue(rows[2]["hull_bearing_approximate"])
        self.assertEqual((rows[3]["to_bow"],rows[3]["to_stern"],
                          rows[3]["to_port"],rows[3]["to_starboard"]),
                         (6,2,1.4,1.5))
        self.assertEqual(rows[3]["hull_geometry_source"],"AIS dimensions")
        self.assertFalse(rows[3]["hull_bearing_approximate"])
        self.assertIsNone(rows[4]["hull_geometry_source"])
        self.assertIsNone(rows[5]["hull_geometry_source"])

    def test_tug_classification_by_type_status_and_name(self):
        cases = [
            ("MULTRATUG 9", None, None, None, "tug"),
            ("SMIT SWIFT", None, None, None, "tug"),
            ("HARBOUR TUG", None, None, None, "tug"),
            ("SLEEPBOOT 1", None, None, None, "tug"),
            ("FREEDOM", 52, None, None, "tug"),
            ("FREEDOM", 31, None, None, "tug"),
            ("FREEDOM", None, None, "11", "tug"),
            ("FREEDOM", None, None, "Tugging", "tug"),
            ("CARGO TOW", 70, 2, "Pushing", "tug"),
            ("TUGGER CARGO", 70, 2, None, "cargo"),
            ("WTG 13", 52, None, "Towing", "tug"),
            ("P15", 52, None, "Towing", "tug"),
        ]
        for name, kind, cls, status, expected in cases:
            with self.subTest(name=name,status=status):
                self.assertEqual(traffic_map.display_profile(name,kind,cls,status),expected)

    def test_police_vs_platform_ais_metadata_and_moving_police_traces(self):
        common = {"lat": 51.91, "lon": 4.35, "heading": 90,
                  "to_bow": 13, "to_stern": 7, "to_port": 2.5,
                  "to_starboard": 2.5, "validated": 1}
        rows = traffic_map.vessels({"ships": [
            {**common, "mmsi": "244600001", "shipname": "P1",
             "shiptype": 55, "shipclass": 5, "speed": 14},
            {**common, "mmsi": "244600015", "shipname": "P15",
             "shiptype": 55, "shipclass": 5, "speed": 8},
            {**common, "mmsi": "244600017", "shipname": "HARBOUR",
             "callsign": "P17", "shipclass": 5, "speed": 8},
            {**common, "mmsi": "992440015", "shipname": "P15",
             "shipclass": 12, "speed": 0},
            {**common, "mmsi": "244600099", "shipname": "P15",
             "shipclass": 3, "speed": 5},
            {**common, "mmsi": "244600098", "shipname": "PLATFORM SERVICE",
             "shiptype": 70, "shipclass": 2, "speed": 6},
        ]})
        self.assertEqual([row["render_profile"] for row in rows],
                         ["police","police","police","offshore_platform","vessel","cargo"])
        self.assertEqual([row["hull_available"] for row in rows],
                         [True, True, True, False, True, True])
        self.assertTrue(all(not row["is_offshore_structure"] for row in rows[:3]))
        self.assertTrue(all(row["is_offshore_structure"] is False for row in rows[4:]))
        self.assertEqual(traffic_map.display_profile(
            "P15", 55, 5, mmsi="244600015", callsign="P15"), "police")
        self.assertEqual(traffic_map.display_profile(
            "P15", None, 12, mmsi="992440015"), "offshore_platform")

    def test_tug_vessel_profile_reports_navigation_status(self):
        row=traffic_map.vessels({"ships":[{
            "mmsi":"244555000","shipname":"TEST","shiptype":52,
            "status":"Tugging","lat":51.9,"lon":4.3,
            "to_bow":11,"to_stern":8,"to_port":3,"to_starboard":3,
            "heading":78,
        }]})[0]
        self.assertEqual(row["render_profile"],"tug")
        self.assertTrue(row["hull_available"])
        self.assertEqual(row["nav_status"],"Tugging")

    def test_ais_catcher_native_track_is_real_bounded_and_ordered(self):
        now=2000000000
        raw={"type":"Feature","geometry":{"type":"LineString",
             "coordinates":[[4.40,51.92],[4.38,51.92],[4.36,51.91],[4.30,51.90]]},
             "properties":{"mmsi":244555000,
                           "timestamps_start":[now-10,now-45,now-80,now-9999]}}
        with patch.object(traffic_map.receiver_monitor,"_read_json_url",
                          return_value=(raw,"loopback")) as reader, \
             patch.object(traffic_map.time,"time",return_value=now):
            result=traffic_map.track_snapshot("244555000")
        self.assertTrue(result["ok"])
        self.assertTrue(result["available"])
        self.assertEqual(result["point_count"],3)
        self.assertEqual(result["geojson"]["features"][0]["geometry"]["coordinates"],
                         [[4.36,51.91],[4.38,51.92],[4.4,51.92]])
        self.assertEqual(len(reader.call_args.args[0]),2)
        self.assertIn("/api/path.geojson?244555000",reader.call_args.args[0][0])
        self.assertFalse(traffic_map.track_snapshot("../etc/passwd")["ok"])
        with patch.object(traffic_map.receiver_monitor,"_read_json_url",
                          return_value=(None,None)):
            self.assertFalse(traffic_map.track_snapshot("244555000")["available"])

    def test_track_filters_invalid_points_and_breaks_bad_jumps(self):
        now=2000000000
        raw={"type":"Feature","geometry":{"type":"LineString",
             "coordinates":[[4.91,51.9],[4.90,51.9],[4.35,51.9],[4.34,51.9],
                            [None,51.9],[4.33,51.9]]},
             "properties":{"mmsi":244555000,
                           "timestamps_start":[now-10,now-20,now-30,now-40,
                                               now-50,now-60]}}
        with patch.object(traffic_map.receiver_monitor,"_read_json_url",
                          return_value=(raw,"loopback")), \
             patch.object(traffic_map.time,"time",return_value=now):
            result=traffic_map.track_snapshot("244555000")
        self.assertEqual(result["point_count"],5)
        self.assertEqual(len(result["geojson"]["features"]),2)

    def test_all_vessel_tracks_use_native_ais_catcher_and_ignore_structures(self):
        now = 2000000000
        ais = {"ships": [
            {"mmsi": "244555000", "shipname": "MULTRATUG 9",
             "lat": 51.90, "lon": 4.3, "shipclass": 5, "last_signal": 10},
            {"mmsi": "244555001", "shipname": "CARGO TEST",
             "lat": 51.92, "lon": 4.4, "shipclass": 2, "last_signal": 10},
            {"mmsi": "992440001", "shipname": "WTG 19",
             "lat": 51.93, "lon": 4.5, "shipclass": 12, "last_signal": 10},
        ]}
        def feature(mmsi, coords, times):
            return {"type": "Feature", "geometry": {"type": "LineString",
                    "coordinates": coords},
                    "properties": {"mmsi": int(mmsi), "timestamps_start": times}}
        payload = {"type": "FeatureCollection", "features": [
            feature("244555000", [[4.32,51.9],[4.31,51.9],[4.30,51.9]],
                    [now-10,now-30,now-60]),
            feature("244555001", [[4.45,51.9],[4.43,51.9]],
                    [now-10,now-35]),
            feature("992440001", [[4.50,51.9],[4.51,51.9]],
                    [now-10,now-30]),
            feature("244999999", [[4.40,51.9],[4.41,51.9]],
                    [now-10,now-30]),
        ]}
        with patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(payload, "loopback")) as reader, \
             patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(ais, "loopback")), \
             patch.object(traffic_map.time, "time", return_value=now):
            result = traffic_map.all_tracks_snapshot()
        self.assertTrue(result["available"])
        self.assertEqual(result["track_count"], 2)
        self.assertEqual(result["point_count"], 5)
        self.assertEqual(len(result["geojson"]["features"]), 2)
        self.assertEqual(
            [row["properties"]["mmsi"] for row in result["geojson"]["features"]],
            ["244555000", "244555001"])
        self.assertEqual(result["geojson"]["features"][0]["properties"]["shipclass"], 5)
        self.assertEqual(result["geojson"]["features"][1]["properties"]["shipclass"], 2)
        self.assertEqual(result["geojson"]["features"][0]["geometry"]["coordinates"],
                         [[4.3,51.9],[4.31,51.9],[4.32,51.9]])
        self.assertIn("/api/allpath.geojson", reader.call_args.args[0][0])

    def test_all_tracks_reject_invalid_source_and_break_long_gaps(self):
        now = 2000000000
        ais = {"ships": [{"mmsi": "244555000", "shipname": "MULTRATUG 9",
                          "lat": 51.9, "lon": 4.3, "last_signal": 5}]}
        payload = {"type": "FeatureCollection", "features": [{
            "type": "Feature", "geometry": {"type": "LineString",
                "coordinates": [[4.35,51.9],[4.34,51.9],[4.33,51.9],
                                [4.32,51.9],[4.31,51.9],[4.3,51.9]]},
            "properties": {"mmsi": 244555000,
                "timestamps_start": [now-10,now-20,now-1200,now-1210,now-7000,now-7010]},
        }]}
        with patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(payload,"local")), \
             patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(ais,"local")), \
             patch.object(traffic_map.time,"time",return_value=now):
            result = traffic_map.all_tracks_snapshot(minutes=60)
        self.assertEqual(result["track_count"], 1)
        self.assertEqual(result["point_count"], 4)
        self.assertEqual(len(result["geojson"]["features"]), 2)
        with patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(None, None)):
            offline = traffic_map.all_tracks_snapshot()
        self.assertFalse(offline["available"])
        self.assertEqual(offline["track_count"], 0)

    def test_track_duration_minutes_one_fifteen_sixty_and_bounds(self):
        now = 2000000000
        offsets = [10, 30, 70, 80, 1600, 1620, 3540, 3550]
        raw = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates":
                         [[4.30 + idx * .001, 51.9] for idx in range(len(offsets))]},
            "properties": {"mmsi": 244555000,
                           "timestamps_start": [now - value for value in offsets]},
        }]}
        ais = {"ships": [{"mmsi": "244555000", "shipname": "TEST TUG",
                          "lat": 51.9, "lon": 4.3, "last_signal": 10}]}
        with patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(raw, "loopback")), \
             patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(ais, "loopback")), \
             patch.object(traffic_map.time, "time", return_value=now):
            for minutes, points in [(1, 2), (15, 4), (60, 8), (0, 2), (99, 8)]:
                with self.subTest(minutes=minutes):
                    result = traffic_map.all_tracks_snapshot(minutes=minutes)
                    self.assertEqual(result["track_count"], 1)
                    self.assertEqual(result["point_count"], points)

    def test_vessel_with_no_position_is_not_plotted(self):
        self.assertEqual(traffic_map.vessels({"ships":[{"mmsi":"123456789","lat":51.9}]}), [])

    def test_vessel_freshness_validation_and_dedup(self):
        live={"mmsi":"123456789","shipname":"Test ship","lat":51.9,"lon":4.34,
              "validated":1,"last_signal":12,"sog":9.8,"cog":110}
        bad={**live,"mmsi":"987654321","last_signal":90000}
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
        self.assertIsNone(out["station"])

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
        self.assertEqual(out["station"]["lon"], 4.28)
        self.assertEqual(out["station"]["lat"], 51.93)
        self.assertEqual(out["station"]["name"], "My station")

    def test_home_position_name_and_altitude_are_taken_from_station_config(self):
        with patch.object(traffic_map.receiver_monitor, "_read_ais_ships",
                          return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_file",
                          return_value=(None, None)), \
             patch.object(traffic_map.receiver_monitor, "_read_json_url",
                          return_value=(None, None)), \
             patch.object(traffic_map.config, "get_home_position",
                          return_value={"configured": True, "latitude": 51.907,
                                        "longitude": 4.321, "name": "VTS SDR station",
                                        "altitude_m": 12.5}):
            result = traffic_map.snapshot()
        self.assertEqual(result["station"]["name"], "VTS SDR station")
        self.assertEqual(result["station"]["altitude_m"], 12.5)
        self.assertEqual(result["center"], [4.321, 51.907])

    def test_stale_adsb_file_is_never_plotted(self):
        with patch.object(traffic_map.receiver_monitor,"_read_ais_ships",return_value=(None,None)), \
             patch.object(traffic_map.receiver_monitor,"_read_json_file",return_value=(
                 {"aircraft":[{"hex":"4ca123","lat":51.92,"lon":4.33,"seen_pos":0}]}, "/old")), \
             patch.object(traffic_map,"_fresh_adsb_file",return_value=False), \
             patch.object(traffic_map.receiver_monitor,"_read_json_url",return_value=(None,None)):
            out=traffic_map.snapshot()
        self.assertEqual(out["adsb"]["count"],0)
        self.assertFalse(out["adsb"]["available"])


    def test_historical_ais_display_is_distinct_from_live_alert_freshness(self):
        """Retained AIS-Catcher targets remain visible but flagged as historical."""
        base = {"mmsi": "123456789", "lat": 51.9, "lon": 4.34, "validated": 1}
        rows = traffic_map.vessels({"ships": [
            {**base, "last_signal": 800},
            {**base, "mmsi": "987654321", "last_signal": 1914},
            {**base, "mmsi": "111222333", "validated": 0, "last_signal": 15},
            {**base, "mmsi": "111222334", "last_signal": 86401},
        ]})
        self.assertEqual([row["id"] for row in rows],
                         ["123456789", "987654321", "111222333"])
        self.assertFalse(rows[0]["position_stale"])
        self.assertTrue(rows[1]["position_stale"])
        self.assertEqual(rows[1]["age_seconds"], 1914)
        self.assertEqual(rows[1]["validation_state"], "verified")
        self.assertEqual(rows[2]["validation_state"], "unverified")
        self.assertEqual(traffic_map.AIS_LIVE_MAX_AGE, 1800)
        self.assertEqual(traffic_map.AIS_DISPLAY_MAX_AGE, 86400)

    def test_stale_target_is_not_live_emergency_or_atis_input(self):
        """The Map Lab display-only flag never makes a stale fix live."""
        raw = {"ships": [{"mmsi": "246333000", "shipname": "KNRM JEANINE PARQUI",
                           "lat": 51.9767, "lon": 4.1254, "last_signal": 1914,
                           "validated": 1, "speed": 0.0}]}
        rows = traffic_map.vessels(raw)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["position_stale"])
        self.assertEqual(rows[0]["id"], "246333000")
        self.assertEqual(rows[0]["name"], "KNRM JEANINE PARQUI")

    def test_unverified_ais_visible_but_flagged(self):
        """The viewer can show unverified AIS just as AIS-Catcher does;
        ATIS and emergency-monitor validation remain entirely unchanged."""
        data = {"ships": [
            {"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
             "validated": 0, "last_signal": 8},
            {"mmsi": "123456788", "lat": 51.9, "lon": 4.4,
             "validated": 1, "last_signal": 8},
        ]}
        targets = traffic_map.vessels(data)
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0]["validation_state"], "unverified")
        self.assertEqual(targets[1]["validation_state"], "verified")


    def test_real_ship_offsets_for_hull(self):
        ship = {"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
                "validated": 1, "heading": 175, "cog": 170,
                "to_bow": 90, "to_stern": 35,
                "to_port": 8, "to_starboard": 9, "shipclass": 6,
                "shiptype": 80, "speed": 0.0}
        result = traffic_map.vessels({"ships": [ship]})[0]
        self.assertTrue(result["hull_available"])
        self.assertEqual(result["hull_heading"], 175)
        self.assertEqual(result["length_m"], 125)
        self.assertEqual(result["to_starboard"], 9)
        self.assertEqual(result["shipclass"], 6)
        self.assertEqual(result["shiptype"], 80)

    def test_no_dimensions_uses_fallback_symbol(self):
        ship = {"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
                "length": 90, "heading": 230}
        result = traffic_map.vessels({"ships": [ship]})[0]
        self.assertFalse(result["hull_available"])
        self.assertIsNone(result["to_bow"])
        self.assertEqual(result["length_m"], 90)

    def test_unknown_heading_needs_moving_course(self):
        base = {"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
                "to_bow": 45, "to_stern": 5,
                "to_port": 4, "to_starboard": 4,
                "heading": 511, "cog": 122}
        static = traffic_map.vessels({"ships": [{**base, "speed": 0}]})[0]
        moving = traffic_map.vessels({"ships": [{**base, "speed": 6}]})[0]
        self.assertFalse(static["hull_available"])
        self.assertTrue(moving["hull_available"])
        self.assertEqual(moving["hull_heading"], 122)

    def test_implausible_dimensions_never_make_enormous_hull(self):
        ship = {"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
                "heading": 90, "length": 87,
                "to_bow": 650, "to_stern": 10,
                "to_port": 20, "to_starboard": 20}
        result = traffic_map.vessels({"ships": [ship]})[0]
        self.assertFalse(result["hull_available"])
        self.assertEqual(result["length_m"], 87)

    def test_extended_vessel_details(self):
        raw = {"ships": [{"mmsi": "123456789", "lat": 51.9, "lon": 4.3,
                          "shipclass": 6, "shiptype": 80, "imo": 9876543,
                          "eni": "02345678", "destination": "ROTTERDAM",
                          "country": "NL", "status": 5, "draught": 7.2,
                          "to_bow": 70, "to_stern": 15,
                          "to_port": 6, "to_starboard": 7, "heading": 95}]}
        ship = traffic_map.vessels(raw)[0]
        self.assertEqual(ship["destination"], "ROTTERDAM")
        self.assertEqual(ship["imo"], "9876543")
        self.assertEqual(ship["eni"], "02345678")
        self.assertEqual(ship["nav_status"], "5")
        self.assertEqual(ship["beam_m"], 13)
        self.assertEqual(ship["draught_m"], 7.2)

    def test_extended_adsb_details(self):
        raw = {"aircraft": [{"hex": "4ca123", "lat": 51.9, "lon": 4.3,
                            "seen_pos": 1, "flight": "KLM123",
                            "r": "PH-BGX", "t": "B738", "ownOp": "KLM",
                            "desc": "Boeing 737-800", "squawk": "4720",
                            "baro_rate": -640}]}
        plane = traffic_map.aircraft(raw)[0]
        self.assertEqual(plane["registration"], "PH-BGX")
        self.assertEqual(plane["aircraft_type"], "B738")
        self.assertEqual(plane["operator"], "KLM")
        self.assertEqual(plane["description"], "Boeing 737-800")
        self.assertEqual(plane["squawk"], "4720")
        self.assertEqual(plane["baro_rate"], -640)

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
