#!/usr/bin/env python3
"""Hardware-free Smart Gain, Traffic Voice and managed-update validation."""

from __future__ import annotations

import hashlib
import json
import ctypes
from datetime import datetime
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import config, hf_monitor, hf_monitor_backend, iss_smart_gain, iss_voice, mission_engine, traffic_voice, update_manager, weather_smart_gain, wideband_iq_recorder  # noqa: E402
from core.mission_engine import MissionEngine, MissionJob  # noqa: E402

if importlib.util.find_spec("skyfield") is None:
    # The command-rewrite unit test does not call pass prediction; keep the
    # hardware-free validator runnable in minimal Python environments.
    sys.modules.setdefault("core.passes", types.ModuleType("core.passes"))
from core import satdump  # noqa: E402
from core.rtl_smart_gain import (  # noqa: E402
    analyze_iq_samples,
    choose_for_measurements,
    choose_smart_gain_db,
    closest_gain,
)


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print("PASS:", label)


gains = config.get_rtl_sdr_valid_gains()
check(closest_gain(gains, 12.5) == 12.5, "Smart Gain uses the 12.5 dB reference when available")
check(
    choose_smart_gain_db({"signal_dbfs": -40.0, "snr_db": 8.0}, gains) > 12.5,
    "a weak but clear channel can receive a bounded gain increase",
)
check(
    choose_smart_gain_db({"signal_dbfs": -20.0, "snr_db": 8.0}, gains) < 12.5,
    "a stronger clear channel receives less tuner gain",
)
check(
    choose_smart_gain_db({"signal_dbfs": -40.0, "snr_db": 3.9}, gains) == 12.5,
    "noise without the configured 4 dB signal margin keeps the safe reference gain",
)
check(
    choose_smart_gain_db({"signal_dbfs": -80.0, "snr_db": 30.0}, gains) <= 20.7,
    "Smart Gain cannot rise above its 20.7 dB bounded ceiling",
)
selected, strongest = choose_for_measurements(
    [
        {"signal_dbfs": -40.0, "snr_db": 8.0},
        {"signal_dbfs": -22.0, "snr_db": 9.0},
    ],
    gains,
)
check(selected < 12.5 and strongest["signal_dbfs"] == -22.0,
      "multi-channel probing protects the fixed gain against the strongest clear channel")


def iq_payload(*, tone_amplitude: float, noise_amplitude: float, count: int = 16_384) -> bytes:
    generator = np.random.default_rng(20260930)
    phase = np.arange(count, dtype=np.float64) * (2.0 * np.pi / 32.0)
    noise = noise_amplitude * (
        generator.standard_normal(count) + 1j * generator.standard_normal(count)
    )
    samples = tone_amplitude * np.exp(1j * phase) + noise
    raw = np.empty(count * 2, dtype=np.uint8)
    raw[0::2] = np.clip(np.rint(samples.real * 127.5 + 127.5), 0, 255).astype(np.uint8)
    raw[1::2] = np.clip(np.rint(samples.imag * 127.5 + 127.5), 0, 255).astype(np.uint8)
    return raw.tobytes()


measurement = analyze_iq_samples(
    iq_payload(tone_amplitude=0.08, noise_amplitude=0.004),
    sample_rate_hz=240_000,
    channel_bandwidth_hz=20_000,
)
check(measurement["snr_db"] > 4.0, "IQ analyzer distinguishes an in-channel signal from noise")
check(measurement["clip_fraction"] < 0.001, "IQ analyzer reports unclipped sample headroom")
legacy_hf_mode = hf_monitor.validate_rf_controls({"gain_mode": "auto"})
check(legacy_hf_mode["gain_mode"] == "smart",
      "Radio Receiver maps saved Auto Gain requests to Smart Gain")


class FakeRtlLibrary:
    def __init__(self) -> None:
        self.tuner_gain = 125
        self.agc_modes: list[int] = []
        self.tuner_modes: list[int] = []

    def rtlsdr_set_agc_mode(self, _device, enabled):
        self.agc_modes.append(int(enabled))
        return 0

    def rtlsdr_set_tuner_gain_mode(self, _device, enabled):
        self.tuner_modes.append(int(enabled))
        return 0

    def rtlsdr_set_tuner_gain(self, _device, gain):
        self.tuner_gain = int(gain)
        return 0

    def rtlsdr_get_tuner_gain(self, _device):
        return self.tuner_gain

    def rtlsdr_reset_buffer(self, _device):
        return 0


