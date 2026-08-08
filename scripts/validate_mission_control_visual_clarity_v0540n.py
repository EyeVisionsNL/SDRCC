#!/usr/bin/env python3
"""Deterministic presentation validator for SDRCC v0.54.0n Mission Control."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []


def check(condition: bool, label: str) -> None:
    if condition:
        print(f"PASS: {label}")
    else:
        print(f"FAIL: {label}")
        errors.append(label)


template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
theme = (ROOT / "dashboard/static/css/mission_control_theme.css").read_text(encoding="utf-8")
mission_js = (ROOT / "dashboard/static/js/mission.js").read_text(encoding="utf-8")
dashboard_js = (ROOT / "dashboard/static/js/dashboard.js").read_text(encoding="utf-8")
scheduler_js = (ROOT / "dashboard/static/js/scheduler.js").read_text(encoding="utf-8")

check(
    '/static/css/mission_control_theme.css?v=0.54.0n-r1' in template,
    "Mission Control theme is loaded with the v0.54.0n-r1 cache key",
)
check(
    '/static/dashboard.js?v=0.54.0n-r1' in template
    and './mission.js?v=0.54.0n-r1' in dashboard_js,
    "changed presentation modules are cache-busted",
)
check(
    './scheduler.js?v=0.54.0n-r1' in dashboard_js
    and './mission.js?v=0.54.0n-r1' in scheduler_js,
    "Mission Queue and receiver cards share one presentation module instance",
)

for token, label in (
    ("--mission-control-meteor-3: #22d3ee", "METEOR-M2 3 uses cyan"),
    ("--mission-control-meteor-4: #a78bfa", "METEOR-M2 4 uses purple"),
    ("--mission-control-iss: #fbbf24", "ISS uses yellow"),
    ("--mission-control-green: #22c55e", "healthy status uses green"),
    ("--mission-control-amber: #f59e0b", "attention status uses amber"),
    ("--mission-control-red: #ef4444", "failure status uses red"),
):
    check(token in theme, label)

for selector, label in (
    (".mission-queue-card-v034", "Mission Queue receives themed card hierarchy"),
    (".controls-panel-v034", "operator controls receive themed card hierarchy"),
    (".mission-receiver-card-v034.is-meteor-3", "receiver card supports M2-3 identity"),
    (".mission-receiver-card-v034.is-meteor-4", "receiver card supports M2-4 identity"),
    (".mission-receiver-card-v034.is-iss", "receiver card supports ISS identity"),
    (".timeline-item.category-receiver", "timeline category meaning remains visible"),
    (".execution-journal-summary-v043 > div:nth-child(4)", "journal failure summary uses a semantic accent"),
):
    check(selector in theme, label)

check("function satelliteTone(value)" in mission_js, "presentation maps visible satellite identity")
check("applySatelliteTone(receiver, satellite);" in mission_js, "receiver card receives satellite presentation class")
check("fetch(" not in mission_js, "presentation change introduces no API call")
check("/api/" not in theme, "theme contains no data or control coupling")

for contract, label in (
    ('phase = missedStart ? "NOT STARTED" : "MISSION OVERLAP"', "overlap status behavior is preserved"),
    ('endEpoch ? formatCountdown(endEpoch - now) : "NOW / ACTIVE"', "active remaining-time behavior is preserved"),
    ('const classes = ["is-ready", "is-next", "is-active", "is-recording", "is-processing", "is-blocked", "is-failed"]', "mission status classes remain authoritative"),
):
    check(contract in mission_js, label)

if errors:
    raise SystemExit(f"FAIL: {len(errors)} v0.54.0n validation check(s) failed")

print("PASS: v0.54.0n Mission Control visual clarity validation complete")
