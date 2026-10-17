#!/usr/bin/env python3
"""Offline regression checks for Emergency Monitor v0.67.5; never starts SDRs/MQTT."""
from __future__ import annotations
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import emergency_monitor as monitor


def check() -> None:
    assert math.isclose(monitor.distance_km(51.9, 4.35, 51.9, 4.35), 0.0)
    assert 110 < monitor.distance_km(51.9, 4.35, 52.9, 4.35) < 112
    assert 15 < monitor.distance_km(51.908401, 4.351168, 51.908401, 4.60) < 20
    config = monitor.validate({"enabled": True, "radius_km": 20})
    assert config["radius_km"] == 20
    assert config["enabled"] is True
    assert set(config["categories"]) == {"lifeliner", "police_helicopter", "knrm", "waterpolitie", "p2000"}
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": "LIFELN2"}, config) == "lifeliner"
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": "UNKNOWN"}, config) is None
    config["aircraft_hex"]["police_helicopter"] = ["ABC123"]
    assert monitor.classify_aircraft({"hex": "ABC123", "flight": ""}, config) == "police_helicopter"
    config["vessel_mmsi"]["knrm"] = ["244123456"]
    assert monitor.classify_vessel({"mmsi": "244123456"}, config) == "knrm"
    assert monitor.classify_vessel({"mmsi": "244123457"}, config) is None
    for invalid in (0, 101, float("inf"), "20"):
        try:
            monitor.validate({"radius_km": invalid})
        except ValueError:
            continue
        raise AssertionError(f"Invalid radius was accepted: {invalid}")
    assert "mqtt_password" not in monitor.public_settings()
    assert monitor._DEFAULT["enabled"] is False
    assert monitor._DEFAULT["p2000_input"] is False
    assert monitor._DEFAULT["ha_notifications"] is False
    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    first = html.index('<details class="card system-maintenance-card-v0540f"')
    panel = html.index('id="em-monitor"')
    end = html.index("</details>", first)
    assert first < panel < end, "Emergency Monitor must be INSIDE Advanced Maintenance"
    assert '<button class="tab-button" data-tab="em-monitor">' not in html
    assert "static/js/emergency_monitor.js?v=0.67.5" in html
    assert "static/css/emergency_monitor.css?v=0.67.5" in html
    print("PASS: Emergency Monitor 0.67.5 offline checks (no receiver or MQTT used)")


if __name__ == "__main__":
    check()
