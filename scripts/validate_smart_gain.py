#!/usr/bin/env python3
"""Hardware-free Smart Gain, Traffic Voice and managed-update validation."""

from __future__ import annotations

import hashlib
import json
import ctypes
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import config, hf_monitor, hf_monitor_backend, traffic_voice, update_manager  # noqa: E402
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
        assert gain_mode == "manual" and gain_db == 12.5
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
manifest = json.loads((ROOT / "scripts/install/update_manifest.json").read_text())
update_files = {
    "VERSION",
    "core/hf_monitor.py",
    "core/hf_monitor_backend.py",
    "core/rtl_smart_gain.py",
    "core/traffic_voice.py",
    "core/traffic_voice_audio.py",
    "core/iss_sstv.py",
    "core/iss_voice_executor.py",
    "core/mission_operations.py",
    "core/mission_planner.py",
    "core/mission_scheduler.py",
    "core/update_manager.py",
    "dashboard/static/js/hf_monitor.js",
    "dashboard/static/js/traffic_voice.js",
    "dashboard/static/css/traffic_voice.css",
    "dashboard/static/css/mission_planner.css",
    "dashboard/static/js/mission_planner.js",
    "dashboard/static/js/mission_recordings.js",
    "dashboard/static/js/update_manager.js",
    "dashboard/templates/index.html",
    "scripts/validate_marine_replays_v0636.py",
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
check(
    "Smart Gain" in (ROOT / "dashboard/templates/index.html").read_text()
    and "digital AGC" in (ROOT / "dashboard/static/js/hf_monitor.js").read_text(),
    "the dashboard names Smart Gain and explains its direct-sampling fallback",
)
for name, allowed in manifest.items():
    if name == "scripts/install/update_manifest.json":
        continue
    source = ROOT / name
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    check(source.is_file() and digest in allowed, f"manifest hash matches {name}")
check(
    (ROOT / "VERSION").read_text().strip() == "0.63.7",
    "release version is 0.63.7",
)
print("VALIDATION PASS: SDRCC bounded Smart Gain and managed-update payload")
