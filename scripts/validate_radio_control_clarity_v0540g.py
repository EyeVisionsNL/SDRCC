#!/usr/bin/env python3
"""Deterministic validation for SDRCC v0.54.0g Radio Control Clarity."""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import sys

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import iss_voice  # noqa: E402
from core.iss_voice_squelch import RfPowerSquelch  # noqa: E402


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    html = read("dashboard/templates/index.html")
    radio_js = read("dashboard/static/js/radio.js")
    radio_css = read("dashboard/static/css/radio.css")
    runtime_js = read("dashboard/static/js/runtime_diagnostics.js")
    app_source = read("dashboard/app.py")
    config_source = read("core/iss_voice.py")
    squelch_source = read("core/iss_voice_squelch.py")
    offline_source = read("core/iss_voice_audio.py")
    live_source = read("core/iss_voice_audio_monitor.py")
    shared_channel_source = read("core/iss_voice_channel.py")
    executor_source = read("core/iss_voice_executor.py")
    controlled_source = read("core/controlled_iq_capture.py")

    parser = IdCollector()
    parser.feed(html)
    duplicates = [value for value, count in Counter(parser.ids).items() if count > 1]
    check(not duplicates, "Radio Control introduces no duplicate element IDs")

    radio_start = html.index('<section class="tab-page" id="tab-radio">')
    radio_view_start = html.index('<section class="tab-page" id="tab-radio-view">')
    radio_html = html[radio_start:radio_view_start]
    retained = (
        "Receiver Monitor",
        "Receiver Runtime Diagnostics",
        "Receiver Assignments",
        "Weather / METEOR Settings",
        "ISS Voice Settings",
    )
    removed = ("SDR Status", "Mission Monitor", "Live RF Console")
    check(all(label in radio_html for label in retained), "five approved Radio Control sections are present")
    check(all(label not in radio_html for label in removed), "three duplicate Radio Control sections are removed")
    check("mission_monitor.js" not in html and "mission_monitor.css" not in html, "removed Mission Monitor assets are no longer loaded")
    check('id="iss-voice-settings-form"' in radio_html, "ISS Voice settings form is present")
    check('id="iss-voice-squelch-enabled"' in radio_html, "ISS squelch control is present")
    check('id="iss-voice-squelch-threshold"' in radio_html, "ISS squelch threshold control is present")
    check("browser volume remains in Mission Operations" in radio_html, "ISS card distinguishes squelch from browser volume")

    check("radio-page-v0540g" in radio_css and "radio-panel-v0540g" in radio_css, "Queue-style Radio layout is scoped")
    check(all(color in radio_css for color in ("#22c55e", "#38bdf8", "#f59e0b", "#ef4444", "#8b5cf6")), "Queue status color vocabulary is retained")
    check("radio-settings-grid-v0540g" in radio_css, "Weather and ISS settings use an equal responsive grid")

    check('/api/receiver-monitor' in radio_js, "Receiver Monitor keeps its existing observer endpoint")
    check('/api/receiver-assignments' in radio_js, "Receiver Assignments keeps the existing authority endpoint")
    check('/api/weather-rf' in radio_js, "Weather settings keep the existing endpoint")
    check('/api/iss-voice/settings' in radio_js, "ISS Voice settings use one bounded endpoint")
    check('/api/live-rf' not in radio_js, "Radio Control no longer polls duplicate Live RF presentation")
    check('sdrcc:mission-queue-updated' not in radio_js, "removed SDR Status no longer duplicates Mission Queue projection")
    check("iss_voice" in runtime_js and "ISS Voice" in runtime_js, "Runtime Diagnostics labels ISS Voice explicitly")

    check('@app.route("/api/iss-voice/settings", methods=["GET", "POST"])' in app_source, "ISS settings endpoint supports read and write")
    check('"iss_voice_settings": iss_voice.get_settings()' in app_source, "status API projects ISS settings without a second source")
    check("ISS Voice settings are locked during an active mission" in app_source, "ISS settings writes are blocked during missions")
    check("systemctl" not in config_source + squelch_source, "ISS settings and squelch add no service authority")
    check("receiver_manager" not in squelch_source and "subprocess" not in squelch_source, "squelch owns no receiver or process lifecycle")
    legacy_squelch = "RfPowerSquelch" in offline_source and "RfPowerSquelch" in live_source
    shared_squelch = (
        "NfmChannelDecoder" in offline_source
        and "NfmChannelDecoder" in live_source
        and "RfPowerSquelch" in shared_channel_source
    )
    check(legacy_squelch or shared_squelch, "one squelch helper serves final and live audio")
    check(
        "squelch.process(complex_iq, audio)" in offline_source
        or ("NfmChannelDecoder" in offline_source and "self.squelch.process(channel_iq, audio)" in shared_channel_source),
        "final WAV applies RF-power squelch",
    )
    check(
        "self.squelch.process(iq, audio)" in live_source
        or ("NfmChannelDecoder" in live_source and "self.squelch.process(channel_iq, audio)" in shared_channel_source),
        "live WAV applies RF-power squelch",
    )
    check("iss_voice.capture_gain_db(cfg)" in executor_source, "automatic ISS missions honor managed tuner gain")
    check("iss_voice.capture_gain_db(config)" in controlled_source, "controlled ISS captures honor managed tuner gain")

    validation = iss_voice.validate_config()
    check(validation["ok"], "existing ISS Voice configuration remains valid without new keys")
    compatibility_config = dict(validation["config"])
    for field in ("gain_mode", "gain_db", "squelch_enabled", "squelch_threshold_dbfs"):
        compatibility_config.pop(field, None)
    compatibility_defaults = iss_voice.get_settings(compatibility_config)
    check(
        compatibility_defaults["squelch_enabled"] is False,
        "squelch is compatibility-safe and disabled by default when unset",
    )

    auto_config = dict(validation["config"])
    auto_config["gain_mode"] = "auto"
    check(
        iss_voice.capture_gain_db(auto_config) is None,
        "automatic gain omits the rtl_sdr manual-gain argument",
    )

    manual_config = dict(validation["config"])
    manual_config["gain_mode"] = "manual"
    manual_config["gain_db"] = 37.2
    check(
        iss_voice.capture_gain_db(manual_config) == 37.2,
        "manual gain retains the configured rtl_sdr gain argument",
    )

    original_config_file = iss_voice.CONFIG_FILE
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_config = Path(temporary_directory) / "iss_voice.yaml"
            temporary_config.write_text(original_config_file.read_text(encoding="utf-8"), encoding="utf-8")
            iss_voice.CONFIG_FILE = temporary_config
            saved = iss_voice.set_settings({
                "gain_mode": "manual",
                "gain_db": 37.2,
                "squelch_enabled": True,
                "squelch_threshold_dbfs": -39,
            })
            document = yaml.safe_load(temporary_config.read_text(encoding="utf-8"))
            check(saved["gain_mode"] == "manual" and iss_voice.capture_gain_db(document["iss_voice"]) == 37.2, "manual ISS tuner gain is validated and persisted")
            check(saved["squelch_enabled"] is True and saved["squelch_threshold_dbfs"] == -39, "ISS squelch settings are persisted")
            check(document["iss_voice"]["downlink_frequency_hz"] == 437800000, "ISS settings write preserves unrelated mission configuration")
            try:
                iss_voice.set_settings({"squelch_threshold_dbfs": -80})
                invalid_rejected = False
            except ValueError:
                invalid_rejected = True
            check(invalid_rejected, "out-of-range squelch thresholds are rejected")
    finally:
        iss_voice.CONFIG_FILE = original_config_file

    audio = np.ones(4800, dtype=np.float32)
    quiet_iq = np.full(24000, 0.001 + 0.001j, dtype=np.complex64)
    strong_iq = np.full(24000, 0.7 + 0.7j, dtype=np.complex64)
    quiet_gate = RfPowerSquelch(
        rf_sample_rate_hz=240000, audio_sample_rate_hz=48000,
        enabled=True, threshold_dbfs=-42,
    )
    strong_gate = RfPowerSquelch(
        rf_sample_rate_hz=240000, audio_sample_rate_hz=48000,
        enabled=True, threshold_dbfs=-42,
    )
    bypass = RfPowerSquelch(
        rf_sample_rate_hz=240000, audio_sample_rate_hz=48000,
        enabled=False, threshold_dbfs=-42,
    )
    check(float(np.max(np.abs(quiet_gate.process(quiet_iq, audio)))) < 1e-5, "squelch closes below the RF threshold")
    check(float(np.max(np.abs(strong_gate.process(strong_iq, audio)))) > 0.9, "squelch opens above the RF threshold")
    check(np.array_equal(bypass.process(quiet_iq, audio), audio), "disabled squelch is bit-for-bit transparent to float audio")

    check(
        "v=0.54.0g" in html
        and any(version in html for version in ('radio.js?v=0.54.0g', 'radio.js?v=0.54.0h-r2')),
        "Radio assets use an approved v0.54.0g/v0.54.0h cache bust",
    )
    print("VALIDATION PASS: SDRCC v0.54.0g Radio Control Clarity and ISS Voice Squelch")


if __name__ == "__main__":
    main()
