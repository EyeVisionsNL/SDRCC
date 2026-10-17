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


    # Motion-only filtering must never claim that an unknown or stationary
    # target is moving, and no repeated alerts for the same in-range target.
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
        for _ in range(15):
            monitor._target_event("ais", "knrm", "244123456", "Test", 7, motion_config,
                                  ground_speed_knots=4.0)
        assert len(captured) == 1, "One in-range session must alert only once"
        monitor._target_event("ais", "knrm", "244123456", "Test", 23, motion_config,
                              ground_speed_knots=4.0)
        assert "ais:244123456" not in monitor._announced
        # With the switch off, stationary reports still work (old behavior).
        monitor._presence.clear()
        monitor._announced.clear()
        monitor._recent.clear()
        normal = monitor.validate({"motion_only": False, "radius_km": 20})
        monitor._target_event("adsb", "lifeliner", "ABC123", "Lifeliner", 5, normal,
                              ground_speed_knots=0.0)
        monitor._target_event("adsb", "lifeliner", "ABC123", "Lifeliner", 5, normal,
                              ground_speed_knots=0.0)
        assert len(captured) == 2
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
    assert "static/js/emergency_monitor.js?v=0.67.8" in html
    assert "static/css/emergency_monitor.css?v=0.67.7" in html
    assert "static/js/radio_view.js?v=0.67.8" in html
    assert 'id="em-motion-only"' in html

    js = (ROOT / "dashboard/static/js/emergency_monitor.js").read_text(encoding="utf-8")
    assert "em-p2000-input" not in js and "em-cat-p2000" not in js
    assert 'motion_only: $("em-motion-only").checked' in js
    assert '["lifeliner", "police_helicopter", "knrm", "waterpolitie"]' in js
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
    assert "sdrcc:emergency-highlight:sync" in desktop
    assert "sdrcc:emergency-highlight:sync" in mobile
    assert '"/api/emergency-monitor/map-highlights"' in backend_app
    assert "def map_highlights()" in backend

    assert 'event_bus.purge_legacy_emergency_p2000_events()' in backend
    print("PASS: v0.67.8 Emergency Monitor — moving AIS overlays, motion filters and no P2000")


if __name__ == "__main__":
    check()