tuner = hf_monitor_backend._RtlSdrDevice.__new__(hf_monitor_backend._RtlSdrDevice)
tuner.library = FakeRtlLibrary()
tuner.device = ctypes.c_void_p(1)
tuner.sampling_mode = "QUADRATURE_TUNER"
tuner.sample_rate_hz = 240_000
tuner.center_frequency_hz = 144_000_000
with patch.object(tuner, "available_gains_db", return_value=gains), patch.object(
    tuner, "read", side_effect=[
        iq_payload(tone_amplitude=0.08, noise_amplitude=0.004),
        iq_payload(tone_amplitude=0.08, noise_amplitude=0.004),
    ],
):
    tuner_result = tuner.set_gain(gain_mode="smart", gain_db=28.0)
check(
    tuner_result["gain_mode"] == "smart"
    and tuner_result["smart_gain_db"] == tuner_result["gain_db"] < 12.5
    and not tuner_result["digital_agc"],
    "Radio Receiver Smart Gain probes the tuner path and holds a fixed selected gain",
)

direct = hf_monitor_backend._RtlSdrDevice.__new__(hf_monitor_backend._RtlSdrDevice)
direct.library = FakeRtlLibrary()
direct.device = ctypes.c_void_p(1)
direct.sampling_mode = "Q_BRANCH_DIRECT"
direct.sample_rate_hz = 240_000
direct.center_frequency_hz = 7_100_000
direct_result = direct.set_gain(gain_mode="smart", gain_db=28.0)
check(
    direct_result["digital_agc"]
    and not direct_result["manual_gain_effective"]
    and direct.library.agc_modes == [1],
    "Radio Receiver Smart Gain truthfully selects digital AGC on direct-sampling HF",
)


class FakeProbeDevice:
    def __init__(self, *, serial, center_frequency_hz, sample_rate_hz) -> None:
        self.serial = serial
        self.frequency = center_frequency_hz
        self.sample_rate_hz = sample_rate_hz
        self.retuned: list[int] = []
        self.closed = False

    def open(self, *, gain_mode, gain_db):
        assert gain_mode == "manual"
        self.reference_gain_db = gain_db
        return {"valid_gains": gains}

    def retune(self, frequency_hz):
        self.frequency = frequency_hz
        self.retuned.append(frequency_hz)

    def read(self, _byte_count=0):
        return iq_payload(tone_amplitude=0.08, noise_amplitude=0.004)

    def close(self):
        self.closed = True


fake_probe_devices: list[FakeProbeDevice] = []


def fake_probe_factory(**kwargs):
    device = FakeProbeDevice(**kwargs)
    fake_probe_devices.append(device)
    return device


with patch.object(hf_monitor_backend, "_RtlSdrDevice", side_effect=fake_probe_factory):
    channel_probe = hf_monitor_backend.probe_smart_gain_for_channels(
        serial="TEST123",
        frequencies_hz=[144_000_000, 145_000_000],
        minimum_snr_db=4.0,
    )
check(
    channel_probe["probed_channels"] == 2
    and channel_probe["gain_db"] < 12.5
    and fake_probe_devices[0].retuned == [145_000_000]
    and fake_probe_devices[0].closed,
    "Traffic Voice pre-start probe checks its bounded channel list and closes the device",
)

with patch.object(hf_monitor_backend, "_RtlSdrDevice", side_effect=fake_probe_factory):
    weather_channel_probe = hf_monitor_backend.probe_smart_gain_for_channels(
        serial="WEATHER-TEST",
        frequencies_hz=[137_100_000],
        minimum_snr_db=4.0,
        channel_bandwidth_hz=120_000,
        sample_rate_hz=1_024_000,
        reference_gain_db=38.6,
        maximum_gain_db=max(gains),
    )
check(
    fake_probe_devices[-1].sample_rate_hz == 1_024_000
    and fake_probe_devices[-1].reference_gain_db == 38.6
    and weather_channel_probe["reference_gain_db"] == 38.6
    and fake_probe_devices[-1].closed,
    "Weather Smart Gain probes at the METEOR sample rate and configured tuner-gain reference",
)

