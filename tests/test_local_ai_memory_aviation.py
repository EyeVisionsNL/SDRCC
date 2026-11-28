"""Offline fixtures for aviation and the explicitly managed local notebook."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from core import local_ai_aviation as aviation, local_ai_memory as memory


class AviationTests(unittest.TestCase):
    def test_aggregate_freshness_radius_dedup_and_ground(self):
        now=1770000000
        home={"configured":True,"latitude":51.9,"longitude":4.3}
        def row(ident,**kw):
            return dict({"hex":ident,"lat":51.9,"lon":4.31,"seen":1,"seen_pos":1,"alt_baro":10000,"gs":200,"category":"A3"},**kw)
        rows=[row("123451"),row("123451",seen_pos=10,alt_baro=30000),
              row("123452",category="A7",alt_baro=2000,gs=100),
              row("123453",alt_baro="ground",gs=5),
              row("123454",category="C1"),row("123455",seen_pos=31),
              row("123456",lat=54),row("123457",alt_baro=None,gs=None),
              row("123458",seen=None),row("bad")]
        data=aviation.summarize({"now":now,"aircraft":rows},home,25,now)
        self.assertEqual(data["aircraft"],4)
        self.assertEqual(data["helicopters"],1)
        self.assertEqual(data["ground_aircraft"],1)
        self.assertEqual(data["surface_targets_excluded"],1)
        self.assertEqual(data["altitude_mean_ft"],6000)
        self.assertEqual(data["speed_mean_knots"],150)
        self.assertEqual(data["altitude_bands"]["Unknown"],1)
        self.assertNotIn("123451",json.dumps(data))
        self.assertEqual(aviation.summarize({"now":now-6,"aircraft":rows},home,25,now)["status"],"unavailable")
        self.assertEqual(aviation.summarize({"now":now,"aircraft":[]},home,25,now)["aircraft"],0)
        self.assertEqual(aviation.summarize({"now":now,"aircraft":[]},{},25,now)["status"],"unavailable")

    def test_stale_file_and_inactive_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"aircraft.json"
            path.write_text('{"aircraft":[]}')
            os.utime(path,(100,100))
            self.assertIsNone(aviation.fresh_json([path],106,5))
            self.assertEqual(aviation.fresh_json([path],104,5),{"aircraft":[]})
            with patch("core.local_ai_health.observe_service",return_value={"state":"inactive"}),patch.object(aviation,"fresh_json") as read:
                self.assertEqual(aviation.snapshot(Path(tmp),25,now=100)["status"],"inactive")
                read.assert_not_called()


class MemoryTests(unittest.TestCase):
    def test_notes_search_delete_and_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(memory.snapshot(root)["status"],"empty")
            self.assertEqual(list(root.iterdir()),[])
            memory.add(root,{"entry_kind":"hardware","title":"New antenna","details":"Gain test","outcome":"Not measured"},now=100)
            memory.add(root,{"entry_kind":"incident","title":"USB error","details":"Wedged","outcome":"Reset"},now=200)
            path=root/memory.SOURCE
            before=path.read_bytes()
            data=memory.snapshot(root,"antenna")
            self.assertEqual(data["total"],2)
            self.assertEqual(data["matched"],1)
            self.assertEqual(data["entries"][0]["title"],"New antenna")
            self.assertEqual(memory.snapshot(root,"' OR 1=1 --")["matched"],0)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            memory.delete(root,data["entries"][0]["id"])
            self.assertEqual(memory.snapshot(root)["total"],1)
            with self.assertRaises(ValueError):
                memory.delete(root,True)
            with self.assertRaises(ValueError):
                memory.add(root,{"entry_kind":"other","title":"bad"})
            with self.assertRaises(ValueError):
                memory.add(root,{"entry_kind":"note","title":"x"*101})
            with patch.object(memory,"MAX_ENTRIES",1):
                with self.assertRaises(ValueError):
                    memory.add(root,{"entry_kind":"note","title":"full"})

    def test_import_dedup_and_no_raw_log_content(self):
        now=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            log=root/"logs/sdrcc.log";log.parent.mkdir()
            log.write_text(f"[{datetime.fromtimestamp(now-10):%Y-%m-%d %H:%M:%S}] USB reset OK: SECRET_SERIAL\n")
            journal=json.dumps({"__REALTIME_TIMESTAMP":str(int((now-20)*1e6)),"__CURSOR":"test-cursor","MESSAGE":"SDR wedged SECRET_IDENTIFIER"})
            with patch.object(memory.health,"command",side_effect=["",journal]):
                first=memory.import_events(root,now=now)
            with patch.object(memory.health,"command",side_effect=["",journal]):
                second=memory.import_events(root,now=now)
            self.assertEqual(first["added"],2)
            self.assertEqual(second["added"],0)
            data=memory.snapshot(root)
            self.assertEqual(data["total"],2)
            self.assertNotIn("SECRET",json.dumps(data))
            self.assertEqual(data["counts"]["incident"],2)

    def test_model_excerpt_and_paging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for i in range(12):
                memory.add(root,{"entry_kind":"note","title":str(i),"details":"d"*500,"outcome":"o"*300},now=i)
            data=memory.snapshot(root)
            self.assertEqual(len(data["entries"]),10)
            self.assertEqual(len(memory.snapshot(root,page=2)["entries"]),2)
            excerpt=memory.model_evidence(data)
            self.assertEqual(len(excerpt["entries"]),6)
            self.assertEqual(len(excerpt["entries"][0]["details"]),240)
            self.assertEqual(len(data["entries"][0]["details"]),500)
