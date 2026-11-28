"""Temporary SQLite fixtures only; no station data or radio services."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_ai_reception as reception


class ReceptionEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / reception.SOURCE
        self.now = 1770000000

    def create(self, legacy=False):
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY, ais_on INTEGER, ais_targets INTEGER, ais_rate REAL, ais_range REAL, adsb_on INTEGER, adsb_targets INTEGER, adsb_rate REAL, adsb_range REAL" + ("" if legacy else ", ais_fresh INTEGER, ais_valid_range REAL") + ")")
            if legacy:
                db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)", (self.now-60,1,999,30,800,1,12,4,80))
                return
            for row in [
                (self.now-300,1,999,12,999,1,4,5,100,10,60),
                (self.now-240,1,999,8,999,1,0,0,None,0,None),
                (self.now-180,1,777,100,999,0,99,99,999,None,None),
                (self.now-120,0,900,200,999,1,8,10,600,900,280),
                (self.now-60,1,None,None,None,1,None,None,None,None,None),
                (self.now-86401,1,888,999,999,1,20,7,90,100,100),
                (self.now+1,1,999,999,999,1,99,99,90,99,99),
            ]:
                db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)", row)

    def read(self, period="24h"):
        return reception.read_evidence(self.root, period, now=self.now)

    def test_missing_does_not_create_database(self):
        self.assertEqual(self.read()["status"], "unavailable")
        self.assertFalse(self.path.parent.exists())

    def test_aggregates_are_read_only_and_distinguish_null_zero_legacy_inactive(self):
        self.create()
        before = self.path.read_bytes()
        r = self.read()
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["samples"], 5)
        self.assertEqual(r["ais"]["targets"], {"valid_samples":2,"mean":5.0,"peak":10})
        self.assertEqual(r["ais"]["rate"], {"valid_samples":2,"mean":10.0,"peak":12})
        self.assertEqual(r["ais"]["range_nm"]["valid_samples"], 1)
        self.assertEqual(r["ais"]["active_samples"], 4)
        self.assertEqual(r["adsb"]["targets"], {"valid_samples":3,"mean":4.0,"peak":8})
        self.assertEqual(r["adsb"]["range_nm"]["peak"], 100)
        self.assertEqual(r["latest_sample_age_seconds"],60)
        self.assertEqual(r["scope"], "whole station; simultaneous sampled targets, not unique totals")
        self.assertEqual(self.read("7d")["samples"], 6)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.path.parent.iterdir()), {self.path.name})

    def test_stale_history_is_not_live_status(self):
        self.create()
        r = reception.read_evidence(self.root,"24h",now=self.now+3600)
        self.assertTrue(r["latest_sample_stale"])
        self.assertEqual(r["status"],"ok")
        self.assertEqual(r["latest_sample_age_seconds"],3599)

    def test_legacy_schema_ais_is_not_invented_or_migrated(self):
        self.create(legacy=True)
        before = self.path.read_bytes()
        r = self.read()
        self.assertEqual(r["ais"]["targets"]["valid_samples"],0)
        self.assertIsNone(r["ais"]["targets"]["mean"])
        self.assertIsNone(r["ais"]["range_nm"]["peak"])
        self.assertEqual(r["adsb"]["targets"]["mean"],12)
        self.assertEqual(self.path.read_bytes(),before)

    def test_empty_window_and_row_cap(self):
        self.create()
        self.assertEqual(reception.read_evidence(self.root,"24h",now=self.now+86401)["status"],"no_samples")
        with patch.object(reception,"MAX_ROWS",2):
            self.assertEqual(self.read()["status"],"unavailable")

    def test_corrupt_database_and_timeout_are_unavailable(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"not sqlite")
        self.assertEqual(self.read()["status"],"unavailable")
        self.path.unlink()
        self.path.parent.rmdir()
        self.create()
        with patch.object(reception,"QUERY_SECONDS",-1):
            # Expand enough for the SQLite VM progress callback to fire.
            with sqlite3.connect(self.path) as db:
                db.executemany("INSERT INTO samples(ts,ais_on,ais_fresh) VALUES(?,1,1)", [(self.now-i,) for i in range(1000,2000)])
            self.assertEqual(self.read()["status"],"unavailable")

    def test_period_selection_is_allowlisted(self):
        for question, expected in [
            ("Hoeveel schepen gemiddeld afgelopen week?", "7d"),
            ("ADS-B last month", "30d"),
            ("AIS ontvangst afgelopen dag", "24h"),
            ("Hallo", None),
            ("AIS 24h versus 7d", None),
        ]:
            self.assertEqual(reception.select_period(question,"auto"), expected)
        self.assertEqual(reception.select_period("hello","7d"),"7d")
        self.assertIsNone(reception.select_period("AIS last week","none"))
        for mode in ("SELECT * FROM samples", "../database", [], None):
            with self.assertRaises(ValueError):
                reception.select_period("AIS",mode)
