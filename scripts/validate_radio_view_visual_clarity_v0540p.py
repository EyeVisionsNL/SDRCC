#!/usr/bin/env python3
"""Validate the style-only Radio View visual clarity release."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
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


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
theme = (ROOT / "dashboard/static/css/radio_view_theme.css").read_text(encoding="utf-8")
javascript = (ROOT / "dashboard/static/js/radio_view.js").read_text(encoding="utf-8")

radio_view_start = template.index('<section class="tab-page" id="tab-radio-view">')
planner_start = template.index('<section class="tab-page" id="tab-mission-planner">')
radio_view_html = template[radio_view_start:planner_start]

check(
    '/static/css/radio_view_theme.css?v=0.54.0p-r1' in template,
    "Radio View theme is loaded with the v0.54.0p-r1 cache key",
)

for class_name, label in (
    ("radio-view-panel is-adsb", "ADS-B panel has its semantic visual class"),
    ("radio-view-panel is-ais", "AIS panel has its semantic visual class"),
    ("radio-view-satellite-panel is-satellite", "Satellite panel has its semantic visual class"),
):
    check(class_name in radio_view_html, label)

for phrase, label in (
    ("Live tar1090 viewer", "ADS-B presentation label is English"),
    ("Live AIS-Catcher viewer", "AIS presentation label is English"),
):
    check(phrase in radio_view_html, label)

for token, label in (
    ("--radio-view-meteor-3: #22d3ee", "M2-3 identity uses cyan"),
    ("--radio-view-meteor-4: #a78bfa", "M2-4 identity uses purple"),
    ("--radio-view-iss: #fbbf24", "ISS identity uses yellow"),
    ("--radio-view-green: #22c55e", "healthy and live state uses green"),
    ("--radio-view-amber: #f59e0b", "attention state uses amber"),
    ("--radio-view-red: #ef4444", "failure state uses red"),
    ("#tab-radio-view .radio-view-panel.is-adsb", "ADS-B has a scoped purple panel accent"),
    ("#tab-radio-view .radio-view-panel.is-ais", "AIS has a scoped cyan panel accent"),
    ("#tab-radio-view .radio-view-panel.is-satellite", "Satellite View has a scoped panel accent"),
    ("#tab-radio-view .radio-view-satellite-selector button.is-active", "satellite selection remains visually explicit"),
    ("#tab-radio-view .radio-view-badge.is-online", "online state remains visually explicit"),
    ("#tab-radio-view .radio-view-badge.is-offline", "offline state remains visually explicit"),
    ("#tab-radio-view .radio-view-open-button", "viewer actions use the panel accent"),
):
    check(token in theme, label)

check("#tab-radio-view" in theme and "#tab-radio " not in theme, "theme is isolated to Radio View")
check("/api/" not in theme and "fetch(" not in theme, "stylesheet contains no data or control coupling")

for contract, label in (
    ('id="radio-view-adsb-frame"', "ADS-B iframe contract remains present"),
    ('id="radio-view-ais-frame"', "AIS iframe contract remains present"),
    ('id="radio-view-satellite-map"', "satellite world map contract remains present"),
    ('id="radio-view-satellite-footprints"', "satellite footprints remain present"),
    ('id="radio-view-satellite-tracks"', "satellite tracks remain present"),
    ('class="radio-view-satellite-selector"', "all-satellite selector remains present"),
    ('id="radio-view-next-satellite"', "next planned mission projection remains present"),
):
    check(contract in radio_view_html, label)

for contract, label in (
    ('/api/satellite-view', "Radio View keeps the orbital observer endpoint"),
    ('/api/mission-queue', "Radio View keeps Mission Queue as next-pass source"),
    ('/api/mission-engine', "Radio View keeps the mission observer endpoint"),
    ('setInterval(() =>', "Radio View keeps its existing bounded refresh loop"),
    ('10000', "Radio View keeps its ten-second live refresh interval"),
    ('data-open-tab="images"', "Satellite View keeps Mission Operations navigation"),
):
    haystack = radio_view_html if contract.startswith("data-") else javascript
    check(contract in haystack, label)

check("world-map-equirectangular.svg" in radio_view_html, "offline world map remains the Satellite View base")
check("radio-view-live-image-wrap" not in radio_view_html, "Mission Operations preview is not duplicated")

parser = IdCollector()
parser.feed(template)
duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
check(not duplicates, "Radio View visual release introduces no duplicate element IDs")

print("PASS: v0.54.0p Radio View visual clarity validation complete")