with tempfile.TemporaryDirectory() as temporary_directory:
    station_config = Path(temporary_directory) / "station.yaml"
    station_config.write_text(
        "weather_rf:\n  gain_mode: auto\n  gain_db: 38.6\n  lna_agc: true\n",
        encoding="utf-8",
    )
    with patch.object(config, "STATION_CONFIG", station_config):
        saved_weather = config.set_weather_rf_config({
            "gain_mode": "smart",
            "gain_db": 38.6,
            "lna_agc": True,
        })
        check(
            saved_weather["gain_mode"] == "smart"
            and saved_weather["gain_db"] == 38.6
            and saved_weather["lna_agc"] is False,
            "Weather settings persist Smart mode and force tuner AGC off",
        )

clear_weather_probe = {
    "gain_db": 43.4,
    "measurement": {"signal_dbfs": -38.0, "snr_db": 8.0, "clip_fraction": 0.0},
}
weather_settings = {"gain_mode": "smart", "gain_db": 38.6, "lna_agc": True}
with patch.object(
    hf_monitor_backend,
    "probe_smart_gain_for_channels",
    return_value=clear_weather_probe,
) as weather_probe:
    weather_gain = weather_smart_gain.resolve_capture_gain(
        settings=weather_settings,
        receiver_serial="WEATHER-TEST",
        frequency_hz=137_100_000,
        sample_rate_hz=1_024_000,
    )
check(
    weather_gain["gain_mode"] == "smart"
    and weather_gain["gain_db"] == 43.4
    and weather_probe.call_args.kwargs["reference_gain_db"] == 38.6
    and weather_probe.call_args.kwargs["sample_rate_hz"] == 1_024_000
    and weather_probe.call_args.kwargs["channel_bandwidth_hz"] == 120_000,
    "Weather Smart Gain probes METEOR once and selects one fixed supported gain",
)

with patch.object(
    hf_monitor_backend,
    "probe_smart_gain_for_channels",
    return_value={"gain_db": 12.5, "measurement": None},
):
    weather_fallback = weather_smart_gain.resolve_capture_gain(
        settings=weather_settings,
        receiver_serial="WEATHER-TEST",
        frequency_hz=137_100_000,
        sample_rate_hz=1_024_000,
    )
check(
    weather_fallback["gain_db"] == 38.6
    and weather_fallback["smart_gain"]["fallback_reason"] == "no_clear_signal",
    "Weather Smart Gain retains the configured tuner gain when the probe is unclear",
)

with patch.object(
    hf_monitor_backend,
    "probe_smart_gain_for_channels",
    side_effect=RuntimeError("weather probe unavailable"),
):
    weather_probe_error = weather_smart_gain.resolve_capture_gain(
        settings=weather_settings,
        receiver_serial="WEATHER-TEST",
        frequency_hz=137_100_000,
        sample_rate_hz=1_024_000,
    )
check(
    weather_probe_error["gain_db"] == 38.6
    and weather_probe_error["smart_gain"]["fallback_reason"] == "probe_error",
    "Weather Smart Gain falls back safely if the receiver probe fails",
)

with patch.object(
    hf_monitor_backend,
    "probe_smart_gain_for_channels",
    return_value={
        "gain_db": 43.4,
        "measurement": {"signal_dbfs": -25.0, "snr_db": 9.0, "clip_fraction": 0.02},
    },
):
    weather_clipped = weather_smart_gain.resolve_capture_gain(
        settings=weather_settings,
        receiver_serial="WEATHER-TEST",
        frequency_hz=137_100_000,
        sample_rate_hz=1_024_000,
    )
check(
    weather_clipped["gain_db"] <= 32.6
    and weather_clipped["smart_gain"]["fallback_reason"] == "input_clipping",
    "Weather Smart Gain lowers its selection when the probe reports clipping",
)

command_data = {
    "rf": {"gain_mode": "smart", "gain_db": 38.6, "lna_agc": False},
    "pass": {"frequency": 137_100_000, "sample_rate": 1_024_000},
    "device": {"serial": "WEATHER-TEST"},
    "command": ["satdump", "live", "meteor", "out", "--gain", "38.6", "--timeout", "300"],
}
with patch.object(
    weather_smart_gain,
    "resolve_capture_gain",
    return_value={
        "gain_mode": "smart",
        "gain_db": 43.4,
        "smart_gain": {"source": "smart_probe", "selected_gain_db": 43.4},
    },
):
    satdump.resolve_record_gain(command_data)
