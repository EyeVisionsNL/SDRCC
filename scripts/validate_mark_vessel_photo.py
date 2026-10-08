#!/usr/bin/env python3
"""Regression tests for the Mark Prummel source; no live website calls."""
import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "core/traffic_voice_vessel_photo.py"
spec = importlib.util.spec_from_file_location("mark_vessel_source", SOURCE)
photos = importlib.util.module_from_spec(spec)
spec.loader.exec_module(photos)

REGISTER = """<html><a href="/ship/rix-voyager-5lkk2-9125671/"><span>RIX VOYAGER</span></a>
<a href="/nl/ship/aaltje-jacoba-9133525/">AALTJE JACOBA</a>
<a href="/ship/other-voyager-9114713/">OTHER VOYAGER</a>
<a href="https://offsite.test/ship/evil-9125671/">RIX VOYAGER</a></html>"""

DETAIL = """<html><h1>RIX VOYAGER</h1><p>IMO number: 9125671</p>
<p>MMSI number: 636022775</p><img
src="https://markprummel.nl/wp-content/uploads/2026/10/rix-voyager-kiel-canal.jpg"
alt="Rix Voyager passing Kiel Canal"></html>"""


class MarkPrummelSourceTests(unittest.TestCase):
    def test_actual_register_path_and_matching_imo(self):
        with patch.object(photos, "_mark_page", return_value=(REGISTER, photos.MARK_REGISTER_URL)):
            photos._mark_register_rows = None
            self.assertEqual(
                photos._mark_candidate_urls("9125671", "RIX VOYAGER"),
                ["https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"],
            )

    def test_register_names_only_exact_not_partial(self):
        with patch.object(photos, "_mark_register", return_value=[
            ("RIX VOYAGER", "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/")
        ]):
            self.assertEqual(photos._mark_candidate_urls("", "VOYAGER"), [])
            self.assertEqual(photos._mark_candidate_urls("", "RIX VOYAGER"), [
                "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
            ])

    def test_real_ship_page_with_matching_imo_yields_photo(self):
        with patch.object(photos, "_mark_candidate_urls", return_value=[
            "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        ]), patch.object(photos, "_mark_page", return_value=(
            DETAIL, "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        )):
            result = photos._mark_lookup("636022775", "RIX VOYAGER", "9125671", 1000)
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "Mark Prummel")
        self.assertIn("rix-voyager-kiel-canal.jpg", result["image_url"])
        self.assertIn("rix-voyager-5lkk2-9125671", result["page_url"])

    def test_no_imo_requires_matching_mmsi(self):
        with patch.object(photos, "_mark_candidate_urls", return_value=[
            "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        ]), patch.object(photos, "_mark_page", return_value=(
            DETAIL, "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        )):
            self.assertIsNone(photos._mark_lookup("244700498", "RIX VOYAGER", "", 1000))
            self.assertIsNotNone(photos._mark_lookup("636022775", "RIX VOYAGER", "", 1000))

    def test_invalid_unrelated_image_is_not_returned(self):
        with patch.object(photos, "_mark_candidate_urls", return_value=[
            "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        ]), patch.object(photos, "_mark_page", return_value=(
            DETAIL.replace("rix-voyager-kiel-canal.jpg", "website-logo.jpg")
                  .replace('Rix Voyager passing Kiel Canal', 'Website logo'),
            "https://markprummel.nl/ship/rix-voyager-5lkk2-9125671/"
        )):
            self.assertIsNone(photos._mark_lookup("636022775", "RIX VOYAGER", "9125671", 1000))

    def test_dutch_profile_imo_and_mmsi_labels(self):
        document = DETAIL.replace("IMO number:", "IMO-nummer:").replace("MMSI number:", "MMSI-nummer:")
        with patch.object(photos, "_mark_candidate_urls", return_value=[
            "https://markprummel.nl/nl/ship/rix-voyager-5lkk2-9125671/"
        ]), patch.object(photos, "_mark_page", return_value=(
            document, "https://markprummel.nl/nl/ship/rix-voyager-5lkk2-9125671/"
        )):
            self.assertIsNotNone(photos._mark_lookup("636022775", "RIX VOYAGER", "9125671", 1000))
            self.assertIsNotNone(photos._mark_lookup("636022775", "RIX VOYAGER", "", 1000))


if __name__ == "__main__":
    unittest.main()
