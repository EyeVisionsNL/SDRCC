"""Observer fixtures: no live station, service control, writes or AI engine."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import local_ai_health as health, local_ai_maritime as maritime


class StationHealthTests(unittest.TestCase):
    def test_service_state_and_log_classification(self):
        with patch.object(health,"command",return_value="LoadState=loaded\nActiveState=activating\nSubState=auto-restart\nNRestarts=3\n") as command:
            service=health.observe_service("ADS-B")
            self.assertEqual(service["status"],"attention")
            self.assertEqual(service["restart_count"],3)
            self.assertEqual(command.call_args.args[0][:3],["systemctl","show","readsb.service"])
        counts=health.count_events(["SDR wedged, exiting!", "FATAL: no device matching '123' found", "rtlsdr_demod_write_reg failed with -1", "USB reset OK: 123", "retry budget exhausted"])
        for key in ("sdr_wedged","device_not_found","usb_io_errors","usb_reset_ok","recovery_exhausted"):
            self.assertEqual(counts[key],1)

    def test_idle_is_not_failure_and_missing_checks_are_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(health,"observe_service",return_value={"state":"inactive","status":"idle"}), patch.object(health,"usb_observation",return_value={"status":"ok","receivers":[]}), patch.object(health,"resources",return_value={"available_ram_gib":9,"disk_free_gib":10,"load_1m_per_cpu":.2,"cpu_temperature_c":None}), patch.object(health.local_ai_reception,"read_evidence",return_value={"status":"ok","latest_sample_stale":False}), patch.object(health,"service_events",return_value={"status":"unavailable"}), patch.object(health,"station_events",return_value={"status":"no_visible_entries"}):
                data=health.snapshot(root,now=1770000000)
            self.assertEqual(data["status"],"partial")
            self.assertEqual(data["findings"],[])
            self.assertEqual(data["services"]["AIS"]["reception"]["status"],"idle")
            self.assertEqual(list(root.iterdir()),[])

    def test_recent_station_log_only_and_bounded(self):
        from datetime import datetime
        now=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            log=root/"logs/sdrcc.log"
            log.parent.mkdir()
            log.write_text(f"[{datetime.fromtimestamp(now-7200):%Y-%m-%d %H:%M:%S}] SDR wedged\n[{datetime.fromtimestamp(now-10):%Y-%m-%d %H:%M:%S}] USB reset OK: 123\n")
            before=log.read_bytes()
            events=health.station_events(root,now)
            self.assertEqual(events["counts"]["sdr_wedged"],0)
            self.assertEqual(events["counts"]["usb_reset_ok"],1)
            self.assertEqual(log.read_bytes(),before)


class MaritimeTests(unittest.TestCase):
    def row(self,mmsi,**kwargs):
        return dict({"mmsi":mmsi,"lat":51.9,"lon":4.31,"validated":1,"last_signal":20,"speed":5,"shiptype":70,"shipname":"CARGO"},**kwargs)

    def test_radius_freshness_identity_fixed_targets_and_zero(self):
        home={"configured":True,"latitude":51.9,"longitude":4.3}
        rows=[self.row("123456781"),self.row("123456781",last_signal=90),
              self.row("123456782",last_signal=301), self.row("123456783",validated=0),
              self.row("123456784",lat=53), self.row("123456785",shipclass=12),
              self.row("123456786",speed=0,shiptype=52,shipname="TUG"),
              self.row("123456787",shiptype=55,shipname="POLICE")]
        data=maritime.summarize({"ships":rows},home,10)
        self.assertEqual(data["status"],"ok")
        self.assertEqual(data["validated_targets"],3)
        self.assertEqual(data["moving"],2)
        self.assertEqual(data["stationary_or_slow"],1)
        self.assertEqual(data["by_profile"]["tug"],1)
        self.assertNotIn("POLICE",[r["name"] for r in data["nearest_examples"]])
        self.assertEqual(maritime.summarize({"ships":[]},home,10)["validated_targets"],0)
        self.assertEqual(maritime.summarize(None,home,10)["status"],"unavailable")
        self.assertEqual(maritime.summarize({"ships":[]},{},10)["status"],"unavailable")

    def test_atis_read_only_legacy_missing_disabled(self):
        now=1770000000
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(maritime.features,"feature_enabled",return_value=True):
                self.assertEqual(maritime.atis_history(root,now)["status"],"unavailable")
                self.assertEqual(list(root.iterdir()),[])
                path=root/"data/analytics/atis_statistics.sqlite3"
                path.parent.mkdir(parents=True)
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE atis_events(ts REAL,decoded INTEGER)")
                    db.executemany("INSERT INTO atis_events VALUES(?,?)",[(now-20,1),(now-10,0),(now-90000,1),(now+1,1)])
                before=path.read_bytes()
                data=maritime.atis_history(root,now)
                self.assertEqual(data["candidates"],2)
                self.assertEqual(data["decoded"],1)
                self.assertIsNone(data["ais_matched"])
                self.assertEqual(path.read_bytes(),before)
            with patch.object(maritime.features,"feature_enabled",return_value=False):
                self.assertEqual(maritime.atis_history(root,now)["status"],"disabled")

    def test_stopped_ais_does_not_read_feed(self):
        with patch.object(health,"observe_service",return_value={"state":"inactive"}), patch("core.receiver_monitor._read_ais_ships") as feed, patch.object(maritime,"atis_history",return_value={"status":"unavailable"}):
            data=maritime.snapshot(Path("/unused"),25,now=1770000000)
            self.assertEqual(data["ais"]["status"],"inactive")
            feed.assert_not_called()
