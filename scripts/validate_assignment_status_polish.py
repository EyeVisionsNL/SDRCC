#!/usr/bin/env python3
"""Static UI checks for assignment authority and runtime verification."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
index = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
radio = (ROOT / "dashboard/static/js/radio.js").read_text(encoding="utf-8")
runtime = (ROOT / "dashboard/static/js/runtime_diagnostics.js").read_text(encoding="utf-8")

checks = [
    ("single assignment form present", 'id="receiver-assignments-form"' in index),
    ("authority status present", 'id="assignment-authority-status"' in index),
    ("drift panel present", 'id="assignment-authority-drift"' in index),
    ("result element retained", 'id="assignment-policy-result"' in index),
    ("runtime verification panel retained", 'id="assignment-policy-runtime"' in index),
    ("weather selector present", 'id="receiver-assignment-weather"' in index),
    ("AIS selector present", 'id="receiver-assignment-ais"' in index),
    ("ADS-B selector present", 'id="receiver-assignment-adsb"' in index),
    ("ISS selector present", 'id="receiver-assignment-iss-voice"' in index),
    ("old mission form absent", "mission-assignments-form" not in index),
    ("old defaults form absent", "receiver-defaults-form" not in index),
    ("single endpoint used", "/api/receiver-assignments" in radio),
    ("form dirty guard present", "assignmentFormDirty" in radio),
    ("form saving guard present", "assignmentFormSaving" in radio),
    ("drift rendered", "configuration_drift" in radio),
    ("verified runtime rendered", "verified_runtime" in radio),
    ("rollback feedback rendered", "rollback_performed" in radio),
    ("AIS/ADS-B collision checked client side", "AIS and ADS-B cannot" in radio),
    ("Runtime Diagnostics renders assignment verification", "assignment_verification" in runtime),
    ("Runtime Diagnostics never invents verified runtime", "niet actief / niet geverifieerd" in runtime),
]

failed = False
for label, ok in checks:
    print(("PASS" if ok else "FAIL") + ": " + label)
    failed |= not ok

for element_id in (
    "receiver-assignments-form",
    "assignment-authority-status",
    "assignment-authority-drift",
    "assignment-policy-result",
    "assignment-policy-runtime",
):
    count = index.count(f'id="{element_id}"')
    ok = count == 1
    print(("PASS" if ok else "FAIL") + f": {element_id} occurs exactly once")
    failed |= not ok

if failed:
    raise SystemExit(1)
print("VALIDATION PASS: v0.54.0a Assignment Authority UI")
