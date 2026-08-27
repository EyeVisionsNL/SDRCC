#!/usr/bin/env python3
"""Validate the UI-only Traffic Voice AIS Auto Follow contract."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    voice = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    radio = (ROOT / "dashboard/static/js/radio_view.js").read_text(encoding="utf-8")
    backend = (ROOT / "core/traffic_voice.py").read_text(encoding="utf-8")

    check(version == "0.56.0o", "release version is 0.56.0o")
    check(template.count('id="traffic-voice-auto-ais-vessel"') == 1, "one AIS Auto control is present")
    check('aria-pressed="false"' in template and "Auto: off" in template, "AIS Auto defaults visibly off")
    check("traffic-voice-show-ais-vessel" in template, "existing manual AIS map control remains present")
    check("toggleAisAuto" in voice and "maybeAutoFollowAis" in voice, "Traffic Voice owns the UI-only Auto lifecycle")
    check("match?.mmsi" in voice and "^\\d{9}$" in voice, "Auto accepts only a valid matched MMSI")
    check("mmsi === lastAutoAisMmsi" in voice, "repeated polling does not renavigate the same vessel")
    check("map window was closed" in voice, "closed map window disables Auto safely")
    check("openAisAutoWindow" in radio and "updateAisAutoWindow" in radio, "Radio View retains AIS window integration ownership")
    check('"flexground-sdr-ais-auto"' in radio, "Auto reuses one named AIS map window")
    check("window.open" not in voice, "Traffic Voice does not duplicate browser-window authority")
    check("setInterval" not in radio.split("function openAisAutoWindow", 1)[1].split("async function fetchJson", 1)[0], "AIS Auto adds no polling loop")
    check("ais_matcher = receiver_monitor.match_ais_callsign" in backend, "existing backend AIS matcher remains authoritative")
    check('/static/js/radio_view.js?v=0.56.0o' in template, "Radio View cache key is current")
    check('/static/js/traffic_voice.js?v=0.56.0o' in template, "Traffic Voice cache key is current")
    check('/static/css/traffic_voice.css?v=0.56.0o' in template, "Traffic Voice CSS cache key is current")

    print("VALIDATION PASS: FlexGround SDR v0.56.0o Traffic Voice AIS Auto Follow")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
