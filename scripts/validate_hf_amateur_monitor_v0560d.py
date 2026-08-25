#!/usr/bin/env python3
"""Validate SDRCC v0.56.0d HF FM, gain and squelch extension."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import numpy as np

ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()
sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def cu8(iq: np.ndarray) -> bytes:
    values = np.empty(iq.size * 2, dtype=np.float32)
    values[0::2] = np.real(iq)
    values[1::2] = np.imag(iq)
    values = np.clip(np.rint((values * 127.5) + 127.5), 0, 255).astype(np.uint8)
    return values.tobytes()


def validate_static() -> None:
    required = [
        "config/hf_monitor.yaml",
        "core/hf_monitor.py",
        "core/hf_monitor_backend.py",
        "core/hf_monitor_controller.py",
        "dashboard/app.py",
        "dashboard/templates/index.html",
        "dashboard/static/js/hf_monitor.js",
        "dashboard/static/css/hf_monitor.css",
        "docs/hf-amateur-monitor-v0560d.md",
    ]
    for relative in required:
        check((ROOT / relative).is_file(), f"required file present: {relative}")
    check(read("VERSION").strip() == "0.56.0d", "release version is 0.56.0d")

    config = read("config/hf_monitor.yaml")
    backend = read("core/hf_monitor_backend.py")
    monitor = read("core/hf_monitor.py")
    controller = read("core/hf_monitor_controller.py")
    app = read("dashboard/app.py")
    template = read("dashboard/templates/index.html")
    javascript = read("dashboard/static/js/hf_monitor.js")

    check("- FM" in config and '"FM"' in monitor, "FM is part of the bounded HF mode vocabulary")
    check("gain_mode: auto" in config and "squelch_threshold_dbfs" in config, "HF gain and squelch defaults are explicit")
    check('if self.mode == "FM"' in backend and "np.angle" in backend, "FM uses the existing DSP worker phase discriminator")
    check("rtlsdr_set_tuner_gain_mode" in backend and "rtlsdr_set_tuner_gain" in backend, "librtlsdr gain control stays in the existing device owner")
    check("Q-branch bypasses the tuner" in backend, "direct-sampling gain limitation is explicit")
    check("def update_rf_controls" in backend and "_rf_request" in backend, "live RF settings use worker request/acknowledgement")
    check("def update_rf_controls" in controller and "receiver_manager." not in controller[controller.index("def update_rf_controls"):controller.index("\ndef stop(", controller.index("def update_rf_controls"))], "live RF settings do not create receiver authority")
    check('"rf_settings"' in app and "hf_monitor_controller.update_rf_controls" in app, "bounded HF action endpoint applies live RF settings")
    for element in (
        "hf-monitor-auto-gain", "hf-monitor-gain-db", "hf-monitor-squelch-enabled",
        "hf-monitor-squelch-threshold", "hf-monitor-apply-rf",
    ):
        check(f'id="{element}"' in template, f"HF page contains {element}")
    check("rfControlsFromForm" in javascript and 'action("rf_settings")' in javascript, "HF UI wires gain and squelch to the bounded action")
    check("manual_gain_effective" in backend and "directSampling" in javascript, "UI distinguishes direct-sampling from tuner gain")


def validate_dsp() -> None:
    from core.hf_monitor_backend import HFSignalProcessor, SAMPLE_RATE_HZ

    count = 32768
    t = np.arange(count, dtype=np.float64) / SAMPLE_RATE_HZ
    audio_hz = 1000.0
    beta = 1.5
    iq = (0.35 * np.exp(1j * beta * np.sin(2.0 * np.pi * audio_hz * t))).astype(np.complex64)
    processor = HFSignalProcessor(center_frequency_hz=7_100_000, mode="FM")
    result = processor.process(cu8(iq))
    pcm = np.frombuffer(result["audio_pcm"], dtype="<i2").astype(np.float64)
    check(pcm.size > 100, "FM demodulator emits 16 kHz PCM")
    spectrum = np.abs(np.fft.rfft(pcm - np.mean(pcm)))
    frequencies = np.fft.rfftfreq(pcm.size, d=1.0 / 16000.0)
    peak = float(frequencies[int(np.argmax(spectrum[1:]) + 1)])
    check(abs(peak - audio_hz) < 80.0, "FM phase discriminator preserves a 1 kHz modulation tone")

    muted = HFSignalProcessor(
        center_frequency_hz=7_100_000,
        mode="AM",
        squelch_enabled=True,
        squelch_threshold_dbfs=-10.0,
    )
    noise = (0.01 * (np.random.default_rng(1).normal(size=count) + 1j * np.random.default_rng(2).normal(size=count))).astype(np.complex64)
    muted_pcm = np.frombuffer(muted.process(cu8(noise))["audio_pcm"], dtype="<i2")
    check(muted_pcm.size > 0 and not np.any(muted_pcm), "RF-power squelch mutes audio below threshold")

    opened = HFSignalProcessor(
        center_frequency_hz=7_100_000,
        mode="AM",
        squelch_enabled=True,
        squelch_threshold_dbfs=-50.0,
    )
    am = ((1.0 + 0.5 * np.sin(2.0 * np.pi * 800.0 * t)) * 0.25).astype(np.complex64)
    open_pcm = np.frombuffer(opened.process(cu8(am))["audio_pcm"], dtype="<i2")
    check(open_pcm.size > 0 and np.any(open_pcm), "RF-power squelch passes audio above threshold")


def main() -> int:
    try:
        validate_static()
        validate_dsp()
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASS: SDRCC v0.56.0d HF FM, Auto Gain and Squelch")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