check(
    command_data["command"][command_data["command"].index("--gain") + 1] == "43.4"
    and "--lna_agc" not in command_data["command"],
    "SatDump command uses the measured fixed gain with tuner AGC disabled",
)

manual_weather_data = {
    "rf": {"gain_mode": "manual", "gain_db": 28.0, "lna_agc": False},
    "pass": {"frequency": 137_100_000, "sample_rate": 1_024_000},
    "device": {"serial": "WEATHER-TEST"},
    "command": ["satdump", "live", "meteor", "out", "--gain", "28.0"],
}
satdump.resolve_record_gain(manual_weather_data)
check(
    manual_weather_data["command"][-1] == "28.0",
    "manual Weather gain remains unchanged by Smart Gain resolution",
)

engine = MissionEngine()
engine.active_job = MissionJob(
    mission_id="smart-gain-validator",
    satellite="METEOR-M2",
    frequency=137_100_000,
    mode="LRPT",
    pipeline="meteor_m2_lrpt",
    output_path="/tmp/sdrcc-weather-test",
    receiver="SDR2",
    receiver_id="sdr2",
    receiver_serial="WEATHER-TEST",
    status="RECORDING",
    progress=50,
    created_at=datetime.now(),
)
with patch.object(mission_engine.event_bus, "publish_mission", return_value=None):
    engine.update_gain(
        gain_mode="smart",
        gain_db=43.4,
        smart_gain={"source": "smart_probe", "selected_gain_db": 43.4},
    )
check(
    engine.active_job.gain_mode == "smart"
    and engine.active_job.gain_db == 43.4
    and engine.active_job.smart_gain["selected_gain_db"] == 43.4,
    "Weather mission history records the actual Smart Gain result",
)

iss_smart_settings = {"gain_mode": "smart", "gain_db": 3.7}
clear_iss_probe = {
    "gain_db": 20.7,
    "measurement": {"signal_dbfs": -40.0, "snr_db": 8.0, "clip_fraction": 0.0},
}
with patch.object(hf_monitor_backend, "probe_smart_gain_for_channels", return_value=clear_iss_probe) as iss_probe:
    iss_gain = iss_smart_gain.resolve_capture_gain(
        config=iss_smart_settings,
        receiver_serial="ISS-TEST",
        frequency_hz=437_550_000,
        sample_rate_hz=240_000,
    )
check(
    iss_gain["gain_mode"] == "smart"
    and iss_gain["gain_db"] == 20.7
    and iss_probe.call_args.kwargs["channel_bandwidth_hz"] == 50_000,
    "ISS Smart Gain probes the Doppler-wide channel and selects one fixed supported gain",
)

with patch.object(
    hf_monitor_backend, "probe_smart_gain_for_channels",
    return_value={"gain_db": 12.5, "measurement": None},
):
    fallback_gain = iss_smart_gain.resolve_capture_gain(
        config=iss_smart_settings,
        receiver_serial="ISS-TEST",
        frequency_hz=437_550_000,
        sample_rate_hz=240_000,
    )
check(
    fallback_gain["gain_db"] == 3.7
    and fallback_gain["smart_gain"]["fallback_reason"] == "no_clear_signal",
    "ISS Smart Gain uses the configured 3.7 dB fallback when no clear signal is measured",
)
check(
    iss_voice.get_settings({"gain_mode": "smart", "gain_db": 37.2})["gain_db"] == 25.4,
    "ISS Smart Gain clamps high legacy fallback settings to 25.4 dB",
)

with patch.object(
    hf_monitor_backend, "probe_smart_gain_for_channels", side_effect=RuntimeError("probe unavailable")
):
    failed_probe_gain = iss_smart_gain.resolve_capture_gain(
        config=iss_smart_settings,
        receiver_serial="ISS-TEST",
        frequency_hz=437_550_000,
        sample_rate_hz=240_000,
    )
check(
    failed_probe_gain["gain_db"] == 3.7
    and failed_probe_gain["smart_gain"]["fallback_reason"] == "probe_error",
    "ISS Smart Gain safely falls back when the receiver probe fails",
)

