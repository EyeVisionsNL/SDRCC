#!/usr/bin/env python3
"""Validate the presentation-only Mission Analytics v0.54.0k contract."""

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
    loader = (ROOT / "dashboard/static/dashboard.js").read_text(encoding="utf-8")
    dashboard = (ROOT / "dashboard/static/js/dashboard.js").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/mission_analytics.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "dashboard/static/css/mission_analytics.css").read_text(encoding="utf-8")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    check(
        'mission_analytics.css?v=0.54.0k-r1' in template
        and any(version in template for version in ('/static/dashboard.js?v=0.54.0k-r1', '/static/dashboard.js?v=0.54.0l-r1', '/static/dashboard.js?v=0.54.0m-r1', '/static/dashboard.js?v=0.54.0n-r1'))
        and any(version in loader for version in ('/static/js/dashboard.js?v=0.54.0k-r1', '/static/js/dashboard.js?v=0.54.0l-r1', '/static/js/dashboard.js?v=0.54.0m-r1', '/static/js/dashboard.js?v=0.54.0n-r1'))
        and './mission_analytics.js?v=0.54.0k-r1' in dashboard,
        "Mission Analytics assets remain cache-busted through an approved module chain",
    )
    for summary_class in ("is-total", "is-success", "is-snr", "is-elevation", "is-images", "is-frames"):
        check(
            f'mission-analytics-stat {summary_class}' in template,
            f"summary presentation hook is retained: {summary_class}",
        )

    check(
        'const API_URL = "/api/mission-history?limit=250";' in javascript,
        "Mission Analytics remains sourced only from Mission History",
    )
    check(
        "window.setInterval(refreshAnalytics, 30000)" in javascript,
        "existing 30-second refresh interval is retained",
    )
    check(
        'payload.statistics || {}' in javascript
        and 'stats.schema_version !== 2' in javascript
        and 'payload.missions || []' in javascript,
        "schema-2 statistics and stored mission rows retain their existing contract",
    )
    check(
        'toLocaleDateString("en-GB"' in javascript,
        "mission dates render in the English UI locale",
    )
    check(
        all(token in javascript for token in ("is-meteor-3", "is-meteor-4", "is-iss")),
        "all supported satellites receive stable identity classes",
    )
    check(
        all(token in javascript for token in ('"SUCCESS"', '"NO SYNC"', '"FAILED"', '"UNRATED"', '"POOR"')),
        "stored result and quality values receive presentation-only semantic classes",
    )
    check(
        'normalized === "SUCCESS"' in javascript
        and '["NO SYNC", "NO SIGNAL", "NO IMAGES"].includes(normalized)' in javascript,
        "existing outcome classification behavior is retained",
    )
    check(
        'successRate >= 80 ? "good" : successRate >= 50 ? "warn" : "bad"' in javascript,
        "existing receiver and satellite success thresholds are retained",
    )

    for selector in (
        ".mission-analytics-header",
        ".mission-analytics-stat.is-success.is-bad",
        ".mission-analytics-performance.is-satellite.is-meteor-3",
        ".mission-analytics-performance.is-satellite.is-meteor-4",
        ".mission-analytics-performance.is-satellite.is-iss",
        ".mission-analytics-breakdown-row.is-warn",
        ".mission-analytics-timeline-row b.good",
    ):
        check(selector in stylesheet, f"presentation selector is defined: {selector}")
    check(
        "--analytics-cyan: #38bdf8" in stylesheet
        and "--analytics-green: #22c55e" in stylesheet
        and "--analytics-amber: #f59e0b" in stylesheet
        and "--analytics-red: #ef4444" in stylesheet
        and "--analytics-purple: #a78bfa" in stylesheet,
        "approved SDRCC theme palette is used",
    )

    print("PASS: v0.54.0k-r1 Mission Analytics Visual Clarity validation complete")


if __name__ == "__main__":
    main()
