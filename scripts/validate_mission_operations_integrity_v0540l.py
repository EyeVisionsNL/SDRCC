#!/usr/bin/env python3
"""Validate Mission Operations integrity and visual clarity for SDRCC v0.54.0l."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_static_contract() -> None:
    template = read("dashboard/templates/index.html")
    javascript = read("dashboard/static/js/mission_recordings.js")
    stylesheet = read("dashboard/static/css/mission_recordings.css")
    capture_javascript = read("dashboard/static/js/capture.js")
    dashboard_module = read("dashboard/static/js/dashboard.js")
    dashboard_loader = read("dashboard/static/dashboard.js")
    backend = read("core/mission_operations.py")
    app = read("dashboard/app.py")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    required_ids = {
        "mission-operations-idle",
        "mission-operations-console",
        "mission-operations-preview-card",
        "mission-operations-audio-monitor",
        "mission-operations-audio-listeners",
        "mission-operations-recorder-group",
        "mission-operations-decoder-group",
        "mission-recordings-list",
        "mission-recordings-audio",
    }
    check(required_ids.issubset(set(ids)), "live, audio and result presentation hooks are present")
    check(
        any(version in template for version in ('mission_recordings.css?v=0.54.0l-r2', 'mission_recordings.css?v=0.54.0s-r1'))
        and 'mission_recordings.js?v=0.54.0l-r2' in template
        and any(version in template for version in ('/static/dashboard.js?v=0.54.0l-r1', '/static/dashboard.js?v=0.54.0m-r1', '/static/dashboard.js?v=0.54.0n-r1', '/static/dashboard.js?v=0.54.0q-r1', '/static/dashboard.js?v=0.54.0q-r3'))
        and any(version in dashboard_loader for version in ('/static/js/dashboard.js?v=0.54.0l-r1', '/static/js/dashboard.js?v=0.54.0m-r1', '/static/js/dashboard.js?v=0.54.0n-r1', '/static/js/dashboard.js?v=0.54.0q-r1', '/static/js/dashboard.js?v=0.54.0q-r3'))
        and './capture.js?v=0.54.0l-r1' in dashboard_module,
        "Mission Operations and compatibility assets use the v0.54.0l cache chain",
    )
    check(
        "const receiverLabel = (value) =>" in javascript
        and "['RECEIVER01', 'SDR1', 'RX01']" in javascript
        and "['RECEIVER02', 'SDR2', 'RX02']" in javascript
        and "receiverLabel(rfConsole.receiver || summary.receiver || summary.receiver_id)" in javascript
        and "receiverLabel(mission.receiver || mission.receiver_id)" in javascript,
        "Mission Operations normalizes canonical, alias and numbered receiver identities to SDR1/SDR2",
    )
    check(
        ".mission-operations-status-card::after" in stylesheet
        and ".mission-operations-summary-grid > div:nth-child(2)" in stylesheet
        and ".mission-operations-summary-grid > div:nth-child(5).is-good" in stylesheet
        and ".mission-operations-state.is-meteor-4" in stylesheet
        and "color-mix(in srgb, var(--recording-accent) 14%" in stylesheet,
        "Mission Operations completes the approved satellite and status colour hierarchy",
    )

    check("capture_live.js" not in template, "duplicate one-second capture updater is no longer loaded")
    check("Weather image pipeline" not in template, "duplicate Weather pipeline footer is removed")
    check(">Clients<" not in template, "ambiguous visible Clients label is removed")
    check("Audio listeners" in template, "ISS listener count has an explicit audio-only label")
    check(
        'updateCaptureBlock(capture, "-images")' not in capture_javascript,
        "generic dashboard capture refresh cannot overwrite Selected Result",
    )
    check(
        "operationsVisible" in javascript
        and "window.setInterval(refreshLive, 3000)" in javascript
        and "window.setInterval(refreshResults, 15000)" in javascript,
        "existing refresh cadences run only while Mission Operations is visible",
    )
    check(
        "state.recordings.find(row => row.relative_path === selectedPath)" in javascript
        and "element.dataset.path === row.relative_path" in javascript,
        "selected result and row highlight survive inventory refresh",
    )
    check(
        "pathParts.includes(outputName)" in javascript
        and "mission.mission_id || row.mission_id" in javascript,
        "nested Weather product folders display the owning mission ID",
    )
    check("'en-GB'" in javascript and "'nl-NL'" not in javascript, "Mission Operations dates use the English UI locale")
    check(
        all(color in stylesheet for color in ("#38bdf8", "#22c55e", "#f59e0b", "#ef4444", "#a78bfa", "#fbbf24")),
        "approved Mission Planner and Analytics palette is reused",
    )
    check(
        all(selector in stylesheet for selector in (
            ".mission-operations-status-card.is-meteor-3",
            ".mission-operations-status-card.is-meteor-4",
            ".mission-operations-status-card.is-iss",
            ".recording-item.selected",
        )),
        "satellite identity and selected-result theme states are styled",
    )

    check("last_result =" not in backend, "historical last_result is not promoted into the live summary")
    check("metrics_available" in backend, "unavailable Weather capture byte metrics are explicit")
    check(
        'audio_monitor.get("stream_state")\n                if is_iss' not in backend,
        "ISS recorder lifecycle is not sourced from audio stream state",
    )
    check("subprocess" not in backend and "systemctl" not in backend, "Mission Operations backend remains observer-only")
    check(app.count('@app.route("/api/mission-operations")') == 1, "one existing Mission Operations snapshot endpoint remains")
    check(app.count('@app.route("/api/iss-voice/audio-stream"') == 1, "one existing ISS audio stream endpoint remains")
    check(app.count('@app.route("/api/mission-recordings"') == 1, "one existing Mission Recordings endpoint remains")


def validate_snapshot_contract() -> None:
    from core import mission_operations

    receiver_idle = {
        "reservation": None,
        "configured_receiver": {"number": "SDR1", "serial": "05419737"},
        "receivers": {
            "sdr2": {
                "device": {
                    "id": "sdr2",
                    "runtime_id": "sdr2",
                    "registry_id": "receiver02",
                    "canonical_id": "receiver02",
                    "number": "RX02",
                    "serial": "24006572",
                },
                "reservation": {"status": "ACTIVE"},
            }
        },
    }
    stale_mission = {
        "active_job": None,
        "last_result": {
            "mission_id": "iss_voice_old",
            "mission_type": "iss_voice",
            "satellite": "ISS (ZARYA)",
            "frequency": 437_800_000,
            "pipeline": "wideband_iq_offline_fm",
        },
    }
    stale_rf = {
        "active": False,
        "state": "COMPLETE",
        "satellite": "METEOR-M2 3",
        "frequency_hz": 137_100_000,
        "pipeline": "meteor_m2-x_lrpt",
    }
    summary = mission_operations._mission_summary(stale_mission, stale_rf, receiver_idle)
    check(summary is None, "idle live summary rejects stale ISS and METEOR result data")

    idle_console = mission_operations._console_snapshot(
        None,
        stale_mission,
        stale_rf,
        receiver_idle,
        {"mode": "AUTO", "observer": {"phase": "WAIT FOR PASS"}},
        {"active": False, "phase": "FINISHED"},
        {"stream_state": "STANDBY", "active_clients": 0, "max_clients": 3},
    )
    check(idle_console["mission"]["state"] == "IDLE", "idle console reports IDLE instead of the previous mission")
    check(idle_console["rf"]["receiver"] is None, "idle console exposes no stale RF receiver")
    check(idle_console["recorder"]["type"] is None, "idle console exposes no fictitious SatDump recorder")
    check(idle_console["decoder"]["pipeline"] is None, "idle console exposes no stale decoder pipeline")

    entry = mission_operations._receiver_runtime_entry(receiver_idle, "receiver02")
    check((entry.get("device") or {}).get("number") == "RX02", "ISS receiver identity resolves through Receiver Manager")

    iss_summary = {
        "active": True,
        "mission_id": "iss_voice_now",
        "mission_type": "iss_voice",
        "plugin_id": "iss_voice",
        "satellite": "ISS (ZARYA)",
        "receiver": "RX02",
        "receiver_id": "receiver02",
        "frequency": 437_800_000,
        "sample_rate": 240_000,
        "mode": "NFM",
        "status": "RECORDING",
        "output_path": "/recordings/iss_voice_now",
        "receiver_status": "ACTIVE",
    }
    iss_console = mission_operations._console_snapshot(
        iss_summary,
        {"active_job": None},
        stale_rf,
        receiver_idle,
        {"mode": "AUTO", "observer": {"phase": "PASS ACTIVE"}},
        {"active": True, "phase": "RECORDING"},
        {"stream_state": "READY", "iq_bytes": 480_000, "observed_byte_rate": 480_000, "active_clients": 0, "max_clients": 3},
    )
    check(iss_console["recorder"]["status"] == "RECORDING", "ISS recorder state comes from the IQ capture lifecycle")
    check(iss_console["recorder"]["bytes"] == 480_000, "ISS IQ byte count remains observable")
    check(iss_console["decoder"]["applicable"] is False, "Weather decoder fields are not applicable to ISS")
    check(iss_console["runtime"]["audio_max_clients"] == 3, "audio listener capacity is projected read-only")

    weather_summary = {
        "active": True,
        "mission_id": "weather_now",
        "mission_type": "weather",
        "plugin_id": "weather",
        "satellite": "METEOR-M2 4",
        "receiver": "SDR1",
        "frequency": 137_900_000,
        "sample_rate": 1_024_000,
        "mode": "LRPT",
        "pipeline": "meteor_m2-x_lrpt",
        "status": "RECORDING",
        "frames": 12,
        "cadu_bytes": 98_304,
        "image_count": 1,
        "output_path": "/recordings/weather_now",
    }
    weather_console = mission_operations._console_snapshot(
        weather_summary,
        {"active_job": weather_summary},
        {"active": True, "state": "RECORDING"},
        receiver_idle,
        {"mode": "AUTO", "observer": {"phase": "PASS ACTIVE"}},
        {"active": False},
        {"stream_state": "STANDBY", "active_clients": 0, "max_clients": 3},
    )
    check(weather_console["recorder"]["metrics_available"] is False, "Weather does not fabricate unavailable capture bytes")
    check(weather_console["recorder"]["bytes"] is None, "Weather capture byte value is explicitly unavailable")
    check(weather_console["decoder"]["applicable"] is True, "Weather retains live decoder metrics")


def validate_audio_client_lifecycle() -> None:
    from core import iss_voice_audio_monitor as monitor

    original_root = monitor.ROOT
    original_runtime = monitor.iss_voice_runtime.get_status
    original_settings = monitor.iss_voice.get_settings
    original_config = monitor.iss_voice.get_config
    original_tracker = monitor.build_tracker

    class Tracker:
        metadata = {"doppler_source": "validator"}

        @staticmethod
        def offset_hz(*_args: Any, **_kwargs: Any) -> float:
            return 0.0

    try:
        with TemporaryDirectory(prefix="sdrcc-audio-listeners-") as temporary:
            root = Path(temporary)
            mission_id = "iss_voice_listener_test"
            mission_dir = root / mission_id
            mission_dir.mkdir(parents=True)
            (mission_dir / "recording.iq").write_bytes(b"\x00" * 120_000)
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            runtime = {
                "active": True,
                "mission_id": mission_id,
                "phase": "RECORDING",
                "receiver_id": "receiver02",
                "receiver_serial": "24006572",
                "frequency_hz": 437_800_000,
                "sample_rate_hz": 240_000,
                "capture_started_at": now,
                "started_at": now,
                "elapsed_seconds": 1.0,
                "output_directory": str(mission_dir),
            }
            monitor.ROOT = root
            monitor.iss_voice_runtime.get_status = lambda: dict(runtime)
            monitor.iss_voice.get_settings = lambda: {"squelch_enabled": False, "squelch_threshold_dbfs": -42.0}
            monitor.iss_voice.get_config = lambda: {
                "downlink_frequency_hz": 437_800_000,
                "channel_bandwidth_hz": 16_000,
                "audio_sample_rate_hz": 48_000,
                "audio_deemphasis_us": 75.0,
                "squelch_enabled": False,
                "squelch_threshold_dbfs": -42.0,
            }
            monitor.build_tracker = lambda _config: Tracker()
            with monitor._clients_lock:
                monitor._active_clients = 0
                monitor._total_clients = 0

            ready = monitor.get_status()
            check(ready["available"] and ready["stream_state"] == "READY", "compatible active ISS IQ capture exposes READY audio")
            stream = monitor.stream_wav(mission_id)
            check(monitor.get_status()["active_clients"] == 1, "opening live WAV registers one audio listener")
            check(next(stream)[:4] == b"RIFF", "live audio starts with a valid WAV header")
            stream.close()
            check(monitor.get_status()["active_clients"] == 0, "closing live WAV unregisters the audio listener")

            streams = [monitor.stream_wav(mission_id) for _ in range(monitor.MAX_CLIENTS)]
            check(monitor.get_status()["active_clients"] == monitor.MAX_CLIENTS, "configured three-listener limit is observable")
            try:
                monitor.stream_wav(mission_id)
            except RuntimeError:
                rejected = True
            else:
                rejected = False
            check(rejected, "fourth audio listener is rejected synchronously")
            for item in streams:
                item.close()
            check(monitor.get_status()["active_clients"] == 0, "all admitted listeners release cleanly")

            try:
                monitor.stream_wav("wrong-mission")
            except ValueError:
                mismatch_rejected = True
            else:
                mismatch_rejected = False
            check(mismatch_rejected, "wrong mission ID cannot open the audio stream")
            check(monitor.get_status()["active_clients"] == 0, "rejected stream does not leak a listener")
    finally:
        monitor.ROOT = original_root
        monitor.iss_voice_runtime.get_status = original_runtime
        monitor.iss_voice.get_settings = original_settings
        monitor.iss_voice.get_config = original_config
        monitor.build_tracker = original_tracker
        with monitor._clients_lock:
            monitor._active_clients = 0


def main() -> None:
    validate_static_contract()
    validate_snapshot_contract()
    validate_audio_client_lifecycle()
    print("VALIDATION PASS: SDRCC v0.54.0l-r2 Mission Operations Integrity and Theme Completion")


if __name__ == "__main__":
    main()