with patch.object(
    hf_monitor_backend, "probe_smart_gain_for_channels",
    return_value={
        "gain_db": 20.7,
        "measurement": {"signal_dbfs": -30.0, "snr_db": 8.0, "clip_fraction": 0.03},
    },
):
    clipped_gain = iss_smart_gain.resolve_capture_gain(
        config=iss_smart_settings,
        receiver_serial="ISS-TEST",
        frequency_hz=437_550_000,
        sample_rate_hz=240_000,
    )
check(
    clipped_gain["gain_db"] == 3.7
    and clipped_gain["smart_gain"]["fallback_reason"] == "input_clipping",
    "ISS Smart Gain caps an overloaded probe at the configured fallback gain",
)

smart_spec = wideband_iq_recorder.build_spec(
    mission_id="smart-gain-validator",
    receiver_serial="ISS-TEST",
    frequency_hz=437_550_000,
    sample_rate_hz=240_000,
    duration_seconds=10,
    gain_db=iss_gain["gain_db"],
    gain_mode=iss_gain["gain_mode"],
    smart_gain=iss_gain["smart_gain"],
)
smart_capture_metadata = wideband_iq_recorder.describe_capture(smart_spec)
check(
    smart_capture_metadata["gain_mode"] == "smart"
    and smart_capture_metadata["gain_db"] == 20.7
    and smart_capture_metadata["smart_gain"]["selected_gain_db"] == 20.7
    and "-g" in smart_capture_metadata["command"],
    "ISS capture metadata records the Smart decision and fixed rtl_sdr gain",
)


raw_config = config.load_traffic_voice()
legacy_auto = json.loads(json.dumps(raw_config))
legacy_auto["traffic_voice"]["backend"]["gain_mode"] = "auto"
check(
    traffic_voice.get_receiver_settings(legacy_auto)["gain_mode"] == "smart",
    "older saved Auto Gain settings remain enabled as Smart Gain",
)
smart_config = json.loads(json.dumps(raw_config))
smart_config["traffic_voice"]["backend"]["gain_mode"] = "smart"
check(
    traffic_voice.validate_configuration(smart_config)["ok"],
    "Traffic Voice validates persisted Smart Gain without changing its schema",
)
normalized = traffic_voice.normalize_receiver_settings(
    {"auto_gain": True}, payload=legacy_auto,
)
manual = traffic_voice.normalize_receiver_settings(
    {"auto_gain": False}, payload=legacy_auto,
)
check(normalized["gain_mode"] == "smart" and manual["gain_mode"] == "manual",
      "Traffic Voice keeps one Smart/Manual checkbox and accepts legacy clients")


plan = {
    "backend": {
        "stats_file": "/run/sdrcc-traffic-voice/channel-stats.prom",
        "correction_ppm": 0,
        "audio_host": "127.0.0.1",
        "audio_port": 49555,
    },
    "selected_mode": "marine_ais",
    "mode": {"modulation": "nfm"},
    "receiver": {"serial": "TEST123"},
    "receiver_settings": {
        "mode_id": "marine_ais",
        "gain_mode": "smart",
        "gain_db": 12.5,
        "selected_channel_id": "v61_botlek",
        "tuning_mode": "fixed",
        "open_squelch": False,
        "squelch_snr_db": 4.0,
        "scan_interval_ms": 200,
        "channel_filter_enabled": True,
        "scan_channel_ids": [],
    },
    "channels": [{"id": "v61_botlek", "label": "V61_BOTLEK", "frequency_mhz": 160.675}],
}
with patch.object(traffic_voice, "_runtime_channel_plan", return_value=plan):
    probe_plan = traffic_voice.smart_gain_probe_plan(raw_config)
    rendered = traffic_voice.render_rtlsdr_airband_config(
        smart_gain_db=19.7,
        payload=raw_config,
    )
check(
    probe_plan["frequencies_hz"] == [160_675_000]
    and probe_plan["minimum_snr_db"] == 4.0,
    "Traffic Voice probes its selected channel using the separate 4 dB squelch setting",
)
check(
    "gain = 19.7;" in rendered
    and "Smart Gain probe selected a fixed 19.7 dB tuner gain." in rendered
    and "gain = -1.0;" not in rendered,
    "Traffic Voice writes a measured fixed gain instead of native unlimited Auto Gain",
)

