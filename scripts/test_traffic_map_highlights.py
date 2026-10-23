#!/usr/bin/env python3
"""Read-only Map Lab overlay tests; no hardware, network or receiver services."""
import unittest
from unittest.mock import patch

from core import traffic_map_highlights as highlights


def valid_atis(**overrides):
    latest = {
        "fresh": True, "mode_id": "marine_ais",
        "atis_code": "9244050123", "received_at": "2026-10-23T11:34:56+02:00",
        "age_seconds": 5,
    }
    latest.update(overrides)
    return {"latest": latest}


def valid_match(**overrides):
    match = {
        "matched": True, "status": "matched", "mmsi": "244123456",
        "latitude": 51.91, "longitude": 4.34,
        "match_method": "callsign_standard",
    }
    match.update(overrides)
    return match


class MapAlertTests(unittest.TestCase):
    def test_only_fresh_exact_validated_marine_match_gets_green_ring(self):
        seen = []
        def match(code):
            seen.append(code)
            return valid_match()
        event = highlights._atis_event(valid_atis(), match)
        self.assertEqual(seen, ["9244050123"])
        self.assertEqual(event["mmsi"], "244123456")
        self.assertEqual(event["remaining_seconds"], 25)
        self.assertEqual(event["event_id"], "9244050123|2026-10-23T11:34:56+02:00")

    def test_rejects_unmatched_stale_nonmarine_or_invalid_atis(self):
        for status in [
            valid_atis(fresh=False), valid_atis(mode_id="weather"),
            valid_atis(atis_code="0123"), valid_atis(age_seconds=31),
            valid_atis(age_seconds=float("nan")),
            valid_atis(received_at=""),
        ]:
            with self.subTest(status=status):
                with patch.object(highlights.receiver_monitor, "match_ais_atis") as matcher:
                    self.assertIsNone(highlights._atis_event(status, matcher))
                    matcher.assert_not_called()
        for result in [valid_match(matched=False), valid_match(latitude=91),
                       valid_match(mmsi="invalid")]:
            self.assertIsNone(highlights._atis_event(valid_atis(), lambda _: result))

    def test_emergency_categories_and_lifetime_are_same_as_monitor(self):
        result = highlights._emergency_rows({
            "ok": True, "vessels": [
                {"mmsi": "244123456", "category": "knrm",
                 "latitude": 51.91, "longitude": 4.31, "remaining_seconds": 295},
                {"mmsi": "244123457", "category": "waterpolitie",
                 "latitude": 51.92, "longitude": 4.32, "remaining_seconds": 20},
                {"mmsi": "244123458", "category": "unknown",
                 "latitude": 51.9, "longitude": 4.3, "remaining_seconds": 100},
                {"mmsi": "244123459", "category": "knrm",
                 "latitude": 51.9, "longitude": 4.3, "remaining_seconds": -1},
            ],
        })
        self.assertEqual([row["category"] for row in result], ["knrm", "waterpolitie"])
        self.assertEqual(result[0]["remaining_seconds"], 295)

    def test_missing_emergency_or_atis_service_cannot_fail_traffic_map(self):
        with patch.object(highlights.emergency_monitor, "map_highlights",
                          side_effect=RuntimeError("offline")), patch.object(
                              highlights.traffic_voice_atis, "get_status",
                              side_effect=RuntimeError("audio unavailable")):
            out = highlights.snapshot()
        self.assertTrue(out["ok"])
        self.assertTrue(out["read_only"])
        self.assertEqual(out["emergency_vessels"], [])
        self.assertIsNone(out["atis_match"])

    def test_allows_emergency_without_atis_and_no_new_classifications(self):
        rows = {"ok": True, "vessels": [{
            "mmsi": "244123456", "category": "knrm",
            "latitude": 51.91, "longitude": 4.32, "remaining_seconds": 300,
        }]}
        with patch.object(highlights.emergency_monitor, "map_highlights",
                          return_value=rows), patch.object(
                              highlights.traffic_voice_atis, "get_status",
                              return_value=valid_atis(fresh=False)):
            result = highlights.snapshot()
        self.assertEqual(len(result["emergency_vessels"]), 1)
        self.assertIsNone(result["atis_match"])


if __name__ == "__main__":
    unittest.main()
