#!/usr/bin/env python3
"""Offline regression tests for SDRCC Emergency Monitor v0.67.6.

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

    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    begin = html.index('<details class="card system-maintenance-card-v0540f"')
    panel = html.index('id="em-monitor"')
    end = html.index("</details>", begin)
    assert begin < panel < end, "Emergency Monitor must be INSIDE Advanced Maintenance"
    assert '<button class="tab-button" data-tab="em-monitor">' not in html
    assert "em-cat-p2000" not in html and "em-p2000-input" not in html
    assert "static/js/emergency_monitor.js?v=0.67.6" in html
    assert "static/css/emergency_monitor.css?v=0.67.6" in html

    js = (ROOT / "dashboard/static/js/emergency_monitor.js").read_text(encoding="utf-8")
    assert "em-p2000-input" not in js and "em-cat-p2000" not in js
    assert '["lifeliner", "police_helicopter", "knrm", "waterpolitie"]' in js
    backend = (ROOT / "core/emergency_monitor.py").read_text(encoding="utf-8")
    assert "p2000_input" not in backend
    assert 'client.subscribe(' not in backend
    assert "homeassistant/sensor/p2000_rtlsdr" not in backend
    assert 'sdrcc/emergency/events' in backend
    assert 'event_bus.purge_legacy_emergency_p2000_events()' in backend
    print("PASS: v0.67.6 Emergency Monitor — HA owns P2000, SDRCC reads ADS-B/AIS only")


if __name__ == "__main__":
    check()
