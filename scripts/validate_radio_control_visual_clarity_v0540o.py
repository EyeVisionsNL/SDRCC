#!/usr/bin/env python3
"""Deterministic presentation validator for SDRCC v0.54.0o Radio Control."""

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
theme = (ROOT / "dashboard/static/css/radio_control_theme.css").read_text(encoding="utf-8")
radio_js = (ROOT / "dashboard/static/js/radio.js").read_text(encoding="utf-8")
runtime_js = (ROOT / "dashboard/static/js/runtime_diagnostics.js").read_text(encoding="utf-8")

radio_start = template.index('<section class="tab-page" id="tab-radio">')
radio_view_start = template.index('<section class="tab-page" id="tab-radio-view">')
radio_html = template[radio_start:radio_view_start]

check(
    '/static/css/radio_control_theme.css?v=0.54.0o-r2' in template,
    "Radio Control theme is loaded with the v0.54.0o-r2 cache key",
)

for label in (
    "Receiver Monitor",
    "Receiver Runtime Diagnostics",
    "Receiver Assignments",
    "Weather / METEOR Settings",
    "ISS Voice Settings",
):
    check(label in radio_html, f"approved Radio Control section remains present: {label}")

for element_id in (
    "receiver-monitor-grid",
    "receiver-runtime-grid",
    "receiver-assignments-form",
    "weather-rf-form",
    "iss-voice-settings-form",
):
    check(f'id="{element_id}"' in radio_html, f"existing control contract remains present: {element_id}")

for token, label in (
    ("--radio-control-cyan: #38bdf8", "primary Radio Control accent uses cyan"),
    ("--radio-control-meteor-3: #22d3ee", "Weather / METEOR uses cyan"),
    ("--radio-control-purple: #a78bfa", "Runtime Diagnostics uses purple"),
    ("--radio-control-iss: #fbbf24", "ISS Voice uses yellow"),
    ("--radio-control-green: #22c55e", "healthy and authority state uses green"),
    ("--radio-control-amber: #f59e0b", "attention state uses amber"),
    ("--radio-control-red: #ef4444", "failure state uses red"),
):
    check(token in theme, label)

for selector, label in (
    ("#tab-radio .radio-panel-v0540g.is-observer", "Receiver Monitor has a scoped panel accent"),
    ("#tab-radio .radio-panel-v0540g.is-diagnostics", "Runtime Diagnostics has a scoped panel accent"),
    ("#tab-radio .radio-panel-v0540g.is-authority", "Receiver Assignments has a scoped panel accent"),
    ("#tab-radio .radio-panel-v0540g.is-weather", "Weather settings have a scoped panel accent"),
    ("#tab-radio .radio-panel-v0540g.is-iss", "ISS Voice settings have a scoped panel accent"),
    ("#tab-radio .receiver-monitor-item.role-adsb", "receiver role identity remains visible"),
    ("#tab-radio .runtime-assignment-verification.is-drift", "runtime drift keeps failure meaning"),
    ("#tab-radio .assignment-runtime-role[data-state=\"unverified\"]", "assignment attention state remains visible"),
):
    check(selector in theme, label)

check("#tab-radio" in theme and "#tab-radio-view" not in theme, "theme is isolated to Radio Control")
check("/api/" not in theme and "fetch(" not in theme, "stylesheet contains no data or control coupling")

for endpoint, label in (
    ('/api/receiver-monitor', "Receiver Monitor keeps its observer endpoint"),
    ('/api/receiver-assignments', "Receiver Assignments keeps its authority endpoint"),
    ('/api/weather-rf', "Weather settings keep their endpoint"),
    ('/api/iss-voice/settings', "ISS Voice settings keep their endpoint"),
):
    check(endpoint in radio_js, label)

check('/api/receiver-runtime' in runtime_js, "Runtime Diagnostics keeps its observer endpoint")
check('/api/live-rf' not in radio_js, "Radio Control does not restore duplicate Live RF polling")

if errors:
    raise SystemExit(f"FAIL: {len(errors)} v0.54.0o validation check(s) failed")

print("PASS: v0.54.0o Radio Control visual clarity validation complete")
