"""Offline recovery history regression fixtures."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core import local_ai_recovery as recovery, local_ai_memory as memory


class RecoveryHistoryTests(unittest.TestCase):
    def test_recovered_episode_survives_restart_and_is_not_double_counted(self):
        now = 1795887600
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "logs/sdrcc.log"
            log.parent.mkdir()
            def line(offset, message):
                return f"[{datetime.fromtimestamp(now+offset):%Y-%m-%d %H:%M:%S}] {message}\n"
            log.write_text(
                line(-180, "Managed SDRCC update requested: 0.80.22 -> 0.80.23 via develop")+
                line(-60, "RECEIVER AUTO RECOVERY: RX02 readsb.service; attempt 1/2")+
                line(-59, "RECEIVER USB RESET: RX02 USB reset OK: private serial")+
                line(-59, "RECEIVER AUTO RECOVERY: RX02 USB reset failed: private serial")+
                line(-55, "RECEIVER AUTO RECOVERY: RX02 readsb.service; attempt 2/2")+
                line(-54, "RECEIVER AUTO RECOVERY: RX02 USB reset OK: private serial")+
                line(-45, "RECEIVER AUTO RECOVERY: RX02 readsb.service running; runtime verified")+
                line(-40, "RECEIVER RECOVERY: RX01 - reservation=False"))
            with patch("core.emergency_monitor.publish_station_anomaly") as mqtt:
                recovery.collect(root, now=now, notify=True)
                recovery.collect(root, now=now+1, notify=True)
                mqtt.assert_not_called()
            data = recovery.snapshot(root, now=now+1)
            for window in recovery.WINDOWS:
                self.assertEqual(data["windows"][window], dict(automatic=1,verified=1,failed=0,unconfirmed=0,manual=1))
            incident = data["recent"][1]
            self.assertEqual((incident["attempts"],incident["seconds"],incident["outcome"]),(2,15,"verified"))
            self.assertIn("update: 0.80.22 -> 0.80.23",incident["context"])
            self.assertNotIn("private serial",str(data))
            notebook = memory.snapshot(root, now=now+1)
            self.assertEqual(notebook["total"],2)
            self.assertEqual(data["memory_pending"],0)
            log.unlink()
            self.assertEqual(recovery.snapshot(root, now=now+3600)["status"],"stale")
            self.assertEqual(recovery.snapshot(root, now=now+3600)["windows"]["24h"]["verified"],1)

    def test_missing_history_and_manual_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(recovery.snapshot(root)["status"],"unavailable")
            self.assertEqual(list(root.iterdir()),[])
        rows=[("a",1,"RX02","readsb","attempt",1,""),
              ("b",3,"RX02","","failed",0,""),
              ("c",4,"RX02","","manual_completed",0,""),
              ("d",5,"RX02","readsb","attempt",1,"")]
        self.assertEqual([x["outcome"] for x in recovery.group(rows)],["failed","manual_completed","unconfirmed"])

    def test_new_terminal_event_notified_once_after_bootstrap(self):
        now = 1795887600
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "logs/sdrcc.log"
            log.parent.mkdir()
            log.write_text("")
            with patch("core.emergency_monitor.publish_station_anomaly") as mqtt:
                recovery.collect(root, now=now, notify=True)
                log.write_text(f"[{datetime.fromtimestamp(now+1):%Y-%m-%d %H:%M:%S}] RECEIVER AUTO RECOVERY: RX02 readsb.service; attempt 1/2\n"
                               f"[{datetime.fromtimestamp(now+2):%Y-%m-%d %H:%M:%S}] RECEIVER AUTO RECOVERY: RX02 FAILED; retry budget exhausted; service stopped\n")
                recovery.collect(root, now=now+3, notify=True)
                recovery.collect(root, now=now+4, notify=True)
                mqtt.assert_called_once()
                self.assertEqual(mqtt.call_args.args[0]["transition"],"failed")
            data=recovery.snapshot(root, now=now+4)
            self.assertEqual(data["windows"]["24h"]["failed"],1)
