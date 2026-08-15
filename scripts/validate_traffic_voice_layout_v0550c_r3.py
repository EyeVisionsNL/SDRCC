#!/usr/bin/env python3
"""Validate the balanced Traffic Voice layout and neutral channel-bank names."""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys


ROOT = Path(os.environ.get("SDRCC_ROOT") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT))


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def validate_layout():
    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/static/css/traffic_voice.css").read_text(encoding="utf-8")
    javascript = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    section = html.split('id="tab-traffic-voice"', 1)[1].split(
        'id="tab-mission-planner"', 1
    )[0]
    marine = section.split('data-traffic-mode="marine_ais"', 1)[1].split(
        'data-traffic-mode="airband_adsb"', 1
    )[0]
    airband = section.split('data-traffic-mode="airband_adsb"', 1)[1].split(
        'class="traffic-voice-shared-workspace"', 1
    )[0]

    check('id="traffic-voice-start"' in marine, "Marine start control belongs to Marine workspace")
    check(
        'data-traffic-channel-bank="marine_ais"' in marine,
        "Marine channel bank belongs to Marine workspace",
    )
    check(
        'id="traffic-voice-start-airband"' in airband,
        "Airband start control belongs to Airband workspace",
    )
    check(
        'data-traffic-channel-bank="airband_adsb"' in airband,
        "Airband channel bank belongs to Airband workspace",
    )
    check(section.count('class="card traffic-voice-mode"') == 2, "exactly two equal mode workspaces")
    check(section.count('class="card traffic-voice-shared-workspace"') == 1, "one shared receiver workspace")
    check("traffic-voice-contract-card" not in section, "duplicated Selected Configuration card removed")
    check("traffic-voice-workspace-grid" not in section, "misleading lower two-column grid removed")

    ids = re.findall(r'\bid="([^"]+)"', section)
    check(len(ids) == len(set(ids)), "Traffic Voice element IDs are unique")
    check(
        "grid-template-columns: repeat(2, minmax(0, 1fr));" in css
        and ".traffic-voice-mode .traffic-voice-channel-activity" in css,
        "desktop mode workspaces have equal columns and channel heights",
    )
    check(
        "function renderChannelBank(mode, payload)" in javascript
        and "modes.forEach(mode => renderChannelBank(mode, payload))" in javascript,
        "both channel banks are rendered from the existing mode API",
    )
    check(
        "row.disabled = !selected || actionBusy || !payload.ok" in javascript,
        "inactive mode channels remain read-only",
    )


def validate_names_and_api():
    from core import config, traffic_voice

    raw = config.load_traffic_voice()
    settings = raw["traffic_voice"]
    marine = settings["modes"]["marine_ais"]
    airband = settings["modes"]["airband_adsb"]
    check(marine["channel_bank"] == "rotterdam_port", "neutral Rotterdam Port bank name")
    check(airband["channel_bank"] == "rotterdam_aviation", "neutral Rotterdam Aviation bank name")

    snapshot = traffic_voice.get_snapshot(
        service_reader=lambda service: {"service": service, "active": False, "state": "inactive"},
        audio_reader=lambda: {"ok": True, "available": False, "stream_state": "WAITING"},
    )
    banks = {mode["id"]: mode["channel_bank"] for mode in snapshot["modes"]}
    check(banks["marine_ais"] == "rotterdam_port", "Marine API exposes neutral bank name")
    check(banks["airband_adsb"] == "rotterdam_aviation", "Airband API exposes neutral bank name")

    forbidden = "".join(("co", "en"))
    scan_paths = [
        ROOT / "config/traffic_voice.yaml",
        ROOT / "dashboard/templates/index.html",
        ROOT / "dashboard/static/js/traffic_voice.js",
        ROOT / "docs/traffic-voice-marine-v0550b.md",
        ROOT / "scripts/validate_traffic_voice_controls_v0550b.py",
    ]
    check(
        all(forbidden not in path.read_text(encoding="utf-8").lower() for path in scan_paths),
        "personal name removed from Traffic Voice sources",
    )


def main():
    validate_layout()
    validate_names_and_api()
    print("VALIDATION PASS: SDRCC v0.55.0c-r3 balanced Traffic Voice layout")


if __name__ == "__main__":
    main()
