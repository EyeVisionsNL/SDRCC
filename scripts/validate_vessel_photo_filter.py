#!/usr/bin/env python3
"""Regression tests for ship-photo filtering; no external network needed."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPOSITORY_ROOT / "core/traffic_voice_vessel_photo.py"
SPEC = importlib.util.spec_from_file_location("vessel_photo_validation", MODULE_PATH)
photo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(photo)


def candidate(title, description="", categories="", thumb=True, mmsi="", imo=""):
    more = " ".join(filter(None, [description, ("MMSI " + mmsi) if mmsi else "", ("IMO " + imo) if imo else ""]))
    return {
        "title": "File:" + title,
        "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/a/a1/example.jpg" if thumb else "",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example",
            "extmetadata": {
                "ImageDescription": {"value": more},
                "Categories": {"value": categories},
                "Artist": {"value": "Ship photographer"},
                "LicenseShortName": {"value": "CC BY-SA 4.0"},
            },
        }],
    }


class VesselPhotoValidation(unittest.TestCase):
    def score(self, page, name="TOURMALINE", imo=""):
        return photo._score(page, mmsi="244700498", shipname=name, imo=imo)

    def test_mineral_from_screenshot_is_rejected(self):
        self.assertLess(self.score(candidate(".Tourmaline - Tourmali.jpg",
                                              "Tourmaline mineral sample, quartz", "Minerals")), 0)

    def test_name_alone_cannot_qualify(self):
        self.assertLess(self.score(candidate("Tourmaline.jpg", "Tourmaline gemstone")), 0)

    def test_art_is_rejected(self):
        self.assertLess(self.score(candidate("Motor tanker Tourmaline painting.jpg",
                                              "Illustration of a motor tanker")), 0)

    def test_military_namesake_is_rejected(self):
        self.assertLess(self.score(candidate("USS Tourmaline PY-20.jpg",
                                              "USS Tourmaline patrol vessel", "US Navy ships")), 0)

    def test_ship_in_filename_is_accepted(self):
        self.assertGreaterEqual(self.score(candidate("Motor tanker TOURMALINE.jpg", "Motor tanker Tourmaline")), 100)

    def test_ship_in_description_is_accepted(self):
        self.assertGreaterEqual(self.score(candidate("Tourmaline.jpg",
                                                      "De motortanker Tourmaline bij Vlaardingen")), 100)

    def test_name_as_credit_is_not_vessel_identity(self):
        self.assertLess(self.score(candidate("MV Ocean Blue.jpg",
                                              "Ships photographed by someone called Tourmaline")), 0)

    def test_ship_name_must_be_exact(self):
        self.assertLess(self.score(candidate("Motor tanker Tourmalines.jpg", "Motortanker Tourmalines")), 0)

    def test_correct_mmsi_is_accepted(self):
        self.assertGreaterEqual(self.score(candidate("Boat harbour.jpg", "Vessel photographed", mmsi="244700498")), 200)

    def test_wrong_mmsi_is_rejected(self):
        self.assertLess(self.score(candidate("Motor tanker Tourmaline.jpg", "Motor tanker Tourmaline",
                                              mmsi="123456789")), 0)

    def test_wrong_imo_is_rejected(self):
        self.assertLess(self.score(candidate("Motor tanker Tourmaline.jpg",
                                              "Motor tanker Tourmaline", imo="7654321"), imo="1234567"), 0)

    def test_no_thumbnail_is_rejected(self):
        self.assertLess(self.score(candidate("Motor tanker Tourmaline.jpg", thumb=False)), 0)

    def test_mineral_name_can_still_identify_a_ship(self):
        self.assertGreaterEqual(self.score(candidate("Motor tanker CRYSTAL.jpg",
                                                      "Motor tanker Crystal"), name="CRYSTAL"), 100)

    def test_lookup_skips_mineral_and_uses_vessel(self):
        bad = candidate("Tourmaline mineral.jpg", "Tourmaline crystal")
        good = candidate("Motor tanker TOURMALINE.jpg", "Motor tanker Tourmaline")
        with tempfile.TemporaryDirectory() as cache_dir:
            original_file, original_cache = photo.CACHE_FILE, photo._cache
            try:
                photo.CACHE_FILE = Path(cache_dir) / "cache.json"
                photo._cache = {}
                with patch.object(photo, "_mark_lookup", return_value=None), \
                     patch.object(photo, "_commons_search", return_value=[bad, good]):
                    result = photo.lookup("244700498", "TOURMALINE")
                self.assertTrue(result["ok"])
                self.assertEqual(result["title"], "Motor tanker TOURMALINE.jpg")
                self.assertFalse(result["cached"])
                self.assertEqual(result["source"], "Wikimedia Commons")
            finally:
                photo.CACHE_FILE = original_file
                photo._cache = original_cache

    def test_old_photo_cache_is_not_reused(self):
        self.assertGreaterEqual(photo.PHOTO_POLICY_VERSION, 4)
        old_key = "3|244700498|TOURMALINE|"
        with tempfile.TemporaryDirectory() as cache_dir:
            original_file, original_cache = photo.CACHE_FILE, photo._cache
            try:
                photo.CACHE_FILE = Path(cache_dir) / "cache.json"
                photo._cache = {old_key: {"ok": True, "image_url": "https://example.com/mineral.jpg", "cached_at": 1e20}}
                with patch.object(photo, "_mark_lookup", return_value=None), \
                     patch.object(photo, "_commons_search", return_value=[]):
                    result = photo.lookup("244700498", "TOURMALINE")
                self.assertFalse(result["ok"])
                self.assertFalse(result["cached"])
            finally:
                photo.CACHE_FILE = original_file
                photo._cache = original_cache


if __name__ == "__main__":
    unittest.main()
