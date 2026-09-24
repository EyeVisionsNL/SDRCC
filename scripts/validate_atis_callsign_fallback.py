#!/usr/bin/env python3
"""Regress Dutch ATIS identities paired with a foreign AIS MMSI, offline."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import receiver_monitor as monitor, traffic_voice


def barendsz(**changes):
    # AIS fields captured on 2026-09-23. The ATIS code is reconstructed from
    # PD4821 for this fixture; the original received packet was not retained.
    ship = dict(mmsi=205595190, callsign="PD4821", shipname="BARENDSZ",
                validated=1, last_signal=8, lat=51.894085, lon=4.32698)
    ship.update(changes)
    return ship


class CallsignFallbackTests(unittest.TestCase):
    def test_thirty_minute_boundary(self):
        for code in ("9244044821", "9205044821", "9205595190"):
            for age in (31, 601, 1799, 1800, 1801):
                with self.subTest(code=code, age=age):
                    result = self.match(barendsz(last_signal=age), code=code)
                    self.assertEqual(result["matched"], age <= 1800)
                    self.assertEqual(result["status"], "matched" if age <= 1800 else "stale")

    def match(self, *ships, code="9244044821", **kwargs):
        return monitor.match_ais_atis(code, payload={"ships": list(ships)}, **kwargs)

    def test_match_diagnostics_expose_missing_callsigns(self):
        result = self.match(
            barendsz(callsign=""),
            barendsz(mmsi=205595191, callsign="PD4822", last_signal=31),
        )
        self.assertFalse(result["matched"])
        self.assertEqual(result["ais_vessel_count"], 2)
        self.assertEqual(result["ais_with_callsign_count"], 1)
        self.assertEqual(result["ais_without_callsign_count"], 1)
        self.assertEqual(result["ais_validated_count"], 2)
        self.assertEqual(result["ais_fresh_count"], 2)

    def test_cross_flag_match(self):
        for mid in (244, 245, 246):
            with self.subTest(mid=mid):
                result = self.match(barendsz(callsign=" pd4821 "), code=f"9{mid}044821")
                self.assertTrue(result["matched"])
                self.assertEqual(result["mmsi"], "205595190")
                self.assertEqual(result["callsign"], "PD4821")
                self.assertEqual(result["match_method"], "callsign_exact_fallback")

    def test_fallback_keeps_validation(self):
        for changes, status in [
            ({"last_signal": 1801}, "stale"),
            ({"last_signal": None}, "stale"),
            ({"validated": 0}, "not_validated"),
            ({"lat": 91}, "invalid_position"),
            ({"mmsi": 123}, "invalid_position"),
            ({"callsign": "PD4822"}, "not_found"),
        ]:
            with self.subTest(changes=changes):
                result = self.match(barendsz(**changes))
                self.assertFalse(result["matched"])
                self.assertEqual(result["status"], status)
        self.assertEqual(self.match(barendsz(), max_age_seconds=7)["status"], "stale")

    def test_duplicate_callsign_rejected(self):
        result = self.match(barendsz(), barendsz(mmsi=205595191))
        self.assertFalse(result["matched"])
        self.assertEqual(result["status"], "ambiguous")

    def test_standard_match_preserved(self):
        result = self.match(barendsz(), code="9205044821")
        self.assertEqual(result["match_method"], "callsign_standard")
        self.assertTrue(result["matched"])
        result = self.match(barendsz(), code="9205595190")
        self.assertEqual(result["match_method"], "mmsi_direct")
        self.assertTrue(result["matched"])
        result = self.match(barendsz(mmsi=244690002, callsign="PF2323"), code="9244062323")
        self.assertTrue(result["matched"])
        self.assertEqual(result["match_method"], "callsign_standard")

    def test_standard_rejection_not_bypassed(self):
        standard = barendsz(mmsi=244595190, last_signal=1801)
        self.assertEqual(self.match(standard, barendsz())["status"], "stale")
        self.assertEqual(self.match(standard, barendsz(mmsi=244595191), barendsz())["status"], "ambiguous")

    def test_no_foreign_or_invalid_projection(self):
        for code in ("9211044821", "9244004821", "9244274821", "invalid"):
            with self.subTest(code=code):
                self.assertFalse(self.match(barendsz(), code=code)["matched"])

    def test_shared_feed_and_source(self):
        source = "http://127.0.0.1:8119/ships.json"
        with patch.object(monitor, "_read_ais_ships", return_value=({"ships": [barendsz()]}, source)) as reader:
            result = monitor.match_ais_atis("9244044821")
            reader.assert_called_once()
        self.assertTrue(result["matched"])
        self.assertEqual(result["source"], source)
        self.assertEqual(result["atis_code"], "9244044821")
        with patch.object(monitor, "_read_ais_ships", return_value=(None, None)):
            self.assertEqual(monitor.match_ais_atis("9244044821")["status"], "source_unavailable")

    def test_unmatched_atis_is_logged_once_and_recovery_is_logged(self):
        latest = {
            "fresh": True,
            "atis_code": "9244044821",
            "callsign": "PD4821",
            "received_at": "2026-09-24T18:00:00+02:00",
        }
        missing = {
            "matched": False,
            "status": "not_found",
            "candidate_count": 0,
            "ais_vessel_count": 37,
            "ais_with_callsign_count": 25,
            "ais_without_callsign_count": 12,
            "ais_fresh_count": 34,
        }
        recovered = {
            **missing,
            "matched": True,
            "status": "matched",
            "candidate_count": 1,
            "mmsi": "205595190",
            "callsign": "PD4821",
            "shipname": "BARENDSZ",
            "match_method": "callsign_exact_fallback",
        }
        with patch.object(traffic_voice, "_write_sdrcc_log") as write_log:
            traffic_voice._ATIS_AIS_LAST_EVENT_ID = None
            traffic_voice._ATIS_AIS_LAST_STATUS = None
            traffic_voice._log_atis_ais_result_once(latest, missing)
            traffic_voice._log_atis_ais_result_once(latest, missing)
            self.assertEqual(write_log.call_count, 1)
            self.assertEqual(write_log.call_args.args[0], "warning")
            self.assertIn("AIS_vessels=37", write_log.call_args.args[1])
            self.assertIn("without_callsign=12", write_log.call_args.args[1])
            traffic_voice._log_atis_ais_result_once(latest, recovered)
            self.assertEqual(write_log.call_count, 2)
            self.assertEqual(write_log.call_args.args[0], "info")
            self.assertIn("recovered=YES", write_log.call_args.args[1])

    def test_traffic_voice_projection(self):
        for fresh in (True, False):
            with self.subTest(fresh=fresh):
                snapshot = traffic_voice.get_snapshot(
                    service_reader=lambda service: {"service": service, "active": False, "state": "inactive"},
                    audio_reader=lambda: {"ok": True, "available": False, "stream_state": "WAITING"},
                    atis_reader=lambda: {"latest": {"fresh": fresh, "atis_code": "9244044821", "callsign": "PD4821"}},
                    ais_matcher=lambda code: self.match(barendsz(), code=code),
                )
                self.assertEqual(snapshot["ais_match"]["matched"], fresh)
                if fresh:
                    self.assertEqual(snapshot["possible_speaker"], "BARENDSZ · PD4821 · AIS MATCHED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
