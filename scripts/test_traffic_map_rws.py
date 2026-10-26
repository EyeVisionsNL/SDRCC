#!/usr/bin/env python3
"""Offline tests for the limited official-RWS tide/wind adapter."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from core import traffic_map_rws as rws


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self, limit=-1):
        return self.body[:limit]


class RwsAdapterTests(unittest.TestCase):
    NOW = datetime(2026, 10, 25, 18, 35,
                   tzinfo=timezone(timedelta(hours=1)))

    def test_fixed_tide_request_matches_rijnmond_plugin(self):
        for kind, process, hours_ahead in (
            ("tide-measured", "meting", 0),
            ("tide-forecast", "astronomisch", 7),
        ):
            with self.subTest(kind=kind):
                endpoint, body = rws._request(kind, self.NOW)
                self.assertEqual(endpoint, "OphalenWaarnemingen")
                self.assertEqual(body["Locatie"]["Code"], "hoekvanholland")
                aqo = body["AquoPlusWaarnemingMetadata"]["AquoMetadata"]
                self.assertEqual(
                    (aqo["Compartiment"]["Code"], aqo["Grootheid"]["Code"],
                     aqo["Hoedanigheid"]["Code"], aqo["Eenheid"]["Code"],
                     aqo["ProcesType"]),
                    ("OW", "WATHTE", "NAP", "cm", process))
                period = body["Periode"]
                self.assertEqual(datetime.fromisoformat(period["Begindatumtijd"]),
                                 self.NOW - timedelta(hours=6))
                self.assertEqual(datetime.fromisoformat(period["Einddatumtijd"]),
                                 self.NOW + timedelta(hours=hours_ahead))

    def test_fixed_wind_request_matches_rijnmond_plugin(self):
        for kind, code in (("wind-speed", "WINDSHD"),
                           ("wind-direction", "WINDRTG")):
            with self.subTest(kind=kind):
                endpoint, body = rws._request(kind, self.NOW)
                self.assertEqual(endpoint, "OphalenLaatsteWaarnemingen")
                self.assertEqual(body["LocatieLijst"], [{"Code": "hoekvanholland"}])
                meta = body["AquoPlusWaarnemingMetadataLijst"][0]
                self.assertEqual(meta["AquoMetadata"]["Compartiment"]["Code"], "LT")
                self.assertEqual(meta["AquoMetadata"]["Grootheid"]["Code"], code)
                self.assertEqual(
                    meta["WaarnemingMetadata"]["OpdrachtgevendeInstantieLijst"],
                    ["RIKZ_METEO"])

    def test_no_open_proxy_and_fixed_official_rws_destination(self):
        calls = []
        payload = {"Waarnemingen": [{"Tijdstip": "2026-10-25T18:35:00+01:00",
                                    "Meetwaarde": {"Waarde_Numeriek": 87}}]}
        def opener(req, timeout):
            calls.append((req, timeout))
            return FakeResponse(payload)
        self.assertEqual(rws.fetch("wind-speed", opener), {
            "ok": True, "payload": payload,
        })
        self.assertEqual(len(calls), 1)
        request, timeout = calls[0]
        self.assertEqual(request.full_url,
                         "https://ddapi20-waterwebservices.rijkswaterstaat.nl/"
                         "ONLINEWAARNEMINGENSERVICES/"
                         "OphalenLaatsteWaarnemingen")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, rws.TIMEOUT_SECONDS)
        self.assertEqual(json.loads(request.data)["LocatieLijst"][0]["Code"],
                         "hoekvanholland")
        self.assertEqual(rws.fetch("https://example.org/", opener), {
            "ok": False, "error": "unsupported_measurement",
        })
        self.assertEqual(len(calls), 1, "invalid kind must not reach the network")

    def test_unreachable_and_oversize_relay_fail_closed(self):
        def unreachable(*args, **kwargs):
            raise ConnectionRefusedError("no relay")
        self.assertEqual(rws.fetch("tide-measured", unreachable)["error"],
                         "rws_service_unavailable")
        def invalid_response(*args, **kwargs):
            return FakeResponse({"sample": []})
        self.assertTrue(rws.fetch("tide-measured", invalid_response)["ok"])
        class Oversize(FakeResponse):
            def __init__(self):
                self.body = b"x" * (rws.MAX_RESPONSE_BYTES + 1)
        result = rws.fetch("tide-forecast", lambda *_args, **_kwargs: Oversize())
        self.assertEqual(result["error"], "rws_response_too_large")


if __name__ == "__main__":
    unittest.main()
