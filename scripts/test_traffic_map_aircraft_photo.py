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
