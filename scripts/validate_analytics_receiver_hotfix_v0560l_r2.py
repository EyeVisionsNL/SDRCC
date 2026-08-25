#!/usr/bin/env python3
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
js = (ROOT/"dashboard/static/js/mission_analytics.js").read_text()

def check(ok, msg):
    if not ok:
        print("FAIL:", msg)
        raise SystemExit(1)
    print("PASS:", msg)

check((ROOT/"VERSION").read_text().strip() == "0.56.0l", "release remains 0.56.0l")
check("function analyticsReceiverLabel" in js, "receiver display normalizer retained")
check('kind === "receiver" ? analyticsReceiverLabel' in js,
      "Receiver Performance uses display normalizer")
check('return "SDR1"' in js and 'return "SDR2"' in js,
      "normalizer maps to SDR1 and SDR2")
check("escapeHtmlanalyticsReceiverLabel" not in js,
      "malformed receiver label call removed")
check("mission_history" not in js.lower(),
      "hotfix does not add Mission History write logic")
print("VALIDATION PASS: SDRCC v0.56.0l-r2 Analytics Receiver Display Hotfix")
