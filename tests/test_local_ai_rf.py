"""Offline RF experiment fixtures; never change receivers."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_ai_rf as rf, local_ai_memory as memory


class RFTests(unittest.TestCase):
    now=1770000000
    body={"service":"adsb","category":"lna","period":"24h","title":"New LNA","details":"Old vs new"}

    def populate(self,root):
        path=root/rf.reception.SOURCE
        path.parent.mkdir(parents=True)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY, ais_on INTEGER, ais_fresh INTEGER, ais_rate REAL, ais_valid_range REAL, adsb_on INTEGER, adsb_targets INTEGER, adsb_rate REAL, adsb_range REAL)")
            start=self.now-rf.GAP
            end=self.now+rf.GAP+86400
            db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",[
                (boundary-i*60,1,100,10,30,1,targets,rate,rng)
                for boundary,targets,rate,rng in [(start,30,100,80),(end,60,150,120)]
                for i in range(1440)])
            db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)",(self.now,1,999,999,299,1,999,999,499))
        return path

    def test_record_wait_compare_finalize_and_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(rf.snapshot(root)["status"],"empty")
            self.assertEqual(list(root.iterdir()),[])
            path=self.populate(root)
            original=path.read_bytes()
            ident=rf.record(root,self.body,now=self.now)
            self.assertEqual(memory.snapshot(root)["total"],1)
            self.assertEqual(rf.snapshot(root,ident,now=self.now)["experiment"]["status"],"measuring")
            self.assertEqual(rf.snapshot(root,ident,now=self.now)["experiment"]["before"]["adsb"]["targets"]["mean"],30)
            with self.assertRaises(ValueError):
                rf.finalize(root,ident,now=self.now)
            end=self.now+rf.GAP+86400
            data=rf.snapshot(root,ident,now=end)["experiment"]
            self.assertEqual(data["status"],"ready")
            self.assertEqual(data["metrics"]["targets"]["change_pct"],100)
            self.assertEqual(data["metrics"]["rate"]["change_pct"],50)
            self.assertEqual(data["metrics"]["range_nm"]["change_pct"],50)
            self.assertEqual(data["before"]["samples"],1440)
            self.assertEqual(data["after"]["samples"],1440)
            self.assertEqual(path.read_bytes(),original)
            rf.finalize(root,ident,now=end)
            path.unlink()
            saved=rf.snapshot(root,ident,now=end+86400)["experiment"]
            self.assertTrue(saved["saved"])
            self.assertEqual(saved["metrics"]["rate"]["change_pct"],50)
            self.assertIn("rate: +50.0%",memory.snapshot(root)["entries"][0]["outcome"])
            rf.finalize(root,ident,now=end+1)
            rf.delete(root,ident)
            self.assertEqual(rf.snapshot(root)["status"],"empty")
            self.assertEqual(memory.snapshot(root)["total"],1)

    def test_overlap_and_missing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.populate(root)
            ident=rf.record(root,self.body,now=self.now)
            rf.record(root,dict(self.body,service="ais"),now=self.now+60)
            end=self.now+rf.GAP+86400
            self.assertEqual(rf.snapshot(root,ident,now=end)["experiment"]["status"],"ready")
            rf.record(root,self.body,now=self.now+120)
            data=rf.snapshot(root,ident,now=end)["experiment"]
            self.assertEqual(data["intervening_changes"],1)
            self.assertEqual(data["metrics"]["targets"]["status"],"intervening_change")
            self.assertIsNone(data["metrics"]["targets"]["change_pct"])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            ident=rf.record(root,self.body,now=self.now)
            data=rf.snapshot(root,ident,now=end)["experiment"]
            self.assertEqual(data["status"],"insufficient")
            self.assertIsNone(data["metrics"]["rate"]["change_pct"])
            self.assertFalse((root/rf.reception.SOURCE).exists())

    def test_metric_guards(self):
        def w(mean,active=100,valid=100,coverage=100,stale=False):
            return {"status":"ok","coverage_pct":coverage,"expected_samples":100,"latest_sample_stale":stale,
                    "adsb":{"active_samples":active,"rate":{"mean":mean,"peak":mean,"valid_samples":valid}}}
        for current,baseline in [(w(20,active=70,valid=70),w(10)),(w(20,valid=70),w(10)),
                                 (w(20),w(10,coverage=74)),(w(20),w(10,stale=True)),(w(20),w(0))]:
            self.assertIsNone(rf.comparison(current,baseline,"adsb","rate",False)["change_pct"])
        self.assertEqual(rf.comparison(w(0),w(10),"adsb","rate",False)["change_pct"],-100)

    def test_atomic_notebook_capacity_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with self.assertRaises(ValueError):
                rf.record(root,dict(self.body,period="30d"),now=self.now)
            with patch.object(memory,"MAX_ENTRIES",0):
                with self.assertRaises(ValueError):
                    rf.record(root,self.body,now=self.now)
            self.assertEqual(rf.snapshot(root)["status"],"empty")
            self.assertEqual(memory.snapshot(root)["total"],0)
            with self.assertRaises(ValueError):
                rf.snapshot(root,True)
            ident=rf.record(root,self.body,now=self.now)
            db=root/memory.SOURCE; before=db.read_bytes()
            data=rf.snapshot(root,ident,now=self.now)
            self.assertEqual(db.read_bytes(),before)
            self.assertNotIn("experiments",rf.model_evidence(data))
            self.assertEqual(rf.model_evidence(data)["experiment_count"],1)
