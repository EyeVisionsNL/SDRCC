#!/usr/bin/env python3
"""Unit tests for Map Lab aircraft-photo service; no external network."""
import io
import unittest
from unittest.mock import patch

from core import traffic_map_aircraft_photo as photos


class AircraftPhotoTests(unittest.TestCase):
    def setUp(self):
        photos._CACHE.clear()

    def test_reject_invalid_icao_without_network(self):
        with patch.object(photos, "urlopen") as request:
            self.assertFalse(photos.lookup("~4ca123")["ok"])
            self.assertFalse(photos.lookup("../../secret")["ok"])
            request.assert_not_called()

    def test_return_credited_photo_and_cache_it(self):
        payload = b'{"photos":[{"thumbnail":{"src":"https://cdn.planespotters.net/image.jpg"},' \
                  b'"link":"https://www.planespotters.net/photo/123", "photographer":"Jane Doe"}]}'
        with patch.object(photos, "urlopen", return_value=io.BytesIO(payload)) as get:
            first = photos.lookup("4ca123")
            second = photos.lookup("4ca123")
        self.assertTrue(first["ok"])
        self.assertEqual(second["photographer"], "Jane Doe")
        self.assertEqual(first["source"], "Planespotters.net")
        self.assertIn("/pub/photos/hex/4ca123", get.call_args.args[0].full_url)
        get.assert_called_once()

    def test_registration_and_icao_type_hints_are_safe(self):
        payload=b'{"photos":[{"thumbnail":{"src":"https://cdn.planespotters.net/p.jpg"}}]}'
        with patch.object(photos,"urlopen",return_value=io.BytesIO(payload)) as get:
            result=photos.lookup("345107","EC-MJC","A320")
        self.assertTrue(result["ok"])
        self.assertIn("reg=EC-MJC",get.call_args.args[0].full_url)
        self.assertIn("icaoType=A320",get.call_args.args[0].full_url)
        photos._CACHE.clear()
        with patch.object(photos,"urlopen",return_value=io.BytesIO(payload)) as get:
            result=photos.lookup("345107","https://bad.example/","../../")
        self.assertTrue(result["ok"])
        self.assertNotIn("bad.example",get.call_args.args[0].full_url)
        self.assertNotIn("icaoType=",get.call_args.args[0].full_url)

    def test_official_shortened_planespotters_cdn_is_accepted(self):
        # Real official thumbnails use t.plnspttrs.net, NOT the longer
        # planespotters.net domain; accepting only the latter caused no photos.
        payload = (b'{"photos":[{"thumbnail_large":{"src":'
                   b'"https://t.plnspttrs.net/43495/1864265_b4e8176cfe_280.jpg"},'
                   b'"link":"https://www.planespotters.net/photo/123",'
                   b'"photographer":"Photo Author"}]}')
        with patch.object(photos, "urlopen", return_value=io.BytesIO(payload)):
            result = photos.lookup("48520a")
        self.assertTrue(result["ok"])
        self.assertEqual(result["photographer"], "Photo Author")
        self.assertTrue(result["image_url"].startswith("https://t.plnspttrs.net/"))
        self.assertFalse(photos._trusted_url("https://t.plnspttrs.net.evil.test/a.jpg",image=True))
        self.assertFalse(photos._trusted_url("https://t.plnspttrs.net/a.jpg",image=False))
        self.assertFalse(photos._trusted_url("http://t.plnspttrs.net/a.jpg",image=True))

    def test_untrusted_image_or_photo_link_is_rejected(self):
        payload = b'{"photos":[{"thumbnail":{"src":"http://127.0.0.1/photo.jpg"},' \
                  b'"link":"https://evil.example/photo", "photographer":"Fraud"}]}'
        with patch.object(photos, "urlopen", return_value=io.BytesIO(payload)):
            result = photos.lookup("4ca123")
        self.assertFalse(result["ok"])

    def test_timeout_degrades_without_crashing(self):
        with patch.object(photos, "urlopen", side_effect=TimeoutError("offline")):
            result = photos.lookup("4ca123")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
