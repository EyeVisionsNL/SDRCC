#!/usr/bin/env python3
"""Validate Marine Voice's four most recent squelch-gated replays."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import io
import importlib.util
import json
import os
import struct
import sys
import wave


ROOT = Path(os.environ.get("SDRCC_ROOT") or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT))


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def test_configured_outputs() -> None:
    from core import config, traffic_voice
    from core import traffic_voice_audio

    check(
        traffic_voice.MARINE_RECORDING_PORT_OFFSET
        == traffic_voice_audio.RECORDING_UDP_PORT_OFFSET,
        "backend and recorder reserve the same adjacent UDP port",
    )

    receivers = [
        {"id": "sdr1", "serial": "test-serial-1"},
        {"id": "sdr2", "serial": "test-serial-2"},
    ]
    assignments = {"ais": "sdr1", "adsb": "sdr2", "traffic_voice": "sdr2"}

    def resolve(value):
        if value in ("sdr1", "receiver01"):
            return "sdr1"
        if value in ("sdr2", "receiver02"):
            return "sdr2"
        return None

    def render(mode: str, *, open_squelch: bool = False) -> str:
        payload = deepcopy(config.load_traffic_voice())
        settings = payload["traffic_voice"]
        settings["selected_mode"] = mode
        settings["backend"]["audio_port"] = 49555
        settings["backend"]["open_squelch"] = open_squelch
        marine = settings["modes"]["marine_ais"]
        marine["tuning_mode"] = "scan"
        for channel in marine["channels"]:
            channel["scan_enabled"] = True
        settings["modes"]["airband_adsb"]["tuning_mode"] = "fixed"
        current_assignments = dict(assignments)
        current_assignments["traffic_voice"] = "sdr1" if mode == "airband_adsb" else "sdr2"
        with (
            patch.object(config, "get_receiver_assignments", return_value=current_assignments),
            patch.object(traffic_voice.receiver_registry, "resolve_id", side_effect=resolve),
            patch.object(traffic_voice.receiver_registry, "get_receivers", return_value=receivers),
            patch.object(traffic_voice.receiver_registry, "get_receiver", side_effect=lambda value: next((item for item in receivers if item["id"] == resolve(value)), None)),
        ):
            return traffic_voice.render_rtlsdr_airband_config(payload=payload)

    marine = render("marine_ais")
    check('dest_port = 49555;' in marine and 'continuous = true;' in marine,
          "Marine live audio keeps its existing continuous UDP output")
    check('dest_port = 49556;' in marine and 'continuous = false;' in marine,
          "Marine adds a separate squelch-gated recording output")

    airband = render("airband_adsb")
    check('dest_port = 49556;' not in airband,
          "Airband does not send recordings to the Marine capture port")
    open_squelch = render("marine_ais", open_squelch=True)
    check('dest_port = 49556;' not in open_squelch,
          "Open-squelch test audio is excluded from automatic replays")

    invalid = deepcopy(config.load_traffic_voice())
    invalid["traffic_voice"]["backend"]["audio_port"] = 65535
    check(not traffic_voice.validate_configuration(invalid)["ok"],
          "Live UDP port validation reserves the adjacent recording port")


def test_channel_metadata() -> None:
    from core import config, traffic_voice_audio as audio

    document = config.get_traffic_voice_config()
    marine = document["modes"]["marine_ais"]
    channel = marine["channels"][0]
    marine["tuning_mode"] = "fixed"
    marine["selected_channel_id"] = channel["id"]
    with patch.object(config, "get_traffic_voice_config", return_value=document):
        fixed = audio._marine_channel_metadata(2000.0)
    check(fixed["channel"] == channel["label"],
          "Fixed-channel recordings retain their configured channel label")
    check(fixed["frequency_mhz"] == round(float(channel["frequency_mhz"]), 6),
          "Fixed-channel recordings retain their configured frequency")

    marine["tuning_mode"] = "scan"
    marine["channels"] = [{"label": "VHF16 - Distress", "frequency_mhz": 156.8}]
    log_line = "2000.100 host rtl_airband[123]: Activity on 156.800 MHz (VHF16 - Distress)\n"
    with (
        patch.object(config, "get_traffic_voice_config", return_value=document),
        patch.object(audio.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=log_line)),
    ):
        scanned = audio._marine_channel_metadata(2000.2)
    check(scanned == {"channel": "VHF16 - Distress", "frequency_mhz": 156.8},
          "Scan-mode recordings use the matching RTLSDR-Airband activity event")


def test_recording_store() -> None:
    from core.traffic_voice_audio import MarineRecordingStore

    store = MarineRecordingStore(
        sample_rate=16000,
        pre_roll_seconds=0.1,
        post_roll_seconds=0.1,
        gap_seconds=0.2,
        max_seconds=1.0,
    )
    quiet = struct.pack("<h", 0) * 800
    speech = struct.pack("<h", 12000) * 800
    store.observe_live_chunk(quiet, 10.0)
    store.observe_live_chunk(quiet, 10.05)
    store.observe_gated_chunk(speech, 10.1, {"channel": "VHF16", "frequency_mhz": 156.8})
    store.observe_live_chunk(quiet, 10.15)
    store.observe_gated_chunk(speech, 10.2, None)
    store.observe_live_chunk(quiet, 10.25)
    active = store.list_recordings()
    check(len(active) == 1 and not active[0]["complete"] and not active[0]["play_url"],
          "An in-progress transmission is shown but cannot be replayed yet")
    check(store.finish_if_idle(10.5), "Squelch silence completes the current recording")
    recordings = store.list_recordings()
    check(len(recordings) == 1 and recordings[0]["complete"],
          "Completed transmission appears in the replay list")
    check(recordings[0]["channel"] == "VHF16" and recordings[0]["frequency_mhz"] == 156.8,
          "Recording metadata preserves its channel and frequency")

    wav_bytes = store.get_wav(recordings[0]["id"])
    check(wav_bytes is not None and wav_bytes[:4] == b"RIFF",
          "Completed replay is served as a finite WAV file")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        check(wav.getnchannels() == 1 and wav.getsampwidth() == 2 and wav.getframerate() == 16000,
              "Replay WAV is mono PCM16 at the configured sample rate")
        check(wav.getnframes() > 160,
              "Replay includes its captured speech and short audio margins")

    latest = None
    for index in range(5):
        started = 20.0 + index * 2
        metadata = {"channel": f"CH{index}", "frequency_mhz": 156.0 + index / 10}
        store.observe_gated_chunk(speech, started, metadata)
        store.observe_gated_chunk(speech, started + 0.05, None)
        store.finish_if_idle(started + 0.3)
        latest = store.list_recordings()
    check(len(latest) == 4 and latest[0]["channel"] == "CH4",
          "Only the four latest completed Marine transmissions are retained")
    check(store.get_wav(recordings[0]["id"]) is None,
          "The oldest WAV is removed when it falls outside the four-item limit")

    bounded = MarineRecordingStore(
        sample_rate=16000,
        pre_roll_seconds=0,
        post_roll_seconds=0,
        gap_seconds=0.2,
        max_seconds=0.1,
    )
    bounded.observe_gated_chunk(speech * 4, 40.0, {"channel": "VHF16"})
    bounded.finish_if_idle(40.3)
    bounded_recordings = bounded.list_recordings()
    check(
        len(bounded_recordings) == 1
        and bounded_recordings[0]["duration_seconds"] <= 0.1,
        "A single transmission cannot exceed its configured memory bound",
    )


def test_dashboard_endpoint_and_assets() -> None:
    app_source = (ROOT / "dashboard/app.py").read_text(encoding="utf-8")
    if importlib.util.find_spec("flask"):
        from dashboard import app as dashboard_app

        payload = b"RIFF" + (b"0" * 40)
        valid_id = "a" * 32
        with patch.object(dashboard_app.traffic_voice_audio, "get_recording_wav", return_value=payload):
            response = dashboard_app.app.test_client().get(
                f"/api/traffic-voice/recordings/{valid_id}.wav"
            )
        check(
            response.status_code == 200
            and response.mimetype == "audio/wav"
            and response.data == payload
            and "no-store" in response.headers.get("Cache-Control", ""),
            "Replay endpoint serves the requested no-store WAV response",
        )
        with patch.object(dashboard_app.traffic_voice_audio, "get_recording_wav", return_value=None):
            missing = dashboard_app.app.test_client().get(
                f"/api/traffic-voice/recordings/{valid_id}.wav"
            )
        check(missing.status_code == 404, "Expired or invalid recording IDs return 404")
    else:
        check(
            '@app.route("/api/traffic-voice/recordings/<recording_id>.wav", methods=["GET"])' in app_source
            and "traffic_voice_audio.get_recording_wav(recording_id)" in app_source,
            "Replay WAV endpoint is registered and calls the bounded recording store",
        )

    html = (ROOT / "dashboard/templates/index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard/static/js/traffic_voice.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/static/css/traffic_voice.css").read_text(encoding="utf-8")
    check('id="traffic-voice-recordings"' in html and 'id="traffic-voice-replay-audio"' in html,
          "Traffic Voice has a dedicated Marine replay list and player")
    check("stopRecordingReplay(true)" in js and "startAudio()" in js,
          "Replay pauses live listening and reconnects it afterward")
    check("traffic-voice-recording-play" in css and "traffic-voice-recordings[hidden]" in css,
          "Replay controls are styled and hidden outside Marine mode")
    check("traffic_voice.js?v=0.63.6" in html and "traffic_voice.css?v=0.63.6" in html,
          "Marine replay assets use the release cache-busting version")


if __name__ == "__main__":
    test_configured_outputs()
    test_channel_metadata()
    test_recording_store()
    test_dashboard_endpoint_and_assets()
    print("PASS: Marine replay v0.63.6 validation completed")
