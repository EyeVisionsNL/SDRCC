#!/usr/bin/env python3
"""Validate the presentation-only v0.55.0f banner satellite correction."""

from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TARGET_TRANSFORM = "translate(545 86) rotate(-12)"
VIEWBOX_WIDTH = 760.0
VIEWBOX_HEIGHT = 180.0
DESKTOP_HEADER_HEIGHT = 88.0


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def rotated_y(x: float, y: float, translate_y: float = 86.0) -> float:
    angle = math.radians(-12.0)
    return translate_y + (x * math.sin(angle)) + (y * math.cos(angle))


def desktop_visible_y_range(viewport_width: float) -> tuple[float, float]:
    artwork_width = min(viewport_width * 0.58, 880.0)
    scale = max(artwork_width / VIEWBOX_WIDTH, DESKTOP_HEADER_HEIGHT / VIEWBOX_HEIGHT)
    visible_height = DESKTOP_HEADER_HEIGHT / scale
    margin = (VIEWBOX_HEIGHT - visible_height) / 2.0
    return margin, VIEWBOX_HEIGHT - margin


def main() -> None:
    required = (
        "README.md",
        "VERSION",
        "dashboard/templates/index.html",
        "dashboard/static/css/header_theme.css",
        "docs/header-banner-satellite-v0550f.md",
    )
    for relative_path in required:
        check((ROOT / relative_path).is_file(), f"required file present: {relative_path}")

    template = read("dashboard/templates/index.html")
    stylesheet = read("dashboard/static/css/header_theme.css")
    version = read("VERSION").strip()
    check(version == "0.56.0c", "current release version is 0.56.0c")

    svg = re.search(
        r'<svg class="topbar-space-art"[^>]*>(.*?)</svg>',
        template,
        re.DOTALL,
    )
    check(svg is not None, "existing inline banner SVG remains present")
    artwork = svg.group(0) if svg else ""
    check('viewBox="0 0 760 180"' in artwork, "banner SVG view box is unchanged")
    check(
        'preserveAspectRatio="xMidYMid slice"' in artwork,
        "existing responsive banner crop is unchanged",
    )
    check(artwork.count('class="topbar-satellite"') == 1, "one satellite group remains present")
    check(f'transform="{TARGET_TRANSFORM}"' in artwork, "satellite uses the corrected vertical position")
    check("translate(545 48)" not in artwork, "clipped satellite position is retired")

    for token, label in (
        ('class="topbar-satellite-panel"', "existing satellite panels are reused"),
        ('class="topbar-satellite-body"', "existing satellite body is reused"),
        ('class="topbar-satellite-dish"', "existing satellite dish is reused"),
        ('d="M248 188 Q 470 74 780 158"', "existing earth curve is unchanged"),
        ('class="topbar-orbit"', "existing orbit is unchanged"),
    ):
        check(token in artwork, label)

    check("min-height: 88px" in stylesheet, "compact desktop header height remains 88 pixels")
    check("width: min(58vw, 880px)" in stylesheet, "existing responsive artwork width remains unchanged")
    check("height: 100%" in stylesheet, "artwork still follows the header height")

    # Corners and extrema of both panels/body plus the dish endpoints/control point.
    points = (
        (-62.0, -10.0), (-17.0, -10.0), (-62.0, 10.0), (-17.0, 10.0),
        (17.0, -10.0), (62.0, -10.0), (17.0, 10.0), (62.0, 10.0),
        (-17.0, -15.0), (17.0, -15.0), (-17.0, 15.0), (17.0, 15.0),
        (-4.0, -17.0), (0.0, -31.0), (15.0, -29.0),
    )
    satellite_min = min(rotated_y(x, y) for x, y in points)
    satellite_max = max(rotated_y(x, y) for x, y in points)
    for viewport in (1100.0, 1366.0, 1920.0):
        visible_min, visible_max = desktop_visible_y_range(viewport)
        check(
            visible_min <= satellite_min and satellite_max <= visible_max,
            f"complete satellite fits the {int(viewport)}px desktop banner crop",
        )

    parser = ContractParser()
    parser.feed(template)
    duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
    check(not duplicates, "banner correction introduces no duplicate element IDs")
    check("<img" not in artwork, "banner correction adds no external image asset")

    print("VALIDATION PASS: v0.55.0f header banner satellite visibility")


if __name__ == "__main__":
    main()
