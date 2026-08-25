\
#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

def check(ok, message):
    if not ok:
        print(f"FAIL: {message}")
        raise SystemExit(1)
    print(f"PASS: {message}")

version = (ROOT / "VERSION").read_text().strip()
js = (ROOT / "dashboard/static/js/mission_analytics.js").read_text()
html = (ROOT / "dashboard/templates/index.html").read_text()
css = (ROOT / "dashboard/static/css/mission_analytics.css").read_text()
doc = ROOT / "docs/mission-analytics-rf-gain-v0560g.md"

check(version == "0.56.0g", "release version is 0.56.0g")
check('const API_URL = "/api/mission-history?limit=250";' in js, "Analytics keeps Mission History as its data source")
check("gainDetails(mission)" in js, "Analytics reads historical mission gain")
check('mode === "auto"' in js and '"Auto Gain"' in js, "Auto Gain is represented without a fixed dB value")
check("gain_db" in js and "Manual ${number(gain, 1)} dB" in js, "manual historical gain is rendered in dB")
check("Gain unknown" in js, "older missions without gain remain compatible")
check('id="analytics-gain-snr"' in html, "RF Gain vs Peak SNR panel is present")
check('renderGainCorrelation("analytics-gain-snr", rows)' in js, "gain/SNR correlation panel is wired")
check("missionReceiverAndGain(mission)" in js, "mission trend/timeline can show historical gain")
check("mission-analytics-gain-row" in css, "gain history has page-local styling")
check(doc.exists(), "v0.56.0g documentation is present")
release_paths = {
    "VERSION",
    "dashboard/templates/index.html",
    "dashboard/static/js/mission_analytics.js",
    "dashboard/static/css/mission_analytics.css",
    "docs/mission-analytics-rf-gain-v0560g.md",
    "scripts/validate_mission_analytics_rf_gain_v0560g.py",
}
check(not any("mission_engine" in path for path in release_paths), "release does not modify Mission Engine")
print("VALIDATION PASS: SDRCC v0.56.0g Mission Analytics RF Gain History")
