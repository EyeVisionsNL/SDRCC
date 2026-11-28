"""Offline anomaly tests. No radio, subprocess, network or model inference."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_ai_anomaly as anomaly, local_ai_memory as memory


class AnomalyTests(unittest.TestCase):
    def test_history_comparison_and_active_coverage(self):
        now=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); path=root/anomaly.reception.SOURCE; path.parent.mkdir(parents=True)
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE samples(ts INTEGER PRIMARY KEY,ais_on INTEGER,ais_fresh INTEGER,ais_rate REAL,adsb_on INTEGER,adsb_rate REAL)")
                for day in range(4):
                    db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?)",
                        [(now-day*86400-i*60,1,50,20 if day==0 else 100,1,100) for i in range(15)])
            before=path.read_bytes()
            checks=anomaly.history_checks(root,now)
            self.assertEqual(checks["analytics"]["state"],"ok")
            self.assertEqual(checks["ais_rate"]["state"],"bad")
            self.assertEqual(checks["adsb_rate"]["state"],"ok")
            self.assertEqual(path.read_bytes(),before)
            with sqlite3.connect(path) as db:
                db.execute("UPDATE samples SET ais_on=0 WHERE ts>? AND ts<=?",(now-900,now))
            self.assertEqual(anomaly.history_checks(root,now)["ais_rate"]["state"],"unknown")
            self.assertEqual(anomaly.history_checks(root,now+600)["analytics"]["state"],"bad")

    def test_episode_confirmation_unknown_hysteresis_clear(self):
        state=anomaly.defaults()
        streak={}
        for i in range(2):
            self.assertEqual(anomaly.advance(state,streak,{"ram":anomaly.result("bad","1 GiB")},100+i),[])
        events=anomaly.advance(state,streak,{"ram":anomaly.result("bad","1 GiB")},102)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]["transition"],"opened")
        first=events[0]["id"]
        for i in range(6):
            self.assertEqual(anomaly.advance(state,streak,{},103+i),[])
        self.assertIn("ram",state["active"])
        for i in range(2):
            self.assertEqual(anomaly.advance(state,streak,{"ram":anomaly.result("ok","4 GiB")},110+i),[])
        self.assertEqual(anomaly.advance(state,streak,{"ram":anomaly.result("hold","2.5 GiB")},112),[])
        for i in range(2):
            self.assertEqual(anomaly.advance(state,streak,{"ram":anomaly.result("ok","4 GiB")},120+i),[])
        event=anomaly.advance(state,streak,{"ram":anomaly.result("ok","4 GiB")},122)[0]
        self.assertEqual(event["transition"],"cleared")
        self.assertEqual(event["id"],first)
        self.assertNotIn("ram",state["active"])
        self.assertEqual(len(state["outbox"]),2)

    def test_worker_persistence_memory_and_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); monitor=anomaly.Monitor(root)
            bad={"ram":anomaly.result("bad","1 GiB")}
            with patch.object(anomaly,"collect",return_value=bad) as collect:
                monitor.tick(lambda:False,now=100)
                collect.assert_not_called()
                self.assertEqual(list(root.iterdir()),[])
                for i in range(5):
                    monitor.tick(lambda:True,now=100+i*60)
            self.assertEqual(len(monitor.snapshot()["active"]),1)
            self.assertEqual(memory.snapshot(root)["total"],1)
            self.assertEqual(monitor.snapshot()["memory_pending"],0)
            again=anomaly.Monitor(root)
            with patch.object(anomaly,"collect",return_value=bad):
                for i in range(3):
                    again.tick(lambda:True,now=500+i*60)
            self.assertEqual(memory.snapshot(root)["total"],1)
            again.configure(False,False)
            with patch.object(anomaly,"collect") as collect:
                again.tick(lambda:True,now=800)
                collect.assert_not_called()
            self.assertEqual(again.snapshot()["status"],"paused")
            self.assertEqual(len(again.snapshot()["active"]),1)
            again.configure(True,False)
            with patch.object(anomaly,"collect",return_value={"ram":anomaly.result("ok","4 GiB")}):
                for i in range(3):
                    again.tick(lambda:True,now=900+i*60)
            self.assertEqual(again.snapshot()["active"],[])
            self.assertEqual(memory.snapshot(root)["total"],2)

    def test_outbox_retries_and_gap_resets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); monitor=anomaly.Monitor(root)
            with patch.object(anomaly,"collect",return_value={"ram":anomaly.result("bad","1 GiB")}):
                monitor.tick(lambda:True,now=100)
                monitor.tick(lambda:True,now=160)
                monitor.tick(lambda:True,now=400)
                self.assertFalse(monitor.snapshot()["active"])
                monitor.tick(lambda:True,now=460)
                with patch.object(anomaly,"persist_memory",side_effect=ValueError("full")):
                    monitor.tick(lambda:True,now=520)
                self.assertEqual(monitor.snapshot()["memory_pending"],1)
                self.assertEqual(monitor.snapshot()["memory_error"],"full")
                again=anomaly.Monitor(root)
                again.tick(lambda:True,now=580)
                self.assertEqual(again.snapshot()["memory_pending"],0)
                self.assertEqual(memory.snapshot(root)["total"],1)
                self.assertEqual(len(again.snapshot()["active"]),1)

    def test_mqtt_only_opted_in_and_only_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); monitor=anomaly.Monitor(root)
            with patch.object(anomaly,"collect",return_value={"ram":anomaly.result("bad","1 GiB")}),patch("core.emergency_monitor.publish_station_anomaly",return_value="Queued") as send:
                monitor.configure(True,True)
                for i in range(6):
                    monitor.tick(lambda:True,now=100+i*60)
                send.assert_called_once()
                self.assertEqual(send.call_args.args[0]["transition"],"opened")
                self.assertEqual(monitor.snapshot()["mqtt_result"],"Queued")

    def test_mqtt_separate_topic(self):
        from core import emergency_monitor
        from unittest.mock import MagicMock
        client=MagicMock()
        client.publish.return_value.rc=0
        event={"id":"123","rule":"ram","title":"RAM","transition":"opened","timestamp":"2026-01-01T00:00:00+00:00","detail":"1 GiB"}
        with patch.object(emergency_monitor,"_mqtt_client",client),patch.object(emergency_monitor,"_mqtt_ha_active",True),patch.dict(emergency_monitor._runtime,{"mqtt":"CONNECTED"}):
            self.assertIn("Queued",emergency_monitor.publish_station_anomaly(event))
            self.assertEqual(client.publish.call_args.args[0],"sdrcc/intelligence/anomalies")
            self.assertFalse(client.publish.call_args.kwargs["retain"])
