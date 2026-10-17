#!/usr/bin/env python3
"""Offline checks for the approved branded JPEG, without network or live radio."""
import unittest
from io import BytesIO
from unittest.mock import patch

from PIL import Image, ImageDraw

try:
    from core import traffic_voice_rensendriessen_image as branding
except ImportError:
    from ais_atis_bridge import rensendriessen_image as branding


PHOTO_URL = "https://www.rensendriessen.com/wp-content/uploads/2025/07/Reality-26-scaled.jpg"


def sample_bytes(*, logo=False):
    size = (160, 160) if logo else (640, 360)
    im = Image.new("RGB", size, "white" if logo else (30, 60, 90))
    if logo:
        draw = ImageDraw.Draw(im)
        draw.polygon([(25, 65), (120, 65), (130, 115), (50, 115)], fill=(0, 125, 63))
    b = BytesIO()
    im.save(b, format="JPEG", quality=94)
    return b.getvalue()


class EmbeddedPhotoTests(unittest.TestCase):
    def tearDown(self):
        branding.render.cache_clear()
        branding._logo.cache_clear()

    def test_badge_is_burned_into_saved_jpeg(self):
        original = sample_bytes()
        logo = sample_bytes(logo=True)
        def fake_download(url, cap, *, logo=False):
            return sample_bytes(logo=True) if logo else original
        with patch.object(branding, "_download", side_effect=fake_download):
            result = branding.render(PHOTO_URL)
        self.assertTrue(result.startswith(b"\xff\xd8"))
        with Image.open(BytesIO(result)) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (640, 360))
            # The upper-left photo is unchanged, and lower-right now has a
            # white/green logo badge rather than bare blue background.
            self.assertTrue(23 <= img.getpixel((20, 20))[0] <= 38)
            self.assertGreater(img.getpixel((515, 285))[0], 170)
            self.assertLess(img.getpixel((565, 315))[0], 100)
        self.assertEqual(original, sample_bytes())  # source was never overwritten

    def test_outside_url_rejected_before_fetching(self):
        with self.assertRaises(ValueError):
            branding._download("https://evil.example/wp-content/uploads/Reality.jpg", 100)
        with self.assertRaises(ValueError):
            branding._download("http://www.rensendriessen.com/wp-content/uploads/Reality.jpg", 100)


if __name__ == "__main__":
    unittest.main()
