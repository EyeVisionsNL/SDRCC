#!/usr/bin/env python3
"""Validate presentation-only Mission History clarity for SDRCC v0.54.0m."""

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
    javascript = (ROOT / "dashboard/static/js/history.js").read_text(encoding="utf-8")
    stylesheet = (ROOT / "dashboard/static/css/history.css").read_text(encoding="utf-8")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    check(
        'history.css?v=0.54.0m-r1' in template
        and any(version in template for version in ('/static/dashboard.js?v=0.54.0m-r1', '/static/dashboard.js?v=0.54.0n-r1', '/static/dashboard.js?v=0.54.0q-r1', '/static/dashboard.js?v=0.54.0q-r3'))
        and any(version in loader for version in ('/static/js/dashboard.js?v=0.54.0m-r1', '/static/js/dashboard.js?v=0.54.0n-r1', '/static/js/dashboard.js?v=0.54.0q-r3'))
        and './history.js?v=0.54.0m-r1' in dashboard,
        "Mission History assets use the complete v0.54.0m cache chain",
    )

    for summary_class in ("is-total", "is-success", "is-images", "is-duration", "is-snr", "is-frames"):
        check(
            f'history-stat {summary_class}' in template,
            f"summary presentation hook is retained: {summary_class}",
        )

    check(
        'fetch(`/api/mission-history?${currentParameters().toString()}`' in javascript
        and 'fetch(`/api/mission-history/${encodeURIComponent(missionId)}`' in javascript,
        "existing Mission History list and detail endpoints remain authoritative",
    )
    check(
        'method: "DELETE"' in javascript
        and 'window.confirm(' in javascript
        and "selectedMissionId = null" in javascript,
        "confirmed exact-mission delete flow is retained",
    )
    check(
        'window.setInterval(() =>' in javascript
        and 'if (historyTabActive()) refreshMissionHistory();' in javascript
        and '}, 15000);' in javascript,
        "existing active-tab-only 15-second refresh is retained",
    )
    check(
        "const selectedGalleryImageByMission = new Map()" in javascript
        and "selectedGalleryImageByMission.set(missionKey" in javascript,
        "per-mission gallery selection remains stable",
    )
    check(
        all(token in javascript for token in ("is-meteor-3", "is-meteor-4", "is-iss", "is-neutral")),
        "all supported satellites receive presentation-only identity classes",
    )
    check(
        "mission.result" in javascript
        and "quality.result || mission.result" in javascript
        and "mission_history" not in javascript,
        "stored result and quality values remain the presentation source",
    )
    check(
        "receiverLabel(mission.receiver || mission.receiver_id)" in javascript
        and '["RECEIVER01", "SDR1", "RX01"]' in javascript
        and '["RECEIVER02", "SDR2", "RX02"]' in javascript,
        "receiver aliases are normalized to SDR1/SDR2 only in presentation",
    )
    check(
        'decoderApplicable' in javascript
        and 'imagesApplicable' in javascript
        and 'snrApplicable' in javascript
        and '"N/A"' in javascript,
        "ISS not-applicable quality fields remain explicit",
    )
    check(
        'toLocaleString("en-GB")' in javascript
        and 'toLocaleTimeString("en-GB"' in javascript
        and "Permanent overview of completed and cancelled satellite missions." in template,
        "Mission History uses the approved English UI locale",
    )

    for selector in (
        ".history-shell",
        ".history-stat.is-success.is-bad",
        ".history-mission.is-meteor-3",
        ".history-mission.is-meteor-4",
        ".history-mission.is-iss",
        ".history-quality.result-no-sync",
        ".history-detail-panel.is-iss",
        ".history-detail-overview .history-metric:nth-child(5)",
    ):
        check(selector in stylesheet, f"presentation selector is defined: {selector}")

    check(
        all(color in stylesheet for color in ("#38bdf8", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#fbbf24")),
        "approved SDRCC theme palette is used",
    )
    check(
        "systemctl" not in javascript
        and 'method: "POST"' not in javascript
        and "/api/mission-operations" not in javascript,
        "Mission History presentation introduces no service or runtime authority",
    )

    print("PASS: v0.54.0m-r1 Mission History Visual Clarity validation complete")


if __name__ == "__main__":
    main()
