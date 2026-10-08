#!/usr/bin/env python3
"""No-network tests for Binnenvaartspotter thumbnails and false matches."""
from __future__ import annotations
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "core/traffic_voice_binnenvaartspotter.py"
SPEC = importlib.util.spec_from_file_location("spotter_test", SOURCE)
spotter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(spotter)

SITEMAP = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://www.binnenvaartspotter.nl/vrachtschepen-s/specter/</loc></url>
<url><loc>https://www.binnenvaartspotter.nl/over-mij/</loc></url>
<url><loc>https://evil.test/vrachtschepen-s/specter/</loc></url></urlset>"""
PHOTO = ("https://image.jimcdn.com/app/cms/image/transf/"
         "dimension%3D1920x400%3Aformat%3Djpg/path/s514/image/i889/"
         "version/1779193797/specter-motorvrachtschip-eni-2321028.jpg")
PAGE = ('<h1>Specter</h1><h2>Motorvrachtschip</h2><h3>ENI 2321028</h3>'
        '<img src="https://image.jimcdn.com/app/cms/image/transf/'
        'dimension%3D1920x400%3Aformat%3Djpg/path/s/header.jpg" alt="Header">'
        f'<img src="{PHOTO}" alt="Specter Motorvrachtschip ENI 2321028">')
PAGE_URL = "https://www.binnenvaartspotter.nl/vrachtschepen-s/specter/"


class PhotoTests(unittest.TestCase):
    def setUp(self):
        spotter.SITEMAP = []
        spotter.SITEMAP_CHECKED = 0

    def test_sitemap_ship_only(self):
        with patch.object(spotter, "_download", return_value=SITEMAP):
            self.assertEqual(spotter._candidate_urls("Specter"), [PAGE_URL])
            self.assertEqual(spotter._candidate_urls("Over mij"), [])

    def test_no_other_domains(self):
        self.assertFalse(spotter._ship_url("https://fake.test/vrachtschepen-s/specter/"))

    def test_matching_page_returns_small_photo_and_attribution(self):
        result = spotter._result_from_page(PAGE, "Specter", PAGE_URL,
                                            "244123456", "", "02321028", 10)
        self.assertEqual(result["source"], "Binnenvaartspotter.nl")
        self.assertEqual(result["artist"], "© Peter de Vries")
        self.assertIn("dimension%3D320x220", result["image_url"])
        self.assertEqual(result["page_url"], PAGE_URL)

    def test_name_only_is_not_sufficient(self):
        self.assertIsNone(spotter._result_from_page(
            "<h1>Specter</h1><p>A mineral crystal</p>", "Specter", PAGE_URL,
            "244123456", "", "", 10))

    def test_wrong_eni_rejected(self):
        self.assertIsNone(spotter._result_from_page(
            PAGE, "Specter", PAGE_URL, "244123456", "", "02311111", 10))

    def test_wrong_ship_name_rejected(self):
        self.assertIsNone(spotter._result_from_page(
            PAGE, "Tourmaline", PAGE_URL, "244123456", "", "", 10))

    def test_header_only_rejected(self):
        without_photo = PAGE.replace(f'<img src="{PHOTO}" alt="Specter Motorvrachtschip ENI 2321028">', "")
        self.assertIsNone(spotter._result_from_page(
            without_photo, "Specter", PAGE_URL, "244123456", "", "", 10))

    def test_original_and_other_domains_refused(self):
        self.assertEqual(spotter._thumbnail_url("https://image.jimcdn.com/full-size.jpg"), "")
        self.assertEqual(spotter._thumbnail_url("https://malicious.test/full-size.jpg"), "")

    def test_duplicate_vessel_names_rejected(self):
        spotter.SITEMAP = [PAGE_URL, "https://www.binnenvaartspotter.nl/tankschepen/specter/"]
        spotter.SITEMAP_CHECKED = spotter.time.monotonic()
        self.assertEqual(spotter._candidate_urls("Specter"), [])

    def test_lookup_with_mocked_page(self):
        with patch.object(spotter, "_candidate_urls", return_value=[PAGE_URL]), \
             patch.object(spotter, "_download", return_value=PAGE):
            self.assertEqual(spotter.lookup("244123456", "Specter")["source"], "Binnenvaartspotter.nl")

    def test_unmatched_falls_back(self):
        with patch.object(spotter, "_candidate_urls", return_value=[]):
            self.assertIsNone(spotter.lookup("244123456", "Unknown"))


if __name__ == "__main__":
    unittest.main()
