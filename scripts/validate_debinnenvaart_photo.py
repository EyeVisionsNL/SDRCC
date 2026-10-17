#!/usr/bin/env python3
"""Offline checks for the current De Binnenvaart JSON photo source."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "core/traffic_voice_debinnenvaart_api.py"
SPEC = importlib.util.spec_from_file_location("binnenvaart_api", FILE)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)
IMAGE = "https://content.epublisher-cloud.com/binnenvaartdata/images/15560/foto_001.jpg"


def summary(id="15560", name="Invotis VII", eni="02334352"):
    return {"id": id, "naam": name, "laatste_naam": name, "status": "actief",
            "eu_nummer_eerste": eni, "eu_nummer_laatste": eni}


def photograph(id="15560", artist="Kor Heidinga", image=IMAGE):
    return {"schip_id": id, "fotograaf": artist, "credit": "Foto: " + artist,
            "src": image, "goedgekeurd": 1, "is_vlag": 0}


def search(rows=None, total=None):
    rows = [summary()] if rows is None else rows
    return {"data": rows, "totaal": len(rows) if total is None else total}


def detail(vessel=None, images=None):
    return {**(summary() if vessel is None else vessel),
            "fotos": [photograph()] if images is None else images}


class BinnenvaartCurrentAPITests(unittest.TestCase):
    def test_real_invotis_seven_fixture_exact_eni_and_credit(self):
        with patch.object(api, "_get_json", side_effect=[search(), detail()]) as req:
            photo = api.lookup("244740814", "INVOTIS VII", "8354732")
        self.assertEqual(photo["source"], "De Binnenvaart")
        self.assertEqual(photo["artist"], "Kor Heidinga")
        self.assertEqual(photo["eni"], "02334352")
        self.assertEqual(photo["image_url"], IMAGE)
        self.assertEqual(photo["page_url"], "https://debinnenvaart.nl/schip/15560")
        self.assertIn("q=INVOTIS+VII", req.call_args_list[0].args[0])
        self.assertEqual(req.call_count, 2)

    def test_fuzzy_invotis_viii_does_not_override_seven(self):
        rows = [summary(), summary("13669", "Invotis VIII", "02388888")]
        with patch.object(api, "_get_json", side_effect=[search(rows), detail()]):
            self.assertEqual(api.lookup("244740814", "INVOTIS VII")["page_url"],
                             "https://debinnenvaart.nl/schip/15560")

    def test_groenendaal_excludes_historical_carinalexander(self):
        current = summary("groenendaal", "Groenendaal", "02339837")
        old = {**summary("11308", "GROENENDAAL", "02332234"),
               "laatste_naam": "Carinalexander"}
        url = "https://content.epublisher-cloud.com/binnenvaartdata/images/groenendaal/foto_001.jpg"
        with patch.object(api, "_get_json", side_effect=[
            search([current, old]), detail(current, [photograph("groenendaal", "Roland Hesse", url)]),
        ]):
            photo = api.lookup("244029535", "GROENENDAAL")
        self.assertEqual(photo["artist"], "Roland Hesse")
        self.assertEqual(photo["eni"], "02339837")

    def test_both_numeric_and_slug_identifiers_are_generic(self):
        for name, id, eni, mmsi in (
            ("DEROVA", "derova", "06105821", "205580990"),
            ("KOSTRA 3", "14304", "02335966", "244660735"),
        ):
            vessel = summary(id, name, eni)
            image = f"https://content.epublisher-cloud.com/binnenvaartdata/images/{id}/foto_001.jpg"
            with self.subTest(name=name), patch.object(api, "_get_json", side_effect=[
                search([vessel]), detail(vessel, [photograph(id, "Ruud Zegwaard", image)])
            ]):
                result = api.lookup(mmsi, name, eni=eni)
            self.assertEqual(result["page_url"], "https://debinnenvaart.nl/schip/" + id)
            self.assertEqual(result["eni"], eni)

    def test_identical_current_name_without_eni_must_be_unique(self):
        with patch.object(api, "_get_json", return_value=search([
            summary("10", "ATLAS", "02330000"), summary("20", "ATLAS", "02330001")
        ])) as mock:
            self.assertIsNone(api.lookup("244456789", "ATLAS"))
        mock.assert_called_once()

    def test_eni_selects_one_same_name_ship(self):
        vessel = summary("20", "ATLAS", "02330001")
        url = "https://content.epublisher-cloud.com/binnenvaartdata/images/20/foto_001.jpg"
        with patch.object(api, "_get_json", side_effect=[
            search([summary("10", "ATLAS", "02330000"), vessel]),
            detail(vessel, [photograph("20", "Anna", url)]),
        ]):
            self.assertEqual(api.lookup("244456789", "ATLAS", eni="02330001")["artist"], "Anna")

    def test_conflicting_eni_on_summary_refused(self):
        with patch.object(api, "_get_json", return_value=search()) as mock:
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII", eni="02399999"))
        mock.assert_called_once()

    def test_conflicting_eni_on_detail_refused(self):
        with patch.object(api, "_get_json", side_effect=[
            search(), detail(summary("15560", "INVOTIS VII", "02399999")),
        ]):
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII", eni="02334352"))

    def test_uncredited_unapproved_and_other_ship_images_refused(self):
        bad = [photograph("wrong"), photograph(artist=""),
               {**photograph(), "goedgekeurd": 0},
               {**photograph(), "is_vlag": 1}]
        with patch.object(api, "_get_json", side_effect=[search(), detail(images=bad)]):
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII"))

    def test_photo_urls_allowlist_not_arbitrary_urls(self):
        for url in ("https://evil.test/x.jpg",
                    "http://content.epublisher-cloud.com/binnenvaartdata/images/15560/a.jpg",
                    "https://content.epublisher-cloud.com/binnenvaartdata/images/99999/a.jpg",
                    "https://de-binnenvaart.b-cdn.net/a.svg"):
            with self.subTest(url=url):
                self.assertEqual(api._photo_url(url, "15560"), "")
        self.assertEqual(api._photo_url(IMAGE, "15560"), IMAGE)

    def test_missing_photographer_never_hidden_by_credit_placeholder(self):
        with patch.object(api, "_get_json", side_effect=[
            search(), detail(images=[
                {**photograph(), "fotograaf": "", "credit": ""},
                {**photograph(), "goedgekeurd": 0},
            ]),
        ]):
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII"))

    def test_incomplete_paging_does_not_guess(self):
        with patch.object(api, "_get_json", side_effect=[
            search(total=80), search([summary("20", "INVOTIS VII", "02399999")], total=80),
            search([], total=80),
        ]):
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII"))

    def test_timeout_falls_through(self):
        with patch.object(api, "_get_json", side_effect=TimeoutError):
            self.assertIsNone(api.lookup("244740814", "INVOTIS VII"))

    def test_shared_desktop_mobile_api_and_attribution(self):
        desktop = (ROOT / "dashboard/static/js/traffic_voice.js").read_text("utf-8")
        mobile = (ROOT / "dashboard/static/mobile/index.html").read_text("utf-8")
        android = (ROOT / "android/app/src/main/java/nl/eyevisions/sdrcc/mobile/StationAddress.java").read_text("utf-8")
        for js in (desktop, mobile):
            self.assertIn("/api/traffic-voice/vessel-photo?mmsi=", js)
        self.assertIn('result.source === "De Binnenvaart" && result.artist', desktop)
        self.assertIn('const isDeBinnenvaart=source==="De Binnenvaart"', mobile)
        self.assertIn("renderPhotoCredit(target,d)", mobile)
        self.assertIn('"/static/mobile/index.html"', android)

    def test_provider_order_binnenvaart_last(self):
        source = (ROOT / "core/traffic_voice_vessel_photo.py").read_text("utf-8")
        self.assertLess(source.index("shipspotting_result = _shipspotting_lookup"),
                        source.index("binnenvaart_result = _binnenvaart_lookup"))

    def test_legacy_module_is_api_compatibility_only(self):
        shim = (ROOT / "core/traffic_voice_debinnenvaart.py").read_text("utf-8")
        self.assertIn("from core.traffic_voice_debinnenvaart_api import lookup", shim)
        self.assertNotIn("schepen_a_z", shim)


if __name__ == "__main__":
    unittest.main()
