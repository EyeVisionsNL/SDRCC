#!/usr/bin/env python3
"""Validate v0.55.0e exact ATIS-to-AIS vessel correlation."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import receiver_monitor, traffic_voice  # noqa: E402


def passed(message: str) -> None:
    print(f"PASS: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    passed(message)


def vessel(**overrides: object) -> dict[str, object]:
    item: dict[str, object] = {
        "mmsi": 244670658,
        "lat": 51.894627,
        "lon": 4.336788,
        "distance": 0.97952,
        "bearing": 213,
        "heading": 72,
        "cog": 78,
        "speed": 9.8,
        "validated": 1,
        "callsign": "PC4621",
        "shipname": "MI-DESEO",
        "destination": "ROTTERDAM 3E PETROHA",
        "eni": "02327130",
        "last_signal": 6,
    }
    item.update(overrides)
    return item


def validate_source_contract() -> None:
    required = [
        "core/receiver_monitor.py",
        "core/traffic_voice.py",
        "dashboard/static/js/radio_view.js",
        "dashboard/static/js/traffic_voice.js",
        "dashboard/static/css/traffic_voice.css",
        "dashboard/templates/index.html",
        "docs/traffic-voice-ais-correlation-v0550e.md",
    ]
    for relative in required:
        require((ROOT / relative).is_file(), f"required file present: {relative}")

    monitor = (ROOT / "core/receiver_monitor.py").read_text(encoding="utf-8")
    traffic = (ROOT / "core/traffic_voice.py").read_text(encoding="utf-8")
    decoder = (ROOT / "core/traffic_voice_atis.py").read_text(encoding="utf-8")
    radio_view = (ROOT / "dashboard/static/js/radio_view.js").read_text(encoding="utf-8")
    voice_ui = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    voice_css = (ROOT / "dashboard/static/css/traffic_voice.css").read_text(encoding="utf-8")
    template = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")

    require('VERSION = "0.56.0h"' in traffic, "current Traffic Voice backend retains the ATIS/AIS contract")
    require(
        monitor.count('"http://127.0.0.1:8119/ships.json"') == 1,
        "receiver_monitor retains one canonical AIS-Catcher endpoint",
    )
    require(
        "payload, source = _read_ais_ships()" in monitor,
        "AIS metrics and correlation reuse the shared ships reader",
    )
    require(
        "ais_matcher = receiver_monitor.match_ais_callsign" in traffic,
        "Traffic Voice delegates vessel correlation to receiver_monitor",
    )
    require("receiver_monitor" not in decoder, "passive ATIS decoder remains AIS-independent")
    require("url.searchParams.set(\"mmsi\"" in radio_view, "AIS viewer uses the MMSI deep link")
    require("url.searchParams.set(\"zoom\"" in radio_view, "AIS viewer uses bounded map zoom")
    require('link.target = "_blank"' in radio_view, "matched vessel opens in the full AIS viewer")
    require('link.rel = "noopener noreferrer"' in radio_view, "full AIS viewer tab is isolated")
    require("window.sdrccRadioView?.openAisVessel" in voice_ui, "Traffic Voice reuses Radio View")
    require("traffic-voice-show-ais-vessel" in template, "verified vessel map control is present")
    require("Show on full AIS map ↗" in template, "map control names the full viewer")
    require(
        '"MARINE + AIRBAND READY"' in voice_ui,
        "header reports readiness for both executable modes",
    )
    require(
        'running ? "ACTIVE MODE" : "SELECTED · STOPPED"' in voice_ui,
        "selected mode distinguishes running from stopped Voice",
    )
    require(
        '"AIRBAND RUNNING" : "MARINE RUNNING"' in voice_ui,
        "running service badge identifies the active mode",
    )
    require("MARINE READY" not in voice_ui, "header no longer hides Airband readiness")
    require(
        "<strong data-traffic-mode-state>SELECTED · STOPPED</strong>" in template,
        "initial Marine card does not claim to be active while Voice is stopped",
    )
    require("Receiver software" in template, "shared receiver engine has a clear UI label")
    require(
        '"RTLSDR-Airband"' in voice_ui and '" · AM/NFM"' in voice_ui,
        "receiver software value explains the shared AM/NFM capability",
    )
    require(
        ".traffic-voice-header {" in voice_css
        and "padding: 11px 18px;" in voice_css
        and ".traffic-voice-header h2 {" in voice_css,
        "Traffic Voice header uses the compact spacing contract",
    )
    require("contentDocument" not in radio_view, "dashboard does not access cross-origin iframe DOM")
    require("postMessage" not in radio_view, "dashboard does not add an undocumented viewer bridge")
    require("systemctl" not in monitor, "AIS correlation creates no service authority")


def validate_matching() -> None:
    live = {"ships": [vessel()]}
    match = receiver_monitor.match_ais_callsign(" pc4621 ", payload=live)
    require(match["matched"] is True, "live PC4621 record matches exactly")
    require(match["status"] == "matched", "successful match status is explicit")
    require(match["mmsi"] == "244670658", "matched MMSI is preserved")
    require(match["shipname"] == "MI-DESEO", "matched ship name is projected")
    require(match["eni"] == "02327130", "matched ENI is projected")
    require(match["latitude"] == 51.894627, "matched latitude is projected")
    require(match["longitude"] == 4.336788, "matched longitude is projected")
    require(match["last_signal_seconds"] == 6.0, "fresh AIS signal age is projected")

    missing = receiver_monitor.match_ais_callsign("PD0000", payload=live)
    require(missing["status"] == "not_found" and not missing["matched"], "missing call sign is not guessed")

    duplicate = {"ships": [vessel(), vessel(mmsi=244670659)]}
    ambiguous = receiver_monitor.match_ais_callsign("PC4621", payload=duplicate)
    require(ambiguous["status"] == "ambiguous" and not ambiguous["matched"], "duplicate call sign fails closed")

    stale_payload = deepcopy(live)
    stale_payload["ships"][0]["last_signal"] = 31
    stale = receiver_monitor.match_ais_callsign("PC4621", payload=stale_payload)
    require(stale["status"] == "stale" and not stale["matched"], "stale AIS position fails closed")

    unvalidated_payload = deepcopy(live)
    unvalidated_payload["ships"][0]["validated"] = 0
    unvalidated = receiver_monitor.match_ais_callsign("PC4621", payload=unvalidated_payload)
    require(unvalidated["status"] == "not_validated" and not unvalidated["matched"], "unvalidated AIS identity fails closed")

    invalid_payload = deepcopy(live)
    invalid_payload["ships"][0]["lat"] = 91
    invalid = receiver_monitor.match_ais_callsign("PC4621", payload=invalid_payload)
    require(invalid["status"] == "invalid_position" and not invalid["matched"], "invalid AIS position fails closed")

    blank = receiver_monitor.match_ais_callsign(" ", payload=live)
    require(blank["status"] == "no_callsign" and not blank["matched"], "blank ATIS identity does not query a vessel")

    snapshot = traffic_voice.get_snapshot(
        service_reader=lambda service: {"service": service, "active": False, "state": "inactive"},
        audio_reader=lambda: {"ok": True, "available": False, "stream_state": "WAITING"},
        atis_reader=lambda: {"latest": {"fresh": True, "callsign": "PC4621"}},
        ais_matcher=lambda callsign: receiver_monitor.match_ais_callsign(callsign, payload=live),
    )
    require(snapshot["ais_match"]["mmsi"] == "244670658", "Traffic Voice API exposes the exact AIS match")
    require(
        snapshot["possible_speaker"] == "MI-DESEO · PC4621 · AIS MATCHED",
        "Possible speaker renders the verified vessel and call sign",
    )


def main() -> int:
    validate_source_contract()
    validate_matching()
    print("VALIDATION PASS: SDRCC v0.55.0e exact ATIS-to-AIS correlation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, ValueError) as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        raise SystemExit(1)
