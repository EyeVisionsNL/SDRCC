#!/usr/bin/env python3
"""Validate the presentation-only SDRCC v0.54.0r System theme."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name == "id" and value:
                self.ids.append(value)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    if os.environ.get("FAKE_SYSTEM_THEME_FAIL") == "1":
        raise RuntimeError("injected System theme validation failure")

    template = read("dashboard/templates/index.html")
    theme = read("dashboard/static/css/system_theme.css")
    services_js = read("dashboard/static/js/services.js")
    system_js = read("dashboard/static/js/system.js")
    inventory_js = read("dashboard/static/js/receiver_inventory.js")
    dashboard_js = read("dashboard/static/js/dashboard.js")
    api_js = read("dashboard/static/js/api.js")

    system_start = template.index('id="tab-system"')
    radio_start = template.index('id="tab-radio"')
    system_html = template[system_start:radio_start]

    check(
        '/static/css/system_theme.css?v=0.54.0r-r1' in template,
        "System theme is loaded with the v0.54.0r-r1 cache key",
    )

    for phrase, label in (
        ("System Health", "System Health remains present"),
        ("Receiver Inventory", "Receiver Inventory remains present"),
        ("Service Control", "Service Control remains present"),
        ("Advanced Maintenance", "Advanced Maintenance remains present"),
        ("AIS-Catcher Control", "AIS-Catcher Control remains a separate maintenance tool"),
    ):
        check(phrase in system_html, label)

    for token, label in (
        ("--system-theme-cyan: #38bdf8", "System Health and AIS identity use cyan"),
        ("--system-theme-purple: #a78bfa", "Receiver Inventory and ADS-B identity use purple"),
        ("--system-theme-amber: #f59e0b", "Advanced Maintenance uses amber"),
        ("--system-theme-green: #22c55e", "healthy state uses green"),
        ("--system-theme-red: #ef4444", "failure state uses red"),
        ("#tab-system .system-health-card-v0540f", "System Health has a scoped panel theme"),
        ("#tab-system .receiver-inventory-card", "Receiver Inventory has a scoped panel theme"),
        ("#tab-system #system-service-ais", "AIS has a scoped cyan identity"),
        ("#tab-system #system-service-adsb", "ADS-B has a scoped purple identity"),
        ("#tab-system .system-maintenance-card-v0540f", "Advanced Maintenance has a scoped amber identity"),
        ("inset -3px 0 0 var(--health-status)", "System Health separates identity from status"),
        ("inset -3px 0 0 var(--receiver-status)", "Receiver Inventory separates identity from status"),
        ("inset -3px 0 0 var(--service-status)", "Service Control separates identity from status"),
        (".system-service-row.is-running", "running service state remains explicit"),
        (".system-service-row.is-starting", "starting service state remains explicit"),
        (".system-service-row.is-partial", "partial service state remains explicit"),
        (".system-service-row.is-attention", "attention service state remains explicit"),
    ):
        check(token in theme, label)

    check("#tab-system" in theme and "#tab-radio " not in theme and "#tab-mission " not in theme, "theme is isolated to System")
    check("/api/" not in theme and "fetch(" not in theme and "systemctl" not in theme, "stylesheet contains no data or control coupling")

    for contract, label in (
        ('id="system-cpu"', "CPU metric contract remains present"),
        ('id="receiver-inventory"', "Receiver Inventory observer target remains present"),
        ('data-action="start_ais"', "normal AIS Start control remains present"),
        ('data-action="stop_ais"', "normal AIS Stop control remains present"),
        ('data-action="start_adsb"', "ADS-B Start control remains present"),
        ('data-action="stop_adsb"', "ADS-B Stop control remains present"),
        ('data-action="start_ais_control"', "maintenance-only Control Start remains present"),
        ('data-action="stop_ais_control"', "maintenance-only Control Stop remains present"),
        ('<details class="card system-maintenance-card-v0540f"', "Advanced Maintenance remains closed-by-default capable"),
    ):
        check(contract in system_html, label)

    check("<details open" not in system_html and " open>" not in system_html, "Advanced Maintenance remains closed by default")
    check("updateSystem" in system_js and "/api/status" in api_js, "System Health keeps its existing observer endpoint")
    check('fetch("/api/receiver-inventory"' in inventory_js, "Receiver Inventory keeps its existing observer endpoint")
    check("start_ais_control" in services_js and "stop_ais_control" in services_js, "AIS-Catcher Control keeps its independent action path")
    check("setInterval(refreshDashboard, 5000)" in dashboard_js, "Service Control keeps its existing polling loop")

    parser = IdCollector()
    parser.feed(template)
    duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
    check(not duplicates, "System visual release introduces no duplicate element IDs")

    print("PASS: v0.54.0r System visual clarity validation complete")


if __name__ == "__main__":
    main()
