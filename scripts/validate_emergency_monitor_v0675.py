#!/usr/bin/env python3
"""Offline regression tests for SDRCC Emergency Monitor v0.67.8.

Read-only: never starts a receiver, opens MQTT or modifies local config.
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import emergency_monitor as monitor


def must_reject(payload):
    try:
        monitor.validate(payload)
    except ValueError:
        return
    raise AssertionError("Emergency Monitor accepted invalid settings: " + str(payload))


def check():
    assert math.isclose(monitor.distance_km(51.9, 4.35, 51.9, 4.35), 0.0)
    assert 110 < monitor.distance_km(51.9, 4.35, 52.9, 4.35) < 112
    assert 15 < monitor.distance_km(51.908401, 4.351168, 51.908401, 4.60) < 20

    cfg = monitor.validate({"enabled": True, "radius_km": 20})
    assert cfg["enabled"] is True
    assert cfg["radius_km"] == 20
    assert all(radius is None for radius in cfg["category_radius_km"].values())
    assert monitor.radius_for_category(cfg, "lifeliner") == 20
    custom = monitor.validate({"radius_km": 30, "category_radius_km": {
        "lifeliner": 10, "police_helicopter": 20, "knrm": 15, "waterpolitie": 25
    }})
    assert [monitor.radius_for_category(custom, name) for name in
            ("lifeliner", "police_helicopter", "knrm", "waterpolitie")] == [10, 20, 15, 25]
    unset = monitor.validate({"category_radius_km": {"lifeliner": None}})
    assert monitor.radius_for_category(unset, "lifeliner") == unset["radius_km"]
    legacy = {"radius_km": 35}
    assert monitor.radius_for_category(legacy, "knrm") == 35
    assert set(cfg["categories"]) == {"lifeliner", "police_helicopter", "knrm", "waterpolitie"}
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": "LIFELN2"}, cfg) == "lifeliner"
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": "UNKNOWN"}, cfg) is None
    cfg["aircraft_hex"]["police_helicopter"] = ["ABC123"]
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": ""}, cfg) == "police_helicopter"
    cfg["vessel_mmsi"]["knrm"] = ["244123456"]
    assert monitor.classify_vessel({"mmsi": "244123456"}, cfg) == "knrm"
    assert monitor.classify_vessel({"mmsi": "244123457"}, cfg) is None

    for invalid in (0, 101, float("inf"), "20"):
        must_reject({"radius_km": invalid})
    must_reject({"categories": {"p2000": True}})
    must_reject({"motion_only": "yes"})
    must_reject({"motion_only": 1})
    for bad in (0, 101, 1.5, -1, True, "10", float("inf")):
        must_reject({"category_radius_km": {"lifeliner": bad}})
    must_reject({"category_radius_km": {"unknown": 20}})
    must_reject({"category_radius_km": []})
    assert monitor.validate({"motion_only": True})["motion_only"] is True
    assert monitor._DEFAULT["motion_only"] is False
    assert monitor._DEFAULT["enabled"] is False
    assert monitor._DEFAULT["ha_notifications"] is False
    assert "p2000_input" not in monitor._DEFAULT
    assert "p2000" not in monitor._DEFAULT["categories"]
    assert "mqtt_password" not in monitor.public_settings()
    # Simulate settings left by the withdrawn beta, without writing local files.
    original_reader = monitor._read_json
    try:
        def legacy_reader(path):
            if path == monitor.SETTINGS_FILE:
                return {"enabled": True, "p2000_input": True,
                        "categories": {"p2000": True, "lifeliner": True}}
            return original_reader(path)
        monitor._read_json = legacy_reader
        migrated = monitor.settings()
        assert "p2000_input" not in migrated
        assert "p2000" not in migrated["categories"]
    finally:
        monitor._read_json = original_reader


    # Motion-only filtering never claims that an unknown or stationary target
    # is moving. Moving AIS and ADS-B targets repeat every five minutes only
    # while fresh and within the configured detection range.
    assert monitor.speed_knots("adsb", {"gs": 35}) == 35
    assert monitor.speed_knots("adsb", {"gs": None}) is None
    assert monitor.speed_knots("ais", {"speed": 2.3}) == 2.3
    assert monitor.speed_knots("ais", {"sog": 2.3}) == 2.3
    assert monitor.speed_knots("ais", {"sog": 102.3}) is None
    assert monitor.speed_knots("ais", {"sog": -1}) is None
    assert monitor.moving_enough("ais", 2.0)
    assert not monitor.moving_enough("ais", 1.9)
    assert monitor.moving_enough("adsb", 30.0)
    assert not monitor.moving_enough("adsb", 29.9)
    assert not monitor.moving_enough("ais", None)
    assert not monitor.moving_enough("adsb", None)
    captured = []
    old_writer = monitor._store_event
    old_presence = dict(monitor._presence)
    old_announced = set(monitor._announced)
    old_recent = dict(monitor._recent)
    try:
        monitor._store_event = captured.append
        monitor._presence.clear()
        monitor._announced.clear()
        monitor._recent.clear()
        motion_config = monitor.validate({"motion_only": True, "radius_km": 20})
        for speed in (None, 0.0, 1.8, None):
            monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                                  ground_speed_knots=speed)
        assert not captured, "Stationary/unknown speed created a false alarm"
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=2.0)
        assert not captured, "First qualifying sample cannot alert"
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=2.5)
        assert len(captured) == 1 and captured[0]["speed_knots"] == 2.5
        assert captured[0]["kind"] == "nearby_detected" and not captured[0].get("repeat")
        for _ in range(15):
            monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                                  ground_speed_knots=4.0)
        assert len(captured) == 1, "AIS must not repeat before five minutes"
        key = "ais:244123456"
        monitor._recent[key] -= monitor.AIS_REPEAT_SECONDS - 1
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=4.0)
        assert len(captured) == 1, "AIS reminder was sent a second early"
        monitor._recent[key] -= 2
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=4.0)
        assert len(captured) == 2 and captured[-1].get("repeat") is True
        assert captured[-1]["kind"] == captured[0]["kind"], "Existing MQTT automation kind changed"
        # Stopped / unknown speed must not repeat, even after cooldown.
        monitor._recent[key] -= monitor.AIS_REPEAT_SECONDS + 1
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=0.0)
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=None)
        assert len(captured) == 2, "Stationary vessel repeated"
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=4.0)
        assert len(captured) == 2, "After stopping, require two moving samples"
        monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                              ground_speed_knots=4.0)
        assert len(captured) == 3 and captured[-1].get("repeat") is True
        monitor._recent[key] -= monitor.AIS_REPEAT_SECONDS + 1
        monitor._target_event("ais", "knrm", "244123456", "Test", 21, motion_config,
                              ground_speed_knots=5.0)
        assert len(captured) == 3, "Out-of-range vessel repeated"
        monitor._target_event("ais", "knrm", "244123456", "Test", 23, motion_config,
                              ground_speed_knots=5.0)
        assert key not in monitor._announced
        # Without motion-only, initial stationary detections are still allowed,
        # but reminders are only for moving AIS vessels.
        monitor._presence.clear()
        monitor._announced.clear()
        monitor._recent.clear()
        captured.clear()
        normal = monitor.validate({"motion_only": False, "radius_km": 20})
        for _ in range(2):
            monitor._target_event("ais", "waterpolitie", "244987654", "Harbour police", 5, normal,
                                  ground_speed_knots=0.0)
        assert len(captured) == 1 and not captured[-1].get("repeat")
        monitor._recent["ais:244987654"] -= monitor.AIS_REPEAT_SECONDS + 1
        monitor._target_event("ais", "waterpolitie", "244987654", "Harbour police", 5, normal,
                              ground_speed_knots=0.0)
        assert len(captured) == 1, "Stationary AIS re-notified with motion-only disabled"
        monitor._target_event("ais", "waterpolitie", "244987654", "Harbour police", 5, normal,
                              ground_speed_knots=2.2)
        assert len(captured) == 2 and captured[-1].get("repeat") is True
        # ADS-B: both Lifeliners and police helicopters use five-minute reminders.
        for category, hex_id in (("lifeliner", "ABC123"), ("police_helicopter", "DEF456")):
            monitor._presence.clear()
            monitor._announced.clear()
            monitor._recent.clear()
            captured.clear()
            key = "adsb:" + hex_id

            def aircraft(speed, distance=5):
                monitor._target_event("adsb", category, hex_id, category, distance, normal,
                                      ground_speed_knots=speed)

            # Existing initial detection works even when motion_only is off.
            aircraft(0.0)
            aircraft(0.0)
            assert len(captured) == 1 and not captured[0].get("repeat"), category
            assert captured[0]["kind"] == "nearby_detected"
            monitor._recent[key] -= monitor.ADSB_REPEAT_SECONDS - 1
            aircraft(50.0)
            assert len(captured) == 1, "Early aircraft reminder: " + category
            monitor._recent[key] -= 2
            aircraft(29.9)
            aircraft(None)
            assert len(captured) == 1, "Stationary/unknown aircraft repeated: " + category
            aircraft(30.0)
            assert len(captured) == 2 and captured[-1].get("repeat") is True, category
            assert captured[-1]["kind"] == captured[0]["kind"], "MQTT event kind changed"

            monitor._recent[key] -= monitor.ADSB_REPEAT_SECONDS + 1
            aircraft(60.0, distance=21)
            assert len(captured) == 2, "Out-of-range aircraft repeated: " + category
            aircraft(60.0, distance=23)
            assert key not in monitor._announced, "Departed aircraft session not reset"

            # motion_only must still suppress first alerts when aircraft are parked.
            monitor._presence.clear()
            monitor._announced.clear()
            monitor._recent.clear()
            captured.clear()

            def moving_aircraft(speed):
                monitor._target_event("adsb", category, hex_id, category, 5, motion_config,
                                      ground_speed_knots=speed)

            moving_aircraft(0.0)
            moving_aircraft(None)
            moving_aircraft(29.9)
            assert not captured, "Parked aircraft alerted with motion_only on"
            moving_aircraft(30.0)
            assert not captured, "First moving sample cannot alert"
            moving_aircraft(35.0)
            assert len(captured) == 1 and not captured[-1].get("repeat"), category
            monitor._recent[key] -= monitor.ADSB_REPEAT_SECONDS + 1
            moving_aircraft(0.0)
            moving_aircraft(None)
            assert len(captured) == 1, "Stopped aircraft reminder occurred"
            moving_aircraft(40.0)
            assert len(captured) == 1, "Requires two new moving samples"
            moving_aircraft(40.0)
            assert len(captured) == 2 and captured[-1].get("repeat") is True

        # All four category ranges affect first alert, MQTT radius and reminders.
        category_limits = {
            "lifeliner": ("adsb", "ABC123", 10, 40.0),
            "police_helicopter": ("adsb", "DEF456", 20, 40.0),
            "knrm": ("ais", "244123456", 15, 4.0),
            "waterpolitie": ("ais", "244987654", 25, 4.0),
        }
        for name, (source, identity, limit, speed) in category_limits.items():
            monitor._presence.clear()
            monitor._announced.clear()
            monitor._recent.clear()
            captured.clear()
            settings = monitor.validate({"radius_km": 50, "category_radius_km": {
                category: values[2] for category, values in category_limits.items()
            }})
            for _ in range(2):
                monitor._target_event(source, name, identity, name, limit + 0.1,
                                      settings, ground_speed_knots=speed)
            assert captured == [], "Outside individual category radius: " + name
            for _ in range(2):
                monitor._target_event(source, name, identity, name, limit - 0.1,
                                      settings, ground_speed_knots=speed)
            assert len(captured) == 1, "First category-specific detection: " + name
            assert captured[0]["radius_km"] == limit, name
            assert "within " + str(limit) + " km" in captured[0]["detail"], name
            key = source + ":" + identity
            monitor._recent[key] -= 301
            monitor._target_event(source, name, identity, name, limit + 0.1,
                                  settings, ground_speed_knots=speed)
            assert len(captured) == 1, "Out-of-range category reminder: " + name
            monitor._target_event(source, name, identity, name, limit - 0.1,
                                  settings, ground_speed_knots=speed)
            assert len(captured) == 2 and captured[-1].get("repeat") is True, name
    finally:
        monitor._store_event = old_writer
        monitor._presence.clear()
        monitor._presence.update(old_presence)
        monitor._announced.clear()
        monitor._announced.update(old_announced)
        monitor._recent.clear()
        monitor._recent.update(old_recent)

    # Map overlays use real AIS positions, configured identifiers and
    # reported movement only. The tests replace read paths without network use.
    from core import receiver_monitor as ais_reader
    from core import config as station_configuration
    old_settings = monitor.settings
    old_ais_reader = ais_reader._read_ais_ships
    old_station = station_configuration.get_home_position
    prior_rings = dict(monitor._map_recent)
    try:
        cfg = monitor.validate({"enabled": True, "radius_km": 50})
        cfg["categories"]["knrm"] = True
        cfg["categories"]["waterpolitie"] = True
        cfg["vessel_mmsi"]["knrm"] = ["244123456"]
        cfg["vessel_mmsi"]["waterpolitie"] = ["244987654"]
        station_configuration.get_home_position = lambda: {
            "latitude": 51.908, "longitude": 4.351
        }
        monitor.settings = lambda: cfg
        moving = {"mmsi": 244123456, "validated": 1, "lat": 51.910,
                  "lon": 4.360, "last_signal": 3, "speed": 6.0}
        stationary = {"mmsi": 244987654, "validated": 1, "lat": 51.911,
                      "lon": 4.362, "last_signal": 3, "speed": 0.0}
        ais_reader._read_ais_ships = lambda: ({"ships": [moving, stationary]}, "test")
        monitor._map_recent.clear()
        first = monitor.map_highlights()
        assert len(first["vessels"]) == 1
        assert first["vessels"][0]["category"] == "knrm"
        assert first["vessels"][0]["mmsi"] == "244123456"
        assert first["linger_seconds"] == 300
        ais_reader._read_ais_ships = lambda: ({"ships": []}, "test")
        assert len(monitor.map_highlights()["vessels"]) == 1, "Five-minute linger missing"
        monitor._map_recent["244123456"]["last_moving"] -= 301
        assert monitor.map_highlights()["vessels"] == [], "Expired ring still present"
        moving_far = {**moving, "lon": 4.39}  # Several km from station.
        cfg["category_radius_km"]["knrm"] = 2
        ais_reader._read_ais_ships = lambda: ({"ships": [moving_far]}, "test")
        assert monitor.map_highlights()["vessels"] == [], "Map ignored narrow category radius"
        cfg["category_radius_km"]["knrm"] = 5
        assert len(monitor.map_highlights()["vessels"]) == 1, "Map ignored wider category radius"
        cfg["category_radius_km"]["knrm"] = 2
        ais_reader._read_ais_ships = lambda: ({"ships": []}, "test")
        assert monitor.map_highlights()["vessels"] == [], "Reduced category radius left stale ring"
        cfg["enabled"] = False
        assert monitor.map_highlights()["vessels"] == [], "Disabled monitor drew an AIS ring"
    finally:
        monitor.settings = old_settings
        ais_reader._read_ais_ships = old_ais_reader
        station_configuration.get_home_position = old_station
        monitor._map_recent.clear()
        monitor._map_recent.update(prior_rings)

    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    begin = html.index('<details class="card system-maintenance-card-v0540f"')
    panel = html.index('id="em-monitor"')
    end = html.index("</details>", begin)
    assert begin < panel < end, "Emergency Monitor must be INSIDE Advanced Maintenance"
    assert '<button class="tab-button" data-tab="em-monitor">' not in html
    assert "em-cat-p2000" not in html and "em-p2000-input" not in html
    assert "static/js/emergency_monitor.js?v=" in html
    assert "static/css/emergency_monitor.css?v=" in html
    assert "static/js/radio_view.js?v=" in html
    assert 'id="em-motion-only"' in html
    for category in ("lifeliner", "police_helicopter", "knrm", "waterpolitie"):
        assert 'id="em-range-' + category + '"' in html

    js = (ROOT / "dashboard/static/js/emergency_monitor.js").read_text(encoding="utf-8")
    assert "em-p2000-input" not in js and "em-cat-p2000" not in js
    assert 'motion_only: $("em-motion-only").checked' in js
    assert '["lifeliner", "police_helicopter", "knrm", "waterpolitie"]' in js
    assert "category_radius_km: Object.fromEntries" in js
    backend = (ROOT / "core/emergency_monitor.py").read_text(encoding="utf-8")
    assert "p2000_input" not in backend
    assert 'client.subscribe(' not in backend
    assert "homeassistant/sensor/p2000_rtlsdr" not in backend
    assert 'sdrcc/emergency/events' in backend
    assert 'ground_speed_knots=speed_knots("adsb", item)' in backend
    assert 'ground_speed_knots=speed_knots("ais", item)' in backend
    css = (ROOT / "dashboard/static/css/emergency_monitor.css").read_text(encoding="utf-8")
    assert "#tab-system .system-maintenance-body-v0540f > #em-monitor" in css
    assert "grid-column: 1 / -1" in css
    ais_plugin = (ROOT / "dashboard/static/mobile/atis-highlight.pjs").read_text(encoding="utf-8")
    desktop = (ROOT / "dashboard/static/js/radio_view.js").read_text(encoding="utf-8")
    mobile = (ROOT / "dashboard/static/mobile/index.html").read_text(encoding="utf-8")
    backend_app = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    assert 'SDRCC Emergency Vessels' in ais_plugin
    assert 'target.category === "knrm" ? "255,255,255" : "36,153,255"' in ais_plugin
    assert "sdrcc:emergency-highlight:sync" in ais_plugin
    assert 'if (window.parent === window)' in ais_plugin
    assert 'fetch(trustedOrigin + "/api/emergency-monitor/map-highlights"' in ais_plugin
    assert 'window.parent !== window)' not in ais_plugin
    assert "sdrcc:emergency-highlight:sync" in desktop
    assert "sdrcc:emergency-highlight:sync" in mobile
    assert '"/api/emergency-monitor/map-highlights"' in backend_app
    assert 'Access-Control-Allow-Origin' in backend_app
    assert 'request.host.rsplit' in backend_app
    assert "def map_highlights()" in backend

    assert 'event_bus.purge_legacy_emergency_p2000_events()' in backend
    print("PASS: Emergency Monitor — category ranges, moving AIS/ADS-B reminders, radius-limited map and no P2000")


if __name__ == "__main__":
    check()
