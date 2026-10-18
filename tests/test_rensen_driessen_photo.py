#!/usr/bin/env python3
"""Offline regressions for the Rensen-Driessen photo provider."""
import unittest
from unittest.mock import patch

try:
    from core import traffic_voice_rensendriessen as provider
except ImportError:
    from ais_atis_bridge import rensendriessen as provider


REGISTER = '<a href="/ships/reality/">REALITY</a><a href="/ships/omega/">OMEGA</a>'
REALITY = ('<h1>Tanker Reality</h1>'
           '<a href="/wp-content/uploads/2025/07/Reality-26-scaled.jpg">Photo</a>'
           '<img src="/wp-content/uploads/2025/07/Reality-26-scaled.jpg">')


class PhotoSourceTests(unittest.TestCase):
    def setUp(self):
        provider._checked = 0
        provider._register = []

    def fake_fetch(self, page):
        return patch.object(provider, "_read",
            side_effect=lambda url, limit: REGISTER if url == provider.REGISTER else page)

    def test_exact_reality_photo_with_original_source(self):
        with self.fake_fetch(REALITY):
            result = provider.lookup("244123456", "Reality", now=123)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "Rensen-Driessen")
        self.assertTrue(result["logo_overlay"])
        self.assertEqual(result["page_url"], "https://www.rensendriessen.com/ships/reality/")
        self.assertIn("Reality-26-scaled.jpg", result["image_url"])

    def test_different_heading_is_rejected(self):
        with self.fake_fetch(REALITY.replace("Tanker Reality", "Tanker Omega")):
            self.assertIsNone(provider.lookup("244123456", "Reality"))

    def test_conflicting_mmsi_is_rejected(self):
        with self.fake_fetch(REALITY + '<p>MMSI 999999999</p>'):
            self.assertIsNone(provider.lookup("244123456", "Reality"))

    def test_duplicate_register_names_are_rejected(self):
        dup = REGISTER + '<a href="/ships/reality-2/">Reality</a>'
        with patch.object(provider, "_read", side_effect=lambda url, limit: dup if url == provider.REGISTER else REALITY):
            self.assertIsNone(provider.lookup("244123456", "Reality"))

    def test_untrusted_media_and_wrong_ship_are_rejected(self):
        self.assertEqual(provider._image_url("https://other.example/Reality.jpg", "Reality"), "")
        self.assertEqual(provider._image_url(
            "https://www.rensendriessen.com/wp-content/uploads/2025/07/Omega-12.jpg", "Reality"), "")
        self.assertEqual(provider._ship_url("http://evil.invalid/ships/reality/"), "")


if __name__ == "__main__":
    unittest.main()
