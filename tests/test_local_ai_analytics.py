"""Offline comparison and mission evidence fixtures; never operate receivers."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from core import local_ai_performance as performance, local_ai_missions as missions


class PerformanceTests(unittest.TestCase):
    def test_real_database_windows_and_active_only(self):
        now=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            path=root/performance.reception.SOURCE
            path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY, ais_on INTEGER, ais_fresh INTEGER, ais_rate REAL, ais_valid_range REAL, adsb_on INTEGER, adsb_targets INTEGER, adsb_rate REAL, adsb_range REAL)")
                rows=[]
                for i in range(11520):
                    current=i<1440
                    active=int(i%10!=0)
                    rows.append((now-i*60,active,20 if current else 10,30 if current else 20,100 if current else 80,active,40,0 if current else 10,200))
                db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",rows)
            before=path.read_bytes()
            data=performance.snapshot(root,now=now)
            self.assertEqual(data["status"],"ok")
            self.assertEqual(data["current"]["samples"],1440)
            self.assertEqual(data["baseline"]["samples"],10080)
            self.assertEqual(data["current"]["window_start_utc"],data["baseline"]["window_end_utc"])
            ais=data["services"]["ais"]
            self.assertEqual(ais["metrics"]["targets"]["change_pct"],100)
            self.assertEqual(ais["metrics"]["rate"]["change_pct"],50)
            self.assertEqual(ais["metrics"]["range_nm"]["change_pct"],25)
            self.assertEqual(ais["current_active_samples"],1296)
            self.assertEqual(data["services"]["adsb"]["metrics"]["rate"]["change_pct"],-100)
            self.assertEqual(path.read_bytes(),before)

    def test_insufficient_zero_and_stale_comparisons(self):
        def window(mean,coverage=100,n=100,stale=False):
            return {"status":"ok","coverage_pct":coverage,"latest_sample_stale":stale,"ais":{"active_samples":100,"rate":{"mean":mean,"valid_samples":n,"peak":mean}}}
        for a,b,expected in (
            (window(2,coverage=30),window(1),"insufficient"),
            (window(2,n=59),window(1),"insufficient"),
            (window(2),window(0),"zero_baseline"),
            (window(2,stale=True),window(1),"stale"),
            (window(None),window(1),"insufficient"),
        ):
            result=performance.compare(a,b,"ais","rate")
            self.assertIsNone(result["change_pct"])
            self.assertEqual(result["status"],expected)

    def test_no_database_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(performance.snapshot(root)["status"],"insufficient")
            self.assertEqual(list(root.iterdir()),[])


class MissionTests(unittest.TestCase):
    def test_real_missions_periods_missing_values_and_simulations(self):
        now=1770000000
        date=lambda seconds:datetime.fromtimestamp(now-seconds,timezone.utc).isoformat()
        rows=[
            {"satellite":"METEOR-M2 3","receiver":"SDR1","result":"SUCCESS","ended_at":date(100),"peak_snr_db":8,"image_count":19,"frames":100,"max_elevation":77,"quality_score":80},
            {"satellite":"METEOR-M2 4","receiver":"SDR2","result":"NO SYNC","ended_at":date(200),"peak_snr_db":-2,"image_count":0,"max_elevation":20},
            {"satellite":"METEOR-M2 3","receiver":"SDR1","result":"CANCELLED","ended_at":date(300)},
            {"satellite":"METEOR-M2 3","result":"UNKNOWN","ended_at":date(400),"peak_snr_db":"NaN","image_count":"bad"},
            {"satellite":"METEOR-M2 3","result":"SUCCESS","ended_at":date(86400*10),"peak_snr_db":10,"image_count":20,"max_elevation":45},
            {"satellite":"SIM","pipeline":"simulation_success","result":"SUCCESS","ended_at":date(100),"peak_snr_db":99,"image_count":999},
            {"satellite":"SIM2","output_path":"/tmp/data/simulations/test","result":"SUCCESS"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/missions.SOURCE; path.parent.mkdir(parents=True)
            path.write_text(json.dumps(rows))
            before=path.read_bytes()
            data=missions.snapshot(root,"7d",now=now)
            m=data["summary"]
            self.assertEqual(data["excluded_simulations"],2)
            self.assertEqual(m["missions"],4)
            self.assertEqual(m["completed"],2)
            self.assertEqual(m["success_pct"],50)
            self.assertEqual(m["unknown_result"],1)
            self.assertEqual(m["cancelled"],1)
            self.assertEqual(m["peak_snr_mean_db"],3)
            self.assertEqual(m["snr_samples"],2)
            self.assertEqual(m["images"],19)
            self.assertEqual(m["image_samples"],2)
            self.assertEqual(m["frames"],100)
            self.assertEqual(data["elevation"][0]["name"],"0–29°")
            self.assertEqual(missions.snapshot(root,"all",now=now)["summary"]["missions"],5)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(list(path.parent.iterdir()),[path])

    def test_missing_empty_corrupt_and_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/missions.SOURCE
            self.assertEqual(missions.snapshot(root)["status"],"unavailable")
            self.assertEqual(list(root.iterdir()),[])
            path.parent.mkdir(parents=True)
            path.write_text("[]")
            self.assertEqual(missions.snapshot(root)["status"],"no_missions")
            self.assertIsNone(missions.snapshot(root)["summary"]["success_pct"])
            path.write_text("{")
            self.assertEqual(missions.snapshot(root)["status"],"unavailable")
            path.write_text(json.dumps([{}]*501))
            self.assertEqual(missions.snapshot(root)["status"],"unavailable")

    def test_group_bound_and_undated(self):
        rows=[{"satellite":str(i),"result":"CANCELLED"} for i in range(12)]
        groups=missions.group_summary(rows,"satellite")
        self.assertEqual(len(groups["groups"]),missions.MAX_GROUPS)
        self.assertEqual(groups["omitted_groups"],12-missions.MAX_GROUPS)
        self.assertIsNone(groups["groups"][0]["success_pct"])