manual_plan = json.loads(json.dumps(plan))
manual_plan["receiver_settings"]["gain_mode"] = "manual"
manual_plan["receiver_settings"]["gain_db"] = 12.5
with patch.object(traffic_voice, "_runtime_channel_plan", return_value=manual_plan):
    manual_rendered = traffic_voice.render_rtlsdr_airband_config(payload=raw_config)
check("gain = 12.5;" in manual_rendered, "manual Traffic Voice gain remains selectable and unchanged")

check(
    update_manager.compare_versions("0.63.3", "0.63.4") == -1,
    "the managed Update button recognizes 0.63.4 as newer than 0.63.3",
)
check(
    update_manager.compare_versions("0.63.5", "0.63.6") == -1,
    "the managed Update button recognizes 0.63.6 as newer than 0.63.5",
)
check(
    update_manager.compare_versions("0.63.6", "0.63.7") == -1,
    "the managed Update button recognizes 0.63.7 as newer than 0.63.6",
)
check(
    update_manager.compare_versions("0.63.7", "0.63.8") == -1,
    "the managed Update button recognizes 0.63.8 as newer than 0.63.7",
)
check(
    update_manager.compare_versions("0.63.8", "0.63.9") == -1,
    "the managed Update button recognizes 0.63.9 as newer than 0.63.8",
)
check(
    update_manager.compare_versions("0.63.9", "0.63.10") == -1,
    "the managed Update button recognizes 0.63.10 as newer than 0.63.9",
)
check(
    update_manager.compare_versions("0.63.10", "0.63.11") == -1,
    "the managed Update button recognizes 0.63.11 as newer than 0.63.10",
)
check(
    update_manager.compare_versions("0.63.11", "0.63.12") == -1,
    "the managed Update button recognizes 0.63.12 as newer than 0.63.11",
)
manifest = json.loads((ROOT / "scripts/install/update_manifest.json").read_text())
update_files = {
    "VERSION",
    "core/hf_monitor.py",
    "core/hf_monitor_backend.py",
    "core/controlled_iq_capture.py",
    "core/iss_smart_gain.py",
    "core/weather_smart_gain.py",
    "core/rtl_smart_gain.py",
    "core/mission_engine.py",
    "core/iss_voice.py",
    "core/wideband_iq_recorder.py",
    "core/traffic_voice.py",
    "core/traffic_voice_audio.py",
    "core/iss_sstv.py",
    "core/iss_voice_executor.py",
    "core/mission_operations.py",
    "core/mission_planner.py",
    "core/mission_scheduler.py",
    "core/update_manager.py",
    "dashboard/static/js/hf_monitor.js",
    "dashboard/static/dashboard.js",
    "dashboard/static/js/dashboard.js",
    "dashboard/static/js/mission_analytics.js",
    "dashboard/static/js/radio.js",
    "dashboard/static/js/traffic_voice.js",
    "dashboard/static/css/traffic_voice.css",
    "dashboard/static/css/mission_planner.css",
    "dashboard/static/js/mission_planner.js",
    "dashboard/static/js/mission_recordings.js",
    "dashboard/static/js/update_manager.js",
    "dashboard/templates/index.html",
    "scripts/validate_marine_replays_v0636.py",
    "scripts/validate_radio_control_clarity_v0540g.py",
    "scripts/validate_iss_pll_lock_retry_v06312.py",
    "dashboard/app.py",
    "requirements.txt",
    "scripts/install/prepare_audio_comparison.sh",
    "scripts/install/prepare_iss_sstv_decoder.sh",
    "scripts/sdrcc_update.py",
    "scripts/traffic_voice_prepare.py",
}
check(update_files.issubset(manifest), "the managed Update button manifest deploys Smart Gain, ISS Voice and SSTV runtime files")
check(
    {"core/traffic_voice_audio.py", "dashboard/static/css/traffic_voice.css",
     "scripts/validate_marine_replays_v0636.py"}.issubset(manifest),
    "the managed Update button manifest deploys Marine replay and its validation",
)
check("README.md" not in manifest, "managed updates preserve the main README and screenshot links")
installed_v06310_hashes = {
    "VERSION": "39b84a92002a498d9b9c12a938e1c6349081342a81079daacfa8cda4fbfcc497",
    "core/config.py": "4c98817ee61311699e62dd70fb51cce9e983fbbd161154634932591b41810d64",
    "core/hf_monitor_backend.py": "eecbb3f9415cba1207c73c1d07218793e3d840c804d5ebf51dbf151fd04fb596",
    "core/rtl_smart_gain.py": "11858ae34c6a54ad6e8e95a8c9fa75e6e6b07fd2e605af04b40a28167381df92",
    "core/satdump.py": "d2a42b1782858ff063615aa2e5c2a25a103a77ea9ea5e41ec7b56f11c44ac928",
    "core/mission_engine.py": "a64b9c626bdc1d4dd3d2091ae599712d3e477627ac93dba6cd975318c6c76c50",
    "dashboard/app.py": "5ba680c6788539c4fa3961200af4750fc073310dba1a8169a6bb7882ecaca36d",
    "dashboard/static/js/radio.js": "e05e215ccc828a9c2b0b13381af2d600dce74074c7652e873bc2afcd921a56d4",
    "dashboard/templates/index.html": "492c0f94da3c38d0e842ba92e6b7b6a9d446a5250c2cb90d29d9da70490c84d8",
    "scripts/validate_smart_gain.py": "ba5d2c0e6416c83b3ed7c483229b2bb36c096340fa6fec9d6a56332202e20576",
}
check(
    all(digest in manifest.get(name, []) for name, digest in installed_v06310_hashes.items()),
    "the Update manifest accepts clean 0.63.10 source files for Weather Smart Gain",
)
installed_v06311_hashes = {
    "VERSION": "0c755e853f13dcd7adf0fe6c85e4764ca5d15a8c506fe663fdd3eb863a6774ce",
    "core/wideband_iq_recorder.py": "e148124930bb46473e2026e947dc2c1c572b870f4e66bc8f29aa5a4c846fdfc1",
    "core/controlled_iq_capture.py": "9d8bae694ab0dcac0fde03d1ad87e428bd639b1a90e1453540d6bff0aea145fb",
    "core/iss_voice_executor.py": "d4ca6f6b28394f6b3f8972115a86b22f2dac833c193fe3bbb18f31d5a726ceba",
    "scripts/validate_smart_gain.py": "9a97f8151c8235d2009bdaf07ce6b1f8a23ede7e345fe477c5082a9102747437",
}
check(
    all(digest in manifest.get(name, []) for name, digest in installed_v06311_hashes.items()),
    "the Update manifest accepts clean 0.63.11 source files for the PLL retry update",
)
check(
    '<option value="smart">Smart</option>' in (ROOT / "dashboard/templates/index.html").read_text()
    and "ISS_PROBE_BANDWIDTH_HZ = 50_000" in (ROOT / "core/iss_smart_gain.py").read_text()
    and "digital AGC" in (ROOT / "dashboard/static/js/hf_monitor.js").read_text(),
    "the dashboard exposes Doppler-aware ISS Smart Gain alongside Radio Receiver Smart Gain",
)
weather_html = (ROOT / "dashboard/templates/index.html").read_text()
weather_js = (ROOT / "dashboard/static/js/radio.js").read_text()
weather_gain_source = (ROOT / "core/weather_smart_gain.py").read_text()
satdump_source = (ROOT / "core/satdump.py").read_text()
dashboard_source = (ROOT / "dashboard/app.py").read_text()
mission_source = (ROOT / "core/mission_engine.py").read_text()
check(
    '<option value="smart">Smart</option>' in weather_html
    and "Tuner gain / Smart fallback" in weather_html
    and "mode?.value === \"smart\"" in weather_js
    and "WEATHER_PROBE_BANDWIDTH_HZ = 120_000" in weather_gain_source,
    "Weather / METEOR settings expose Smart mode and its fixed-gain fallback",
)
check(
    "resolve_record_gain(record_data)" in dashboard_source
    and "SDRCC_WEATHER_GAIN=" in satdump_source
    and "mission_update_gain" in dashboard_source
    and "smart_gain: Optional[dict]" in mission_source,
    "scheduled and Record NOW missions retain their actual Weather Smart Gain result",
)
for name, allowed in manifest.items():
    if name == "scripts/install/update_manifest.json":
        continue
    source = ROOT / name
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    check(source.is_file() and digest in allowed, f"manifest hash matches {name}")
check(
    (ROOT / "VERSION").read_text().strip() == "0.63.12",
    "release version is 0.63.12",
)
print("VALIDATION PASS: SDRCC Smart Gain and managed-update payload")
