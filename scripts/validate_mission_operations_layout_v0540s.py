#!/usr/bin/env python3
"""Validate Mission Operations layout alignment for SDRCC v0.54.0s."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import os
import re


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def main() -> None:
    template = read("dashboard/templates/index.html")
    stylesheet = read("dashboard/static/css/mission_recordings.css")
    javascript = read("dashboard/static/js/mission_recordings.js")
    backend = read("core/mission_operations.py")
    app = read("dashboard/app.py")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    check(
        'mission_recordings.css?v=0.54.0s-r1' in template,
        "Mission Operations stylesheet uses the v0.54.0s cache key",
    )
    check(
        '<section class="card mission-operations-header">' not in template
        and "Live Weather and ISS workspace with a read-only result viewer." not in template,
        "redundant non-interactive Mission Operations title card is removed",
    )
    check(
        '<span id="mission-operations-mode-badge" hidden>' in template
        and '<span id="mission-operations-updated" hidden>' in template,
        "existing live-mode and updated-time JavaScript hooks remain internal",
    )
    check(
        ".mission-operations-live-grid,\n.mission-operations-results-grid" in stylesheet
        and "grid-template-columns: repeat(2, minmax(0, 1fr));" in stylesheet,
        "live and result rows share one equal-width desktop grid",
    )
    check(
        "grid-template-columns: minmax(0, 1.08fr) minmax(390px, .92fr);" not in stylesheet
        and "grid-template-columns: minmax(320px, .72fr) minmax(0, 1.28fr);" not in stylesheet,
        "former unequal row-specific column ratios are removed",
    )
    responsive = re.search(
        r"@media \(max-width: 1250px\) \{(?P<body>.*?)\n\}",
        stylesheet,
        flags=re.DOTALL,
    )
    check(
        responsive is not None
        and ".mission-operations-live-grid" in responsive.group("body")
        and ".mission-operations-results-grid" in responsive.group("body")
        and "grid-template-columns: 1fr;" in responsive.group("body"),
        "both grids still stack below the existing 1250 px breakpoint",
    )
    check(
        "const badge = byId('mission-operations-mode-badge');" in javascript
        and "text('mission-operations-updated'" in javascript,
        "existing Mission Operations live refresh keeps its compatibility hooks",
    )
    check(
        "subprocess" not in backend and "systemctl" not in backend,
        "Mission Operations backend remains observer-only",
    )
    check(
        app.count('@app.route("/api/mission-operations")') == 1
        and app.count('@app.route("/api/iss-voice/audio-stream"') == 1
        and app.count('@app.route("/api/mission-recordings"') == 1,
        "existing Mission Operations API ownership remains unchanged",
    )
    check(
        os.environ.get("FAKE_MISSION_OPERATIONS_LAYOUT_FAIL") != "1",
        "injected Mission Operations layout failure is absent",
    )

    print("VALIDATION PASS: SDRCC v0.54.0s-r1 Mission Operations Layout Alignment")


if __name__ == "__main__":
    main()
