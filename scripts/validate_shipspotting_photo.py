#!/usr/bin/env python3
"""Offline regression checks for Shipspotting and SDRCC photo source priority."""
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import traffic_voice_shipspotting as ship
from core import traffic_voice_vessel_photo as photos

MMSI = "367645050"
IMO = "8883563"
ENI = "02345678"
SMALL = "https://www.shipspotting.com/photos/small/1/7/4/2157471.jpg"
BIG = "https://www.shipspotting.com/photos/big/1/7/4/2157471.jpg"
DETAIL = """
<h2>Photo details</h2><p>Photographer:</p><a href="/photographers/15">dirk septer</a>
<h2>Vessel particulars</h2><p>Current name: SPIRIT OF GLACIER BAY</p>
<p>IMO: 8883563</p><p>MMSI: 367645050</p>
<img src="https://www.shipspotting.com/photos/small/1/7/4/2157471.jpg">
"""
SEARCH = '<a href="/photos/2157471"><img src="' + SMALL + '" alt="ship"></a>'


class ShipspottingTests(unittest.TestCase):
    def test_photo_link_and_thumbnail_restrictions(self):
        self.assertEqual(ship._photo_url("/photos/2157471?navList=gallery"),
                         "https://www.shipspotting.com/photos/2157471")
        self.assertEqual(ship._photo_url("https://evil.example/photos/2157471"), "")
        self.assertEqual(ship._thumbnail_url(SMALL), SMALL)
        self.assertEqual(ship._thumbnail_url(BIG), "")
        self.assertEqual(ship._thumbnail_url("https://evil.example/photos/small/2157471.jpg"), "")

    def test_search_results_and_verified_detail(self):
        links, previews = ship._search_links(SEARCH)
        self.assertEqual(links, ["https://www.shipspotting.com/photos/2157471"])
        self.assertEqual(previews[links[0]], SMALL)
        result = ship._detail(DETAIL, links[0], previews[links[0]],
                              MMSI, "SPIRIT OF GLACIER BAY", IMO, "", 500)
        self.assertIsNotNone(result)
        self.assertEqual(result["artist"], "© dirk septer")
        self.assertEqual(result["source"], "Shipspotting.com")
        self.assertEqual(result["page_url"], links[0])

    def test_mismatch_and_missing_credit_fail_closed(self):
        url = "https://www.shipspotting.com/photos/2157471"
        self.assertIsNone(ship._detail(DETAIL, url, SMALL,
                                       MMSI, "A different ship", "1234567", "", 500))
        self.assertIsNone(ship._detail(DETAIL.replace("Photographer:", "Author unknown:"),
                                       url, SMALL, MMSI, "SPIRIT OF GLACIER BAY", IMO, "", 500))
        self.assertIsNone(ship._detail(DETAIL.replace(SMALL, BIG), url, "",
                                       MMSI, "SPIRIT OF GLACIER BAY", IMO, "", 500))

    def test_imo_outweighs_stale_mmsi(self):
        url = "https://www.shipspotting.com/photos/2157471"
        found = ship._detail(DETAIL, url, SMALL, "999999999",
                             "SPIRIT OF GLACIER BAY", IMO, "", 500)
        self.assertIsNotNone(found)
        self.assertIsNone(ship._detail(DETAIL, url, SMALL, "999999999",
                                        "SPIRIT OF GLACIER BAY", "", "", 500))

    def test_eni_search_when_imo_gallery_empty(self):
        urls = []
        def get(url, cap):
            urls.append(url)
            if "/photos/gallery?" in url:
                return SEARCH if "eni=2345678" in url else ""
            return DETAIL.replace("MMSI: 367645050", "MMSI: 367645050 ENI: 02345678")
        with patch.object(ship, "_download", side_effect=get):
            found = ship.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO, ENI)
        self.assertIsNotNone(found)
        self.assertTrue(any("eni=2345678" in url for url in urls))

    def test_network_failure_falls_through(self):
        with patch.object(ship, "_download", side_effect=OSError("403 blocked")):
            self.assertIsNone(ship.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO))

    def test_on_demand_search(self):
        urls = []
        def get(url, cap):
            urls.append(url)
            return SEARCH if "/photos/gallery?" in url else DETAIL
        with patch.object(ship, "_download", side_effect=get):
            found = ship.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO)
        self.assertEqual(found["image_url"], SMALL)
        self.assertIn("/photos/gallery?", urls[0])
        self.assertIn("imo=8883563", urls[0])
        self.assertTrue(all("/photos/search?" not in url for url in urls))


class PriorityTests(unittest.TestCase):
    def setUp(self):
        photos._cache = {}
        self.cache = patch.object(photos, "_save", return_value=None)
        self.cache.start()

    def tearDown(self):
        self.cache.stop()
        photos._cache = None

    def test_source_order(self):
        calls = []
        def source(name, result):
            def inner(*args):
                calls.append(name)
                return {"ok": True, "source": name, "cached_at": 500} if result else None
            return inner
        with patch.object(photos, "_mark_lookup", side_effect=source("Mark", False)), \
             patch.object(photos, "_spotter_lookup", side_effect=source("Peter", False)), \
             patch.object(photos, "_shipspotting_lookup", side_effect=source("Shipspotting", True)), \
             patch.object(photos, "_binnenvaart_lookup", side_effect=source("De Binnenvaart", True)):
            result = photos.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO)
        self.assertEqual(result["source"], "Shipspotting")
        self.assertEqual(calls, ["Mark", "Peter", "Shipspotting"])


    def test_commons_is_preferred_over_de_binnenvaart(self):
        commons_photo = {"ok": True, "source": "Wikimedia Commons", "cached_at": 500}
        with patch.object(photos, "_mark_lookup", return_value=None), \
             patch.object(photos, "_spotter_lookup", return_value=None), \
             patch.object(photos, "_shipspotting_lookup", return_value=None), \
             patch.object(photos, "_commons_search", return_value=[{}]), \
             patch.object(photos, "_score", return_value=250), \
             patch.object(photos, "_result_from_page", return_value=commons_photo), \
             patch.object(photos, "_binnenvaart_lookup") as de_binnenvaart:
            result = photos.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO)
        self.assertEqual(result["source"], "Wikimedia Commons")
        de_binnenvaart.assert_not_called()

    def test_de_binnenvaart_only_after_commons_has_no_match(self):
        calls = []
        def commons(query):
            calls.append("Wikimedia")
            return []
        def de_binnenvaart(*args):
            calls.append("De Binnenvaart")
            return {"ok": True, "source": "De Binnenvaart", "cached_at": 500}
        with patch.object(photos, "_mark_lookup", return_value=None), \
             patch.object(photos, "_spotter_lookup", return_value=None), \
             patch.object(photos, "_shipspotting_lookup", return_value=None), \
             patch.object(photos, "_commons_search", side_effect=commons), \
             patch.object(photos, "_binnenvaart_lookup", side_effect=de_binnenvaart):
            result = photos.lookup(MMSI, "SPIRIT OF GLACIER BAY", IMO)
        self.assertEqual(result["source"], "De Binnenvaart")
        self.assertGreaterEqual(calls.count("Wikimedia"), 1)
        self.assertEqual(calls[-1], "De Binnenvaart")
        self.assertEqual(calls.count("De Binnenvaart"), 1)


if __name__ == "__main__":
    unittest.main()
