#!/usr/bin/env python3
"""Deterministic RF-chain validation for SDRCC v0.54.0h."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
import json
import shutil
import sys
import tempfile

import numpy as np
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import iss_voice, satdump, weather_planning  # noqa: E402
from core.iss_voice_channel import NfmChannelDecoder  # noqa: E402
from scripts.migrate_rf_profiles_v0540h import migrate  # noqa: E402


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        del tag
        for key, value in attrs:
            if key == "id" and value:
                self.ids.append(value)


def synthetic_iq(seconds: float = 2.0) -> tuple[bytes, callable]:
    rf_rate = 240_000
    count = int(rf_rate * seconds)
    time_axis = np.arange(count, dtype=np.float64) / rf_rate
    offsets = 13_000.0 - 26_000.0 * time_axis / seconds
    message = np.sin(2.0 * np.pi * 1_000.0 * time_axis)
    wanted_phase = np.cumsum(2.0 * np.pi * (offsets + 3_000.0 * message) / rf_rate)
    wanted = 0.58 * np.exp(1j * wanted_phase)
    interferer = 0.38 * np.exp(1j * 2.0 * np.pi * 60_000.0 * time_axis)
    rng = np.random.default_rng(540)
    noise = 0.025 * (rng.normal(size=count) + 1j * rng.normal(size=count))
    iq = wanted + interferer + noise
    iq /= max(1.0, float(np.max(np.maximum(np.abs(iq.real), np.abs(iq.imag)))))
    raw = np.empty(count * 2, dtype=np.uint8)
    raw[0::2] = np.clip(iq.real * 127.5 + 127.5, 0, 255).astype(np.uint8)
    raw[1::2] = np.clip(iq.imag * 127.5 + 127.5, 0, 255).astype(np.uint8)
    return raw.tobytes(), lambda epoch: 13_000.0 - 26_000.0 * epoch / seconds


def tone_quality(audio: np.ndarray, sample_rate: int = 48_000) -> float:
    audio = audio[int(0.2 * sample_rate):]
    windowed = audio * np.hanning(audio.size)
    spectrum = np.abs(np.fft.rfft(windowed))
    frequencies = np.fft.rfftfreq(audio.size, 1.0 / sample_rate)
    tone = float(np.max(spectrum[(frequencies > 950) & (frequencies < 1050)]))
    floor_band = ((frequencies > 200) & (frequencies < 800)) | ((frequencies > 1200) & (frequencies < 5000))
    floor = float(np.sqrt(np.mean(np.square(spectrum[floor_band]))))
    return 20.0 * np.log10(max(tone, 1e-12) / max(floor, 1e-12))


def main() -> int:
    profiles = weather_planning.get_config()
    for profile_id in ("meteor_m2_3", "meteor_m2_4"):
        profile = profiles["profiles"][profile_id]
        check(profile["frequency_choice"] in {"primary", "secondary", "custom"},
              f"{profile['label']} exposes a valid operator frequency choice")
        check(136_000_000 <= profile["frequency_hz"] <= 138_000_000,
              f"{profile['label']} exposes the stored downlink frequency")

    original_satellites_file = weather_planning.SATELLITES_FILE
    original_iss_file = weather_planning.ISS_CONFIG_FILE
    original_station_file = weather_planning.STATION_FILE
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        config_file = temporary / "satellites.yaml"
        iss_file = temporary / "iss_voice.yaml"
        station_file = temporary / "station.yaml"
        config_file.write_text(original_satellites_file.read_text(encoding="utf-8"), encoding="utf-8")
        iss_file.write_text(original_iss_file.read_text(encoding="utf-8"), encoding="utf-8")
        station_file.write_text(original_station_file.read_text(encoding="utf-8"), encoding="utf-8")
        original_document = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        original_document["satellites"]["METEOR-M2 3"]["frequency"] = 137_100_000
        original_document["satellites"]["METEOR-M2 4"]["frequency"] = 137_900_000
        original_document["satellites"]["METEOR-M2 3"]["min_elevation"] = 31.25
        original_document["custom_preserved"] = {"operator": True}
        config_file.write_text(yaml.safe_dump(original_document, sort_keys=False), encoding="utf-8")
        changed, _values, reason = migrate(config_file)
        migrated = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        check(changed and "repaired" in reason and migrated["satellites"]["METEOR-M2 3"]["frequency"] == 137_900_000,
              "migration repairs only the v0.54.0h-r1 forced M2-3 default")
        check(migrated["satellites"]["METEOR-M2 3"]["min_elevation"] == 31.25 and migrated["custom_preserved"]["operator"],
              "migration preserves planning and unrelated operator settings")
        migrated["satellites"]["METEOR-M2 3"]["frequency"] = 137_550_000
        config_file.write_text(yaml.safe_dump(migrated, sort_keys=False), encoding="utf-8")
        changed, values, reason = migrate(config_file)
        check(not changed and "preserved" in reason and values["METEOR-M2 3"] == 137_550_000,
              "migration preserves an existing custom operator frequency")

        weather_planning.SATELLITES_FILE = config_file
        weather_planning.ISS_CONFIG_FILE = iss_file
        weather_planning.STATION_FILE = station_file
        try:
            current = weather_planning.get_config()["profiles"]
            requested = {profile_id: dict(profile) for profile_id, profile in current.items()}
            requested["meteor_m2_3"].update({"frequency_choice": "primary", "frequency_hz": 137_900_000})
            requested["meteor_m2_4"].update({"frequency_choice": "secondary", "frequency_hz": 137_100_000})
            saved = weather_planning.set_config({"profiles": requested})
            check(saved["profiles"]["meteor_m2_3"]["frequency_hz"] == 137_900_000 and
                  saved["profiles"]["meteor_m2_4"]["frequency_hz"] == 137_100_000,
                  "Mission Planner stores independent Primary and Secondary choices")

            requested = {profile_id: dict(profile) for profile_id, profile in saved["profiles"].items()}
            requested["meteor_m2_3"].update({"frequency_choice": "custom", "frequency_hz": 137_550_000})
            custom = weather_planning.set_config({"profiles": requested})
            check(custom["profiles"]["meteor_m2_3"]["frequency_choice"] == "custom" and
                  custom["profiles"]["meteor_m2_3"]["frequency_hz"] == 137_550_000,
                  "Mission Planner stores a bounded Custom frequency")
            preserved = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            check(preserved["custom_preserved"]["operator"], "Mission Planner write preserves unrelated YAML")
        finally:
            weather_planning.SATELLITES_FILE = original_satellites_file
            weather_planning.ISS_CONFIG_FILE = original_iss_file
            weather_planning.STATION_FILE = original_station_file

    original_allowed = satdump.check_recording_allowed
    original_device = satdump.get_assigned_device
    original_rf = satdump.config_core.get_weather_rf_config
    try:
        satdump.check_recording_allowed = lambda: (True, "OK")
        satdump.get_assigned_device = lambda role: {"id": "sdr1", "serial": "05419737", "number": 1}
        satdump.config_core.get_weather_rf_config = lambda: {
            "lna_agc": False, "gain_mode": "manual", "gain_db": 28.0,
            "dc_block": True, "iq_swap": False, "fill_missing": True, "rs_usecheck": True,
        }
        start = datetime.now(timezone.utc) + timedelta(minutes=5)
        planned = {
            "name": "METEOR-M2 3", "frequency": 137_550_000,
            "sample_rate": 1_000_000, "pipeline": "meteor_m2-x_lrpt", "mode": "LRPT",
            "start": start, "maximum": start + timedelta(minutes=5), "end": start + timedelta(minutes=10),
        }
        command = satdump.build_record_command(planned)["command"]
        check(command[command.index("--frequency") + 1] == "137550000",
              "custom planned frequency reaches the SatDump command unchanged")
        check(command[command.index("--source_id") + 1] == "05419737",
              "SatDump still uses Receiver Manager's assigned serial")
    finally:
        satdump.check_recording_allowed = original_allowed
        satdump.get_assigned_device = original_device
        satdump.config_core.get_weather_rf_config = original_rf

    validation = iss_voice.validate_config()
    check(validation["ok"], "ISS configuration validates the implemented Doppler and filter chain")
    config = validation["config"]
    raw, provider = synthetic_iq()
    decoder = NfmChannelDecoder(
        rf_sample_rate_hz=240_000, audio_sample_rate_hz=48_000,
        channel_bandwidth_hz=25_000, deemphasis_us=75.0,
        capture_start_epoch=0.0, doppler_offset_provider=provider,
    )
    audio_parts = []
    for offset in range(0, len(raw), 48_000):
        audio_parts.append(decoder.process_float(raw[offset:offset + 48_000]))
    audio = np.concatenate(audio_parts)
    processing = decoder.status()
    check(tone_quality(audio) > 35.0, "dynamic ±13 kHz Doppler IQ decodes a clean 1 kHz NFM tone")
    check(processing["doppler_min_hz"] < -12_900 and processing["doppler_max_hz"] > 12_900,
          "decoder applied the full dynamic Doppler trajectory")
    check(processing["channel_filter_enabled"] and processing["channel_filter_taps"] >= 65,
          "25 kHz channel filter is real and active")

    mission = "validator_v0540h"
    directory = ROOT / "data" / "recordings" / "iss_voice" / mission
    directory.mkdir(parents=True, exist_ok=False)
    try:
        (directory / "recording.iq").write_bytes(raw)
        (directory / "capture.json").write_text(json.dumps({"capture_started_at": "1970-01-01T00:00:00+00:00"}), encoding="utf-8")
        from core import iss_voice_audio
        result = iss_voice_audio.demodulate_mission(
            mission, config, doppler_offset_provider=provider,
            doppler_metadata={"source": "validator"},
        )
        check(result["doppler_correction_enabled"] and result["channel_filter_enabled"],
              "offline WAV reports proven Doppler correction and channel filtering")
        check(result["audio_duration_seconds"] > 1.99 and Path(result["wav_path"]).stat().st_size > 100_000,
              "offline shared decoder writes bounded PCM WAV audio")
    finally:
        shutil.rmtree(directory, ignore_errors=True)

    offline_source = (ROOT / "core" / "iss_voice_audio.py").read_text(encoding="utf-8")
    live_source = (ROOT / "core" / "iss_voice_audio_monitor.py").read_text(encoding="utf-8")
    check("from core.iss_voice_channel import NfmChannelDecoder" in offline_source and
          "from core.iss_voice_channel import NfmChannelDecoder" in live_source,
          "live and archived audio use one shared DSP implementation")
    check("_LiveNfmDemodulator" not in live_source, "duplicate live FM discriminator was removed")

    html = (ROOT / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    app_source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    parser = IdCollector(); parser.feed(html)
    check(len(parser.ids) == len(set(parser.ids)), "Radio Control contains no duplicate element IDs")
    planner_source = (ROOT / "dashboard" / "static" / "js" / "mission_planner.js").read_text(encoding="utf-8")
    check("weather-satellite-profiles-form" not in html and "/api/weather-satellite-profiles" not in app_source,
          "Radio Control no longer duplicates satellite frequency planning")
    check(all(value in html for value in (
        "Primary · 137.900 MHz", "Secondary · 137.100 MHz", "Custom frequency"
    )) and "data-frequency-choice" in planner_source and "data-frequency-custom" in planner_source,
          "Mission Planner exposes Primary, Secondary and Custom per METEOR satellite")
    check("Automatic · TLE" in html and "25 kHz · active" in html,
          "ISS processing state is operator-visible")
    planner_cache_versions = ("0.54.0h-r2", "0.54.0j-r1")
    check(any(
        f"mission_planner.js?v={version}" in html
        and f"mission_planner.css?v={version}" in html
        for version in planner_cache_versions
    ), "Mission Planner assets use an approved v0.54.0h/v0.54.0j cache bust")
    print("VALIDATION PASS: SDRCC v0.54.0h-r2 RF Receive Chain Integrity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
