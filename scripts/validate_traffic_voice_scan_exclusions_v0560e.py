#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
checks = []

def check(ok, msg):
    print(("PASS: " if ok else "FAIL: ") + msg)
    checks.append(bool(ok))

version = (ROOT / "VERSION").read_text().strip()
core = (ROOT / "core/traffic_voice.py").read_text()
js = (ROOT / "dashboard/static/js/traffic_voice.js").read_text()
css = (ROOT / "dashboard/static/css/traffic_voice.css").read_text()
doc = ROOT / "docs/traffic-voice-scan-exclusions-v0560e.md"

def numeric_version_prefix(value):
    parts = []
    for piece in value.split("."):
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)

version_prefix = numeric_version_prefix(version)
check(version_prefix >= (0, 56, 0), f"release {version} retains the v0.56.0e scan contract")
check('channel.get("scan_enabled", True)' in core, "missing scan flag defaults to included")
check('"scan_channel_ids"' in core, "receiver settings expose bounded scan channel IDs")
check('Selecteer minimaal één kanaal voor Scan all channels' in core, "empty scan list is rejected")
check('enabled_scan_ids = set(receiver_settings["scan_channel_ids"])' in core, "runtime config filters the existing channel bank")
check('channels = [selected_channel]' in core, "fixed-channel path remains independent of scan inclusion")
check('channel["scan_enabled"]' in core, "scan selection persists in existing channel definitions")
check('data.scanChannelId' not in js and 'dataset.scanChannelId' in js, "scan checkbox is channel-scoped")
check('At least one channel must remain enabled for scanning.' in js, "UI prevents accidental empty scan list")
check('applySettings({scan_channel_ids: [...wanted]})' in js, "scan toggles use existing bounded settings action")
check('selectFixedChannel(channel.id)' in js, "manual fixed-channel listening is retained")
check('.traffic-voice-scan-toggle' in css, "scan inclusion control has page-local styling")
check(doc.exists(), "v0.56.0e documentation is present")
check('channel.get("scan_enabled", True)' in core and 'dataset.scanChannelId' in js, "scan contract coexists with later Traffic Voice RF controls")

if not all(checks):
    sys.exit(1)
print(f"VALIDATION PASS: SDRCC {version} retains v0.56.0e Traffic Voice scan exclusions")
