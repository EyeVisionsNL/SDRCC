#!/usr/bin/env python3
"""Offline De Binnenvaart photo-source tests (no images or live web requests)."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import unittest

MODULE = Path(__file__).resolve().parents[1] / "core/traffic_voice_debinnenvaart.py"
SPEC = importlib.util.spec_from_file_location("debinnenvaart_test", MODULE)
photo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(photo)
URL = "https://www.debinnenvaart.nl/schip_detail/provider/"
IMG = "https://de-binnenvaart.b-cdn.net/2019/12/provider-02338736-ship.jpg"
INDEX = ('<table><tr><th>Ship</th><th>Type</th><th>ENI-nr</th></tr>'
         '<tr><td><a href="/schip_detail/provider/">Provider</a></td>'
         '<td>Motortankschip</td><td>02338736</td></tr></table>')
DETAIL = ('<h1>PROVIDER</h1><p>EU Nummer 02338736</p><p>Scheepstype Motortankschip</p>'
          f'<img src="{IMG}" alt="Provider at Werkendam">'
          '<p>Foto: Aris van Dijk - Provider - Werkendam - 2020</p>')


class DeBinnenvaartTests(unittest.TestCase):
    def test_index_name_and_eni(self):
        parser = photo._AlphabetIndex()
        parser.feed(INDEX)
        self.assertEqual(parser.rows, [("Provider", "02338736", URL)])

    def test_index_select_exact_eni(self):
        with patch.object(photo, "_index", return_value=[("Provider", "02338736", URL)]):
            self.assertEqual(photo._candidates("Provider", "02338736"), [URL])
            self.assertEqual(photo._candidates("Provider", "12345678"), [])

    def test_ambiguous_name_is_not_guessed(self):
        with patch.object(photo, "_index", return_value=[
            ("Provider", "02338736", URL),
            ("Provider", "02312345", "https://www.debinnenvaart.nl/schip_detail/other/")
        ]):
            self.assertEqual(photo._candidates("Provider", ""), [])

    def test_detail_photographer_and_original_link(self):
        found = photo._parse_detail(DETAIL, "Provider", "02338736", URL, "244123456", "", 10)
        self.assertEqual(found["source"], "De Binnenvaart")
        self.assertEqual(found["artist"], "Aris van Dijk")
        self.assertEqual(found["page_url"], URL)
        self.assertEqual(found["image_url"], IMG)

    def test_wrong_ship_rejected(self):
        self.assertIsNone(photo._parse_detail(DETAIL, "Tourmaline", "", URL, "244123456", "", 10))

    def test_conflicting_eni_rejected(self):
        self.assertIsNone(photo._parse_detail(DETAIL, "Provider", "02387654", URL, "244123456", "", 10))

    def test_no_photo_credit_rejected(self):
        self.assertIsNone(photo._parse_detail(DETAIL.replace("Foto:", "Credit:"), "Provider", "", URL, "244123456", "", 10))

    def test_unapproved_image_host_rejected(self):
        self.assertEqual(photo._safe_image("https://unknown.test/picture.jpg"), "")

    def test_website_watermark_remains_unmodified(self):
        self.assertEqual(photo._safe_image(IMG), IMG)

    def test_existing_responsive_thumbnail_preferred(self):
        attr = {"srcset": IMG + " 1200w, https://de-binnenvaart.b-cdn.net/2019/12/provider-300x200.jpg 300w", "src": IMG}
        self.assertIn("300x200", photo._image_from_attrs(attr))

    def test_empty_candidate_falls_back(self):
        with patch.object(photo, "_candidates", return_value=[]):
            self.assertIsNone(photo.lookup("244123456", "Provider"))


if __name__ == "__main__":
    unittest.main()
