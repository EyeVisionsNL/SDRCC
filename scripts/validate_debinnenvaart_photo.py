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

    def test_generic_filename_but_matching_ship_caption(self):
        document = DETAIL.replace(IMG, "https://de-binnenvaart.b-cdn.net/2019/12/document-1255.jpg")
        candidate = photo._parse_detail(document, "Provider", "02338736", URL, "244123456", "", 10)
        self.assertIsNotNone(candidate)
        self.assertIn("document-1255", candidate["image_url"])

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

    def test_renamed_ship_same_initial_eni_match(self):
        # The public index may still list the hull under its former name.
        old = "https://www.debinnenvaart.nl/schip_detail/former/"
        with patch.object(photo, "_index", return_value=[
            ("Poseidon", "02338736", old),
            ("Provider II", "02391234", URL),
        ]):
            self.assertEqual(photo._candidates("Provider", "02338736"), [old])

    def test_different_name_needs_exact_eni(self):
        doc = DETAIL.replace("<h1>PROVIDER</h1>", "<h1>POSEIDON</h1>")
        valid = photo._parse_detail(doc, "Provider", "02338736", URL, "244123456", "", 10)
        self.assertEqual(valid["artist"], "Aris van Dijk")
        self.assertIsNone(photo._parse_detail(doc, "Provider", "", URL, "244123456", "", 10))
        self.assertIsNone(photo._parse_detail(doc, "Provider", "02390909", URL, "244123456", "", 10))

    def test_unlabeled_gallery_photo_with_exact_eni_and_credit(self):
        doc = DETAIL.replace(IMG, "https://de-binnenvaart.b-cdn.net/2019/12/photo-98632.webp")
        doc = doc.replace("Provider at Werkendam", "Historic vessel")
        doc = doc.replace(" - Provider - Werkendam - 2020", " - historic image")
        found = photo._parse_detail(doc, "Provider", "02338736", URL, "244123456", "", 10)
        self.assertEqual(found["artist"], "Aris van Dijk")
        self.assertTrue(found["image_url"].endswith("photo-98632.webp"))
        self.assertIsNone(photo._parse_detail(doc, "Provider", "", URL, "244123456", "", 10))

    def test_relative_first_party_image_is_safe(self):
        path = "/image.php?url=https%3A%2F%2Fde-binnenvaart.b-cdn.net%2Fphoto.jpg"
        self.assertEqual(photo._image_from_attrs({"src": path}), "https://de-binnenvaart.b-cdn.net/photo.jpg")
        self.assertEqual(photo._image_from_attrs({"src": "//untrusted.example/ship.jpg"}), "")

    def test_uncredited_generic_photo_rejected_even_with_exact_eni(self):
        doc = DETAIL.replace(IMG, "https://de-binnenvaart.b-cdn.net/2019/12/photo-42.jpg")
        doc = doc.replace("Provider at Werkendam", "Historic vessel").replace("Foto:", "Credits:")
        self.assertIsNone(photo._parse_detail(doc, "Provider", "02338736", URL, "244123456", "", 10))

    def test_android_and_mobile_use_the_same_photo_finder(self):
        root = MODULE.parents[1]
        mobile = (root / "dashboard/static/mobile/index.html").read_text(encoding="utf-8")
        regular = (root / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
        android = (root / "android/app/src/main/java/nl/eyevisions/sdrcc/mobile/StationAddress.java").read_text(encoding="utf-8")
        for client in (mobile, regular):
            self.assertIn("/api/traffic-voice/vessel-photo?mmsi=", client)
        self.assertIn('m.shipname||m.callsign||""', mobile)
        self.assertIn("const key=[id,name.toUpperCase(),imo,eni].join", mobile)
        self.assertIn("lastPhotoRetryAfter=Date.now()+30*60*1000", mobile)
        self.assertIn("readMobileJson(url,90000)", mobile)
        self.assertIn('const isDeBinnenvaart=source==="De Binnenvaart"', mobile)
        self.assertIn("renderPhotoCredit(target,d)", mobile)
        self.assertIn('"/static/mobile/index.html"', android)

    def test_derova_slug_when_alphabetical_list_omits_ship(self):
        with patch.object(photo, "_index", return_value=[]):
            self.assertEqual(photo._candidates("DEROVA", ""),
                             ["https://www.debinnenvaart.nl/schip_detail/derova/"])

    def test_derova_image_proxy_keeps_credit_and_original_link(self):
        from urllib.parse import quote
        cdn = ("https://de-binnenvaart.b-cdn.net/2024/12/"
               "derova-06105821-mts-papendrecht-04-05-2025--aris-van-dijk.jpg")
        proxy = "https://debinnenvaart.nl/wp-content/uploads/image.php?url=" + quote(cdn, safe="")
        page_url = "https://www.debinnenvaart.nl/schip_detail/derova/"
        detail = ('<h1>DEROVA</h1><p>EU Nummer 06105821</p><p>Scheepstype Motortankschip</p>'
                  f'<img src="{proxy}" alt="DEROVA in Papendrecht">'
                  '<p>Foto: Aris van Dijk - Derova - Papendrecht - 04-05-2025</p>')
        result = photo._parse_detail(detail, "DEROVA", "", page_url, "205580990", "", 123)
        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "De Binnenvaart")
        self.assertEqual(result["artist"], "Aris van Dijk")
        self.assertEqual(result["image_url"], cdn)
        self.assertEqual(result["page_url"], page_url)

    def test_slug_probe_does_not_override_identity_check(self):
        with patch.object(photo, "_index", return_value=[]), \
             patch.object(photo, "_fetch", return_value=DETAIL):
            self.assertIsNone(photo.lookup("205580990", "DEROVA"))

    def test_ambiguous_ship_name_disables_slug_guess(self):
        with patch.object(photo, "_index", return_value=[
            ("Derova", "06105821", "https://www.debinnenvaart.nl/schip_detail/derova/"),
            ("Derova", "06105999", "https://www.debinnenvaart.nl/schip_detail/derova-old/"),
        ]):
            self.assertEqual(photo._candidates("DEROVA", ""), [])

    def test_kostra3_vetted_numeric_profile_identity(self):
        expected = ("https://www.debinnenvaart.nl/schip_detail/14304/", "02335966")
        self.assertEqual(photo._verified_numeric_profile("244660735", "KOSTRA 3", ""), expected)
        self.assertEqual(photo._verified_numeric_profile("244660735", "KOSTRA 3", "2335966"), expected)
        self.assertIsNone(photo._verified_numeric_profile("244660736", "KOSTRA 3", ""))
        self.assertIsNone(photo._verified_numeric_profile("244660735", "KOSTRA 2", ""))
        self.assertIsNone(photo._verified_numeric_profile("244660735", "KOSTRA 3", "02335815"))

    def test_kostra3_photo_and_photographer_without_client_eni(self):
        url = "https://www.debinnenvaart.nl/schip_detail/14304/"
        img = "https://de-binnenvaart.b-cdn.net/f5EMLFT68bPS5JPG.jpg"
        detail = ('<h1>KOSTRA 3</h1><p>EU Nummer 02335966</p>'
                  '<p>Scheepstype Kraan & overslagschip</p>'
                  f'<img src="{img}" alt="KOSTRA 3 at Vlaardingen">'
                  '<p>Foto: Kor Heidinga - Kostra 3 - Vlaardingen - 18-03-2017</p>')
        with patch.object(photo, "_index", side_effect=AssertionError("Old index bypass required")), \
             patch.object(photo, "_fetch", return_value=detail) as request:
            result = photo.lookup("244660735", "KOSTRA 3")
        self.assertIsNotNone(result)
        self.assertEqual(result["artist"], "Kor Heidinga")
        self.assertEqual(result["page_url"], url)
        self.assertEqual(result["image_url"], img)
        self.assertEqual(result["eni"], "02335966")
        request.assert_called_once_with(url, photo.MAX_DETAIL)

    def test_kostra3_rejects_wrong_eni_in_live_profile(self):
        doc = ('<h1>KOSTRA 3</h1><p>EU Nummer 02335815</p>'
               '<p>Scheepstype Kraan & overslagschip</p>'
               '<img src="https://de-binnenvaart.b-cdn.net/kostra-3.jpg" alt="KOSTRA 3">'
               '<p>Foto: Kor Heidinga - Kostra 3</p>')
        with patch.object(photo, "_index", return_value=[]), \
             patch.object(photo, "_fetch", return_value=doc):
            self.assertIsNone(photo.lookup("244660735", "KOSTRA 3"))

    def test_desktop_does_not_show_old_photo_alt_during_failed_lookup(self):
        script = (MODULE.parents[1] / "dashboard/static/js/traffic_voice.js").read_text("utf-8")
        self.assertIn('image.style.display = "none"', script)
        self.assertIn('image.alt = ""', script)
        self.assertIn('image.onload = () => {', script)
        self.assertIn('const identityKey = [mmsi, shipname.toUpperCase(), imo, eni].join("|")', script)

    def test_groenendaal_same_name_history_uses_verified_eni(self):
        self.assertEqual(photo._effective_eni("244029535", "GROENENDAAL", ""), "02339837")
        self.assertIsNone(photo._effective_eni("244029535", "GROENENDAAL", "02332234"))
        self.assertEqual(photo._effective_eni("244029535", "OTHER VESSEL", ""), "")

    def test_groenendaal_current_profile_without_alphabet_index(self):
        url = "https://www.debinnenvaart.nl/schip_detail/groenendaal/"
        doc = ('<h1>GROENENDAAL</h1><p>EU Nummer 02339837</p>'
               '<p>Laatste naam</p><p>Groenendaal</p><p>Scheepstype Motortankschip</p>'
               '<img src="https://de-binnenvaart.b-cdn.net/groenendaal.jpg" alt="Groenendaal">'
               '<p>Foto: Leo Schuitemaker - Groenendaal - Rotterdam - 2024</p>')
        with patch.object(photo, "_index", side_effect=AssertionError("Index should not be needed")), \
             patch.object(photo, "_fetch", return_value=doc) as fetch:
            result = photo.lookup("244029535", "GROENENDAAL")
        self.assertEqual(result["artist"], "Leo Schuitemaker")
        self.assertEqual(result["eni"], "02339837")
        self.assertEqual(result["page_url"], url)
        fetch.assert_called_once_with(url, photo.MAX_DETAIL)

    def test_groenendaal_rejects_old_ship_with_different_eni(self):
        doc = ('<h1>GROENENDAAL</h1><p>EU Nummer 02332234</p>'
               '<p>Laatste naam</p><p>Carinalexander</p><p>Scheepstype Motortankschip</p>'
               '<img src="https://de-binnenvaart.b-cdn.net/old.jpg" alt="Groenendaal">'
               '<p>Foto: Aris van Dijk - Old Groenendaal</p>')
        with patch.object(photo, "_index", return_value=[]), \
             patch.object(photo, "_fetch", return_value=doc):
            self.assertIsNone(photo.lookup("244029535", "GROENENDAAL"))

    def test_generic_slug_requires_latest_name_when_eni_missing(self):
        url = "https://www.debinnenvaart.nl/schip_detail/waterland/"
        current = ('<h1>WATERLAND</h1><p>EU Nummer 02345678</p>'
                   '<p>Laatste naam</p><p>Waterland</p><p>Scheepstype Motortankschip</p>'
                   '<img src="https://de-binnenvaart.b-cdn.net/waterland.jpg" alt="Waterland">'
                   '<p>Foto: Anna Fotograaf - Waterland</p>')
        historic = current.replace('<p>Waterland</p><p>Scheepstype',
                                   '<p>Othername</p><p>Scheepstype')
        with patch.object(photo, "_index", side_effect=AssertionError("Do not need index")), \
             patch.object(photo, "_fetch", return_value=current):
            result = photo.lookup("244123456", "WATERLAND")
        self.assertEqual(result["page_url"], url)
        with patch.object(photo, "_index", return_value=[]), \
             patch.object(photo, "_fetch", return_value=historic):
            self.assertIsNone(photo.lookup("244123456", "WATERLAND"))

    def test_direct_slug_with_eni_requires_eni_on_profile(self):
        doc = ('<h1>WATERLAND</h1><p>Laatste naam</p><p>Waterland</p>'
               '<p>Scheepstype Motortankschip</p>'
               '<img src="https://de-binnenvaart.b-cdn.net/waterland.jpg" alt="Waterland">'
               '<p>Foto: Anna Fotograaf - Waterland</p>')
        with patch.object(photo, "_index", return_value=[]), \
             patch.object(photo, "_fetch", return_value=doc):
            self.assertIsNone(photo.lookup("244123456", "WATERLAND", eni="02345678"))

    def test_empty_candidate_falls_back(self):
        with patch.object(photo, "_candidates", return_value=[]):
            self.assertIsNone(photo.lookup("244123456", "Provider"))


if __name__ == "__main__":
    unittest.main()
