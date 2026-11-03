"""Regression coverage for SDRCC emergency presence and MQTT cleanup."""
import json
import unittest
from unittest.mock import Mock, patch

from core import emergency_monitor as em


class EmergencyPresenceTests(unittest.TestCase):
    def setUp(self):
        self.old = (dict(em._active_targets), set(em._announced), dict(em._presence),
                    dict(em._recent), em._mqtt_client, em._mqtt_ha_active)
        em._active_targets.clear()
        em._announced.clear()
        em._presence.clear()
        em._recent.clear()
        self.client = Mock()
        self.client.publish.return_value.rc = 0
        em._mqtt_client, em._mqtt_ha_active = self.client, True
        self.config = em.validate({"enabled": True, "radius_km": 20,
                                   "ha_notifications": True})
        self.events = []

    def tearDown(self):
        active, announced, presence, recent, client, ha = self.old
        em._active_targets.clear()
        em._active_targets.update(active)
        em._announced.clear()
        em._announced.update(announced)
        em._presence.clear()
        em._presence.update(presence)
        em._recent.clear()
        em._recent.update(recent)
        em._mqtt_client, em._mqtt_ha_active = client, ha

    def detect(self, source, category, identity, now, distance=5, speed=40):
        with patch.object(em.time, "time", return_value=now), patch.object(
                em, "_store_event", side_effect=self.events.append):
            em._target_event(source, category, identity, category, distance,
                             self.config, ground_speed_knots=speed)

    def expire(self, now):
        with patch.object(em, "_save_active_targets"):
            em._expire_targets(self.config, now=now)

    def clears(self):
        return [json.loads(call.args[1]) for call in self.client.publish.call_args_list
                if call.args[0] == "sdrcc/emergency/cleared"]

    def test_lifeliner_expires_at_90_seconds_only_once(self):
        self.detect("adsb", "lifeliner", "ABC123", 1000)
        self.detect("adsb", "lifeliner", "ABC123", 1005)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["notification_id"], "sdrcc_adsb_abc123")
        self.expire(1094)
        self.assertEqual(self.clears(), [])
        self.expire(1095)
        self.assertEqual(len(self.clears()), 1)
        self.assertEqual(self.clears()[0]["kind"], "no_longer_observed")
        self.assertEqual(self.clears()[0]["reason"], "position_stale")
        self.assertEqual(self.clears()[0]["notification_id"],
                         self.events[0]["notification_id"])
        self.expire(2000)
        self.assertEqual(len(self.clears()), 1)

    def test_fresh_position_renews_presence_without_reminder(self):
        self.detect("adsb", "lifeliner", "ABC123", 1000)
        self.detect("adsb", "lifeliner", "ABC123", 1005)
        self.detect("adsb", "lifeliner", "ABC123", 1080, speed=0)
        self.assertEqual(len(self.events), 1)
        self.expire(1169)
        self.assertEqual(self.clears(), [])
        self.expire(1170)
        self.assertEqual(len(self.clears()), 1)

    def test_ais_has_180_second_timeout(self):
        self.detect("ais", "knrm", "244123456", 1000, speed=4)
        self.detect("ais", "knrm", "244123456", 1005, speed=4)
        self.expire(1095)
        self.assertEqual(self.clears(), [])
        self.expire(1185)
        self.assertEqual(len(self.clears()), 1)
        self.assertEqual(self.clears()[0]["notification_id"], "sdrcc_ais_244123456")

    def test_beyond_radius_clears_immediately(self):
        self.detect("adsb", "police_helicopter", "DEF456", 1000)
        self.detect("adsb", "police_helicopter", "DEF456", 1005)
        with patch.object(em, "_save_active_targets"):
            self.detect("adsb", "police_helicopter", "DEF456", 1010, distance=23)
        self.assertEqual(len(self.clears()), 1)
        self.assertEqual(self.clears()[0]["reason"], "out_of_range")
        self.assertNotIn("adsb:DEF456", em._active_targets)

    def test_only_announced_targets_can_be_cleared(self):
        self.detect("adsb", "lifeliner", "ABC123", 1000)
        self.expire(2000)
        self.assertEqual(self.clears(), [])

    def test_disabling_category_clears_existing_target(self):
        self.detect("ais", "waterpolitie", "244987654", 1000, speed=4)
        self.detect("ais", "waterpolitie", "244987654", 1005, speed=4)
        self.config["categories"]["waterpolitie"] = False
        self.expire(1006)
        self.assertEqual(self.clears()[0]["reason"], "category_disabled")


if __name__ == "__main__":
    unittest.main()
