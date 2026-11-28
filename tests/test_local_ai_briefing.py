"""Daily briefing fixtures; no receivers, network or AI engine."""
from datetime import datetime, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_ai_briefing as briefing, local_ai_anomaly as anomaly


class DailyBriefingTests(unittest.TestCase):
    def test_read_only_sources_and_window_boundaries(self):
        end=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            dbpath=root/briefing.reception.SOURCE
            dbpath.parent.mkdir(parents=True)
            with sqlite3.connect(dbpath) as db:
                db.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY,ais_on INTEGER,ais_fresh INTEGER,ais_rate REAL,ais_valid_range REAL,adsb_on INTEGER,adsb_targets INTEGER,adsb_rate REAL,adsb_range REAL)")
                db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",[
                    (end-86400,1,999,999,299,1,999,999,499),
                    (end-60,1,20,5,50,1,30,10,100),
                    (end,1,25,8,60,1,40,20,120),
                    (end+1,1,999,999,299,1,999,999,499)])
            missionpath=root/briefing.missions.SOURCE
            missionpath.parent.mkdir(parents=True)
            missionpath.write_text(json.dumps([
                {"result":"SUCCESS","ended_at":briefing.reception.utc(end-10),"image_count":4},
                {"result":"SUCCESS","ended_at":briefing.reception.utc(end),"pipeline":"simulation_test","image_count":99},
                {"result":"CANCELLED","ended_at":briefing.reception.utc(end)},
                {"result":"SUCCESS","ended_at":briefing.reception.utc(end-86400),"image_count":999},
                {"result":"SUCCESS","ended_at":briefing.reception.utc(end+1),"image_count":999}
            ]))
            atispath=root/"data/analytics/atis_statistics.sqlite3"
            with sqlite3.connect(atispath) as db:
                db.execute("CREATE TABLE atis_events(ts REAL,decoded INTEGER,ais_matched INTEGER,photo_found INTEGER)")
                db.executemany("INSERT INTO atis_events VALUES(?,?,?,?)",[(end-86400,1,1,1),(end-1,1,0,0),(end,0,0,0),(end+1,1,1,1)])
            state=anomaly.defaults()
            state["history"]=[{"id":"1","rule":"ram","title":"RAM","transition":"opened","timestamp":briefing.reception.utc(end-60),"detail":"1 GiB"},
                              {"id":"1","rule":"ram","title":"RAM","transition":"cleared","timestamp":briefing.reception.utc(end),"detail":"4 GiB"}]
            anomaly.save(root,state)
            paths=[dbpath,missionpath,atispath,root/anomaly.SOURCE]
            before=[p.read_bytes() for p in paths]
            with patch.object(briefing.maritime.features,"feature_enabled",return_value=True):
                data=briefing.snapshot(root,now=end)
            self.assertEqual(data["reception"]["samples"],2)
            self.assertEqual(data["reception"]["ais"]["targets"]["peak"],25)
            self.assertEqual(data["missions"]["summary"]["missions"],2)
            self.assertEqual(data["missions"]["summary"]["success_pct"],100)
            self.assertEqual(data["missions"]["summary"]["images"],4)
            self.assertEqual(data["atis"]["candidates"],2)
            self.assertEqual(data["atis"]["decoded"],1)
            self.assertEqual(data["alerts"]["opened"],1)
            self.assertEqual(data["alerts"]["cleared"],1)
            self.assertEqual(data["alerts"]["status"],"partial")
            self.assertEqual([p.read_bytes() for p in paths],before)
            self.assertFalse((root/briefing.DIRECTORY).exists())

    def test_archive_once_retention_and_restart(self):
        now=datetime(2026,11,28,0,5,tzinfo=timezone.utc).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(briefing.maritime.features,"feature_enabled",return_value=True):
                self.assertFalse(briefing.archive_once(root,lambda:False,now=now))
                self.assertFalse(briefing.archive_once(root,lambda:True,now=now-1))
                self.assertEqual(list(root.iterdir()),[])
                self.assertTrue(briefing.archive_once(root,lambda:True,now=now))
                self.assertFalse(briefing.archive_once(root,lambda:True,now=now+60))
                archive=briefing.snapshot(root,"2026-11-27",now=now)
                self.assertEqual(archive["window_start_utc"],"2026-11-27T00:00:00+00:00")
                self.assertEqual(archive["window_end_utc"],"2026-11-28T00:00:00+00:00")
                self.assertEqual(archive["mode"],"archive")
                self.assertIsNone(archive["alerts"]["opened"])
                self.assertEqual(archive["available_dates"],["2026-11-27"])
                directory=root/briefing.DIRECTORY
                (directory/"unrelated.json").write_text("{}")
                with patch.object(briefing,"KEEP",2):
                    for offset in (86400,172800):
                        self.assertTrue(briefing.archive_once(root,lambda:True,now=now+offset))
                    self.assertEqual(briefing.archive_days(root),["2026-11-29","2026-11-28"])
                self.assertTrue((directory/"unrelated.json").exists())
                self.assertEqual(briefing.snapshot(root,"2026-11-27")["status"],"unavailable")

    def test_date_validation_and_disable_during_build(self):
        for value in ("../other","2026-02-30","2026-1-1",None,True):
            with self.assertRaises(ValueError):
                briefing.day_key(value)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            now=datetime(2026,11,28,1,tzinfo=timezone.utc).timestamp()
            with patch.object(briefing,"build",return_value={}),patch.object(briefing.maritime.features,"feature_enabled",return_value=True):
                allowed=iter([True,False])
                self.assertFalse(briefing.archive_once(root,lambda:next(allowed),now=now))
            self.assertEqual(list(root.iterdir()),[])
