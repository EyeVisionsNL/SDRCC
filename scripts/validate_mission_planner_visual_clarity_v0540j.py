#!/usr/bin/env python3
"""Validate the presentation-only Mission Planner v0.54.0j contract."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/mission_planner.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "dashboard/static/css/mission_planner.css").read_text(encoding="utf-8")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    check(
        'mission_planner.css?v=0.54.0j-r1' in template
        and 'mission_planner.js?v=0.54.0j-r1' in template,
        "Mission Planner assets are cache-busted together",
    )
    check(
        template.count("mission-planner-summary-card") == 4,
        "all four summary cards use the visual status contract",
    )
    for profile in ("meteor_m2_3", "meteor_m2_4", "iss_voice"):
        check(
            f'data-planning-profile="{profile}"' in template,
            f"existing {profile} planning profile is retained",
        )

    api_paths = set(re.findall(r'fetch\("(/api/[^"?]+)', javascript))
    check(
        api_paths == {"/api/mission-queue", "/api/weather-planning"},
        "Mission Planner retains only its existing Queue and settings APIs",
    )
    check(
        '/api/mission-queue?limit=50&hours=48' in javascript,
        "planned passes remain sourced from the 48-hour Mission Queue",
    )
    check(
        'method: "POST"' in javascript
        and 'body: JSON.stringify({profiles})' in javascript
        and 'body: JSON.stringify({action: "refresh"})' in javascript,
        "save and TLE refresh actions retain their existing contracts",
    )
    check(
        "mission-planner-window-cell" in javascript
        and "mission-planner-satellite-marker" in javascript,
        "pass windows and satellite recognition have dedicated presentation hooks",
    )
    check(
        all(label in javascript for label in ("FAIR", "GOOD", "VERY GOOD", "EXCELLENT")),
        "stored quality grades render with English presentation labels",
    )
    check(
        all(name in javascript for name in ("meteor-3", "meteor-4", "iss")),
        "all supported satellites receive stable presentation classes",
    )

    for selector in (
        ".mission-planner-summary-card.is-passes",
        ".mission-planner-profile[data-planning-profile=\"meteor_m2_3\"]",
        ".mission-planner-row.is-target td",
        ".mission-planner-quality.is-excellent",
        ".mission-planner-state.is-conflict",
    ):
        check(selector in stylesheet, f"presentation selector is defined: {selector}")
    check(
        ".mission-planner-window-cell small { display: block;" in stylesheet,
        "pass-window angles render separately from the end time",
    )
    check(
        "color-scheme: dark" in stylesheet,
        "planning inputs follow the SDRCC dark control theme",
    )

    print("PASS: v0.54.0j-r1 Mission Planner Visual Clarity validation complete")


if __name__ == "__main__":
    main()
