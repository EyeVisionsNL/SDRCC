"""Regression: changing the alert radius must not show ADS-B/AIS as OFF."""
from copy import deepcopy
import threading
import unittest
from unittest.mock import patch

from core import emergency_monitor as em


class EmergencyMonitorStatusTests(unittest.TestCase):
    def setUp(self):
        self.old = deepcopy(em._DEFAULT)
        self.old.update({"enabled": True, "radius_km": 20, "ha_notifications": True,
                         "mqtt_host": "127.0.0.1"})
        self.old_worker, self.old_stop = em._worker, em._stop
        self.old_runtime = dict(em._runtime)
        self.old_mqtt = em._mqtt_client

    def tearDown(self):
        em._worker, em._stop = self.old_worker, self.old_stop
        em._runtime.clear()
        em._runtime.update(self.old_runtime)
        em._mqtt_client = self.old_mqtt

    def test_radius_save_does_not_restart_monitor(self):
        edited = deepcopy(self.old)
        edited["radius_km"] = 50
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "validate", return_value=edited), \
             patch.object(em, "_atomic"), \
             patch.object(em, "sync_worker") as sync, \
             patch.object(em, "public_settings", return_value=edited):
            result = em.save({"radius_km": 50})
        self.assertEqual(result["radius_km"], 50)
        sync.assert_called_once_with(restart=False)

    def test_category_radius_save_does_not_restart_monitor(self):
        edited = deepcopy(self.old)
        edited["category_radius_km"]["lifeliner"] = 10
        edited["category_radius_km"]["knrm"] = 15
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "validate", return_value=edited), \
             patch.object(em, "_atomic"), \
             patch.object(em, "sync_worker") as sync, \
             patch.object(em, "public_settings", return_value=edited):
            result = em.save({"category_radius_km": {"lifeliner": 10, "knrm": 15}})
        self.assertEqual(result["category_radius_km"]["lifeliner"], 10)
        sync.assert_called_once_with(restart=False)

    def test_mqtt_change_still_restarts_connection(self):
        edited = deepcopy(self.old)
        edited["mqtt_host"] = "192.0.2.10"
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "validate", return_value=edited), \
             patch.object(em, "_atomic"), \
             patch.object(em, "sync_worker") as sync, \
             patch.object(em, "public_settings", return_value=edited):
            em.save({"mqtt_host": "192.0.2.10"})
        sync.assert_called_once_with(restart=True)

    def test_disable_still_stops_worker(self):
        edited = deepcopy(self.old)
        edited["enabled"] = False
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "validate", return_value=edited), \
             patch.object(em, "_atomic"), \
             patch.object(em, "sync_worker") as sync, \
             patch.object(em, "public_settings", return_value=edited):
            em.save({"enabled": False})
        sync.assert_called_once_with(restart=True)

    def test_live_worker_keeps_source_statuses(self):
        worker = unittest.mock.Mock()
        worker.is_alive.return_value = True
        stop = threading.Event()
        em._worker, em._stop = worker, stop
        em._runtime.update({"adsb": "LIVE", "ais": "LIVE", "mqtt": "CONNECTED"})
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "_purge_legacy_p2000_history"), \
             patch.object(em.event_bus, "purge_legacy_emergency_p2000_events"):
            em.sync_worker(restart=False)
        self.assertFalse(stop.is_set())
        worker.join.assert_not_called()
        self.assertEqual(em._runtime["adsb"], "LIVE")
        self.assertEqual(em._runtime["ais"], "LIVE")
        self.assertEqual(em._runtime["mqtt"], "CONNECTED")

    def test_worker_reloads_radius_before_poll(self):
        changed = deepcopy(self.old)
        changed["radius_km"] = 75

        class FakeCancel:
            stopped = False
            def wait(self, seconds):
                return self.stopped
            def is_set(self):
                return self.stopped

        cancel = FakeCancel()
        observed = []

        def poll(data):
            observed.append(data["radius_km"])
            cancel.stopped = True

        with patch.object(em, "settings", side_effect=[self.old, changed]), \
             patch.object(em, "_load_history", return_value={"last_sent": {}, "history": []}), \
             patch.object(em, "_purge_legacy_p2000_history"), \
             patch.object(em, "_start_mqtt"), \
             patch.object(em, "_close_mqtt"), \
             patch.object(em, "_poll_positions", side_effect=poll):
            em._loop(cancel)
        self.assertEqual(observed, [75])

    def test_new_worker_shows_checking_during_warmup(self):
        stop = threading.Event()
        em._worker, em._stop = None, None
        em._runtime.update({"adsb": "OFF", "ais": "OFF"})
        with patch.object(em, "settings", return_value=self.old), \
             patch.object(em, "_purge_legacy_p2000_history"), \
             patch.object(em.event_bus, "purge_legacy_emergency_p2000_events"), \
             patch.object(em.threading, "Event", return_value=stop), \
             patch.object(em.threading, "Thread") as thread_type:
            em.sync_worker(restart=True)
            thread_type.return_value.start.assert_called_once()
        self.assertEqual(em._runtime["adsb"], "CHECKING")
        self.assertEqual(em._runtime["ais"], "CHECKING")


if __name__ == "__main__":
    unittest.main()
