#!/usr/bin/env python3
"""Deterministic contract checks for SDRCC v0.54.0f System Status Clarity."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    html = read("dashboard/templates/index.html")
    system_css = read("dashboard/static/css/system.css")
    inventory_css = read("dashboard/static/css/receiver_inventory.css")
    dashboard_loader = read("dashboard/static/dashboard.js")
    dashboard_js = read("dashboard/static/js/dashboard.js")
    system_js = read("dashboard/static/js/system.js")
    services_js = read("dashboard/static/js/services.js")
    inventory_js = read("dashboard/static/js/receiver_inventory.js")
    sounds_js = read("dashboard/static/js/mission_sounds.js")

    parser = IdCollector()
    parser.feed(html)
    duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
    check(not duplicates, "System redesign introduces no duplicate element IDs")

    system_start = html.index('<section class="tab-page" id="tab-system">')
    radio_start = html.index('<section class="tab-page" id="tab-radio">')
    system_html = html[system_start:radio_start]

    required_sections = (
        "System Health",
        "Receiver Inventory",
        "Service Control",
        "Advanced Maintenance",
    )
    check(all(label in system_html for label in required_sections), "four approved System sections are present")
    check("System and Mission Events" not in system_html, "obsolete System and Mission Events card is removed")
    check("Mission Event Center" not in system_html, "large Mission Event Center card is removed")
    check(">🛠 Mission Tools<" not in system_html, "Mission Tools is no longer a primary card")
    check("TLE" not in system_html, "TLE management remains outside the System tab")

    details_marker = '<details class="card system-maintenance-card-v0540f" data-control-scope="system">'
    check(details_marker in system_html, "Advanced Maintenance is a native details control")
    check("<details open" not in system_html and " open>" not in system_html, "Advanced Maintenance is closed by default")

    retained_ids = {
        "system-cpu",
        "system-ram",
        "system-disk",
        "system-uptime",
        "ais-status-radio",
        "adsb-status-radio",
        "system-control-result",
        "mission-sounds-enabled",
        "mission-sounds-volume",
        "mission-sounds-volume-value",
        "mission-sounds-test",
        "mission-sounds-status",
    }
    check(retained_ids.issubset(set(parser.ids)), "all existing System and sound handler IDs are retained")
    check('data-action="start_ais"' in system_html and 'data-action="stop_ais"' in system_html, "AIS manual controls are retained")
    check('data-action="start_adsb"' in system_html and 'data-action="stop_adsb"' in system_html, "ADS-B manual controls are retained")
    check('data-action="simulate_record"' in system_html, "Simulate Recording action is retained")
    check('data-mission-action="reset"' in system_html, "Reset Mission Engine action and confirmation path are retained")

    check("system-health-grid-v0540f" in system_css, "compact System Health grid is styled")
    check("system-service-controls" in system_css, "equal Service Control cards are styled")
    check("system-maintenance-card-v0540f[open]" in system_css, "collapsed maintenance disclosure has an open state")
    combined_system_css = system_css + "\n" + inventory_css
    check(all(color in combined_system_css for color in ("#22c55e", "#38bdf8", "#f59e0b", "#ef4444")), "Queue status color vocabulary is present")
    check(all(tone in inventory_css for tone in ("is-mission-active", "is-service-active", "is-attention", "is-unavailable")), "Receiver Inventory maps runtime states to Queue tones")

    check("number >= 85" in system_js and "number >= 65" in system_js, "existing health warning thresholds are retained")
    check("setServiceState" in services_js and "is-running" in services_js and "is-stopped" in services_js, "service observer state drives presentation classes")
    check('fetch("/api/receiver-inventory"' in inventory_js, "Receiver Inventory keeps the existing read-only endpoint")
    check("systemctl" not in "\n".join((system_js, services_js, inventory_js, sounds_js)), "System presentation code contains no service authority")
    check("Mission Event Center" not in sounds_js, "notification test no longer exposes the removed card name")

    check("v=0.54.0f" in dashboard_loader, "dashboard module cache bust is updated")
    check('system.js?v=0.54.0f' in dashboard_js and 'services.js?v=0.54.0f' in dashboard_js, "System JavaScript module cache busts are updated")
    check(html.count("v=0.54.0f") >= 5, "System assets use the v0.54.0f cache bust")

    print("VALIDATION PASS: SDRCC v0.54.0f System Status Clarity")


if __name__ == "__main__":
    main()
