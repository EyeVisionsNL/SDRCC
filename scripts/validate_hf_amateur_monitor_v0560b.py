#!/usr/bin/env python3
"""Validate the executable v0.56.0b HF Amateur Monitor."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

import numpy as np


ROOT = Path(os.environ.get("SDRCC_ROOT", "/home/eyevisions/SDRCC")).resolve()
sys.path.insert(0, str(ROOT))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_static_boundaries() -> None:
    required = [
        "config/hf_monitor.yaml",
        "core/hf_monitor.py",
        "core/hf_monitor_backend.py",
        "core/hf_monitor_controller.py",
        "dashboard/app.py",
        "dashboard/templates/index.html",
        "dashboard/static/css/hf_monitor.css",
        "dashboard/static/js/hf_monitor.js",
        "docs/hf-amateur-monitor-v0560b.md",
    ]
    for relative in required:
        check((ROOT / relative).is_file(), f"required file present: {relative}")

    controller = read("core/hf_monitor_controller.py")
    controller_tree = ast.parse(controller, filename="core/hf_monitor_controller.py")
    controller_imports = {
        alias.name
        for node in ast.walk(controller_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    check("subprocess" not in controller_imports, "controller has no direct process authority")
    check("systemctl" not in controller, "controller uses injected service authority")
    check("receiver_manager.begin_handover" in controller, "Receiver Manager owns HF handover")
    check("receiver_manager.restore_handover" in controller, "Receiver Manager owns exact HF restore")
    check(controller.index("_write_session(session)") < controller.index("receiver_manager.begin_handover"), "durable HF session precedes service stop")
    check("def _start_watchdog(" in controller and "recovery=True" in controller, "unexpected IQ loss triggers fail-closed exact restore")

    backend = read("core/hf_monitor_backend.py")
    check("subprocess" not in backend and "systemctl" not in backend, "HF backend has no service controller")
    check("rtlsdr_set_direct_sampling" in backend and "direct = 2" in backend, "SMArt v5 Q-branch direct sampling is explicit")
    check("center_frequency_hz < 25_000_000" in backend, "10 metre switches to the normal tuner")
    check("HFSignalProcessor" in backend and "_design_sideband" in backend, "one backend provides measured DSP and SSB selection")
    check('list(_spectrum_points) if spectrum_available else []' in backend and 'list(_waterfall) if spectrum_available else []' in backend, "spectrum and waterfall originate only from available live IQ state")
    check("stream_wav" in backend and "AUDIO_SAMPLE_RATE_HZ = 16_000" in backend, "backend exposes 16 kHz PCM browser audio")

    app = read("dashboard/app.py")
    template = read("dashboard/templates/index.html")
    javascript = read("dashboard/static/js/hf_monitor.js")
    check('@app.route("/api/hf-monitor/action", methods=["POST"])' in app, "bounded HF action endpoint is present")
    check('@app.route("/api/hf-monitor/audio-stream", methods=["GET"])' in app, "HF audio endpoint is present")
    check("service_state=service_state" in app and "service_action=run_systemctl" in app, "dashboard injects existing service authority")
    check("recover_stale_hf_monitor()" in app, "dashboard startup restores stale HF sessions")
    check('id="hf-monitor-spectrum-canvas"' in template and 'id="hf-monitor-waterfall-canvas"' in template, "page has live spectrum and waterfall canvases")
    check('id="hf-monitor-frequency"' in template and 'hf-monitor-frequency" type="number"' in template, "operator frequency input is enabled")
    check('fetch("/api/hf-monitor/action"' in javascript and 'method: "POST"' in javascript, "page-local HF Start/Stop is wired")
    check("drawSpectrum" in javascript and "drawWaterfall" in javascript, "measured RF arrays drive both canvases")
    check("new Audio" in javascript and "hf-monitor-audio-toggle" in javascript, "browser live audio is wired")
    check('data-action="start_hf"' not in template and 'data-action="stop_hf"' not in template, "System receives no competing HF controls")


def _cu8(iq: np.ndarray) -> bytes:
    values = np.empty(iq.size * 2, dtype=np.uint8)
    values[0::2] = np.clip(np.real(iq) * 127.5 + 127.5, 0, 255).astype(np.uint8)
    values[1::2] = np.clip(np.imag(iq) * 127.5 + 127.5, 0, 255).astype(np.uint8)
    return values.tobytes()


def _tone_rms(mode: str, offset_hz: float) -> tuple[float, float, int]:
    from core.hf_monitor_backend import HFSignalProcessor

    processor = HFSignalProcessor(center_frequency_hz=7_100_000, mode=mode)
    chunks = []
    spectrum_count = 0
    for block in range(8):
        index = np.arange(16384, dtype=np.float64) + (block * 16384)
        iq = (0.25 * np.exp(2j * np.pi * offset_hz * index / 240000.0)).astype(np.complex64)
        result = processor.process(_cu8(iq))
        chunks.append(np.frombuffer(result["audio_pcm"], dtype="<i2").astype(np.float64))
        if result["spectrum"] is not None:
            points, row, _peak = result["spectrum"]
            check(len(points) == 256 and len(row) == 256, "measured FFT is reduced to 256 stable bins")
            spectrum_count += 1
    audio = np.concatenate(chunks)[3000:]
    window = audio[-4096:] * np.hanning(4096)
    peak_hz = float(np.argmax(np.abs(np.fft.rfft(window))) * 16000 / 4096)
    return float(np.sqrt(np.mean(np.square(audio)))), peak_hz, spectrum_count


def validate_dsp() -> None:
    usb_right, usb_peak, spectra = _tone_rms("USB", 1800.0)
    usb_wrong, _, _ = _tone_rms("USB", -1800.0)
    lsb_right, lsb_peak, _ = _tone_rms("LSB", -1800.0)
    lsb_wrong, _, _ = _tone_rms("LSB", 1800.0)
    check(usb_right > usb_wrong * 20.0, "USB rejects the opposite sideband")
    check(lsb_right > lsb_wrong * 20.0, "LSB rejects the opposite sideband")
    check(abs(usb_peak - 1800.0) < 12.0 and abs(lsb_peak - 1800.0) < 12.0, "SSB demodulation preserves audio pitch")
    check(spectra >= 2, "continuous IQ processing emits repeated measured spectra")


def validate_backend_worker() -> None:
    from core import hf_monitor_backend

    index = np.arange(16384, dtype=np.float64)
    iq = (0.20 * np.exp(2j * np.pi * 1800.0 * index / 240000.0)).astype(np.complex64)
    payload = _cu8(iq)

    class FakeRtlSdrDevice:
        instances = []

        def __init__(self, *, serial: str, center_frequency_hz: int,
                     sample_rate_hz: int) -> None:
            self.serial = serial
            self.center_frequency_hz = center_frequency_hz
            self.sample_rate_hz = sample_rate_hz
            self.sampling_mode = "Q_BRANCH_DIRECT"
            self.retunes = []
            self.instances.append(self)

        def open(self, *, gain_mode: str = "auto", gain_db: float = 28.0):
            return {
                "gain_mode": gain_mode, "gain_db": gain_db,
                "actual_tuner_gain_db": gain_db,
                "manual_gain_effective": False, "digital_agc": gain_mode == "auto",
                "valid_gains": [12.5, 28.0, 37.2],
            }

        def set_gain(self, *, gain_mode: str, gain_db: float):
            return {
                "gain_mode": gain_mode, "gain_db": gain_db,
                "actual_tuner_gain_db": gain_db,
                "manual_gain_effective": False, "digital_agc": gain_mode == "auto",
            }

        def read(self, byte_count: int = 32768) -> bytes:
            time.sleep(0.003)
            return payload

        def retune(self, center_frequency_hz: int) -> None:
            self.center_frequency_hz = int(center_frequency_hz)
            self.retunes.append(self.center_frequency_hz)

        def close(self) -> None:
            return None

    capability = {
        "ok": True,
        "backend": hf_monitor_backend.BACKEND_ID,
        "direct_sampling_api": True,
    }
    with patch.object(hf_monitor_backend, "_RtlSdrDevice", FakeRtlSdrDevice), \
         patch.object(hf_monitor_backend, "validate_runtime", return_value=capability):
        started = hf_monitor_backend.start(
            serial="24006572",
            receiver_id="sdr2",
            center_frequency_hz=7_100_000,
            band="40m",
            mode="USB",
        )
        check(started["state"] == "LISTENING", "single-owner backend confirms live IQ start")
        deadline = time.monotonic() + 2.0
        runtime = hf_monitor_backend.get_status()
        while time.monotonic() < deadline and not runtime["spectrum"]["available"]:
            time.sleep(0.01)
            runtime = hf_monitor_backend.get_status()
        check(runtime["spectrum"]["available"] and runtime["audio"]["available"], "one live IQ worker supplies measured spectrum and audio")
        retuned = hf_monitor_backend.retune(center_frequency_hz=7_101_250)
        check(retuned["settings"]["center_frequency_hz"] == 7_101_250, "the existing IQ-owner thread confirms live retune")
        check(len(FakeRtlSdrDevice.instances) == 1 and FakeRtlSdrDevice.instances[0].retunes == [7_101_250], "live retune opens no second RTL-SDR owner")
        stream = hf_monitor_backend.stream_wav()
        check(next(stream).startswith(b"RIFF"), "live backend audio stream begins with a WAV header")
        stream.close()
        stopped = hf_monitor_backend.stop()
        check(stopped["state"] == "STOPPED", "single-owner backend releases the receiver on Stop")
        check(stopped["spectrum"]["points"] == [] and stopped["spectrum"]["waterfall"] == [], "Stop clears stale spectrum and waterfall data")


def validate_runtime_and_lifecycle() -> dict[str, object]:
    sys.path.insert(0, str(ROOT))
    from core import hf_monitor, hf_monitor_backend, hf_monitor_controller, plugin_registry

    check(read("VERSION").strip() in {"0.56.0b", "0.56.0c", "0.56.0d"}, "release retains the v0.56.0b live HF contract")
    check(hf_monitor.validate_configuration()["ok"], "executable HF configuration validates")
    plugin = plugin_registry.get_plugin("hf_monitor")
    check(plugin["status"] == "active", "HF Monitor is an active plugin")
    check(plugin_registry.get_plugin("meshcore") is None, "MeshCore remains outside SDRCC")

    normalized = hf_monitor.validate_selection({
        "receiver_id": "sdr2", "band": "40m", "mode": "LSB", "frequency_hz": 7_100_000,
    })
    check(normalized["frequency_hz"] == 7_100_000, "operator HF selection validates")
    try:
        hf_monitor.validate_selection({
            "receiver_id": "sdr2", "band": "40m", "mode": "LSB", "frequency_hz": 14_200_000,
        })
    except ValueError:
        pass
    else:
        raise RuntimeError("out-of-band frequency was accepted")
    print("PASS: out-of-band frequency is rejected")

    fake_runtime = {
        "ok": True, "available": True, "state": "STOPPED", "error": None,
        "spectrum": {"available": False, "source": None, "points": [], "waterfall": []},
        "audio": {"available": False, "stream_url": None},
    }
    with patch.object(hf_monitor_backend, "get_status", return_value=fake_runtime), \
         patch.object(hf_monitor_controller, "get_session", return_value=None):
        snapshot = hf_monitor.get_snapshot()
    check(snapshot["start_allowed"] and snapshot["execution_enabled"], "validated backend enables HF Start")
    check(not snapshot["foundation_only"] and not snapshot["read_only"], "HF snapshot is executable")
    labels = {item["id"]: item["label"] for item in snapshot["receivers"]}
    check(labels == {"sdr1": "SDR1 · pauses AIS", "sdr2": "SDR2 · pauses ADS-B"}, "receiver side effects remain explicit")

    calls: list[object] = []
    device = {
        "id": "sdr2", "runtime_id": "sdr2", "registry_id": "receiver02",
        "serial": "24006572", "name": "SDR2",
    }
    backend_stopped = {"ok": True, "available": True, "state": "STOPPED"}
    backend_live = {
        "ok": True, "available": True, "state": "LISTENING",
        "settings": {"sampling_mode": "Q_BRANCH_DIRECT"},
    }
    with TemporaryDirectory() as temporary:
        session_path = Path(temporary) / "hf_monitor_session.json"
        with patch.object(hf_monitor_controller, "SESSION_FILE", session_path), \
             patch.object(hf_monitor_controller.device_manager, "get_device", return_value=device), \
             patch.object(hf_monitor_controller, "_conflicting_services", return_value=["readsb.service"]), \
             patch.object(hf_monitor_controller.receiver_manager, "begin_handover", side_effect=lambda *a, **k: calls.append("handover")), \
             patch.object(hf_monitor_controller.receiver_manager, "activate", side_effect=lambda **k: calls.append("activate")), \
             patch.object(hf_monitor_controller.receiver_manager, "restore_handover", return_value={"ok": True, "errors": []}), \
             patch.object(hf_monitor_controller.receiver_manager, "release", return_value={"ok": True}), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "get_status", side_effect=[backend_stopped, backend_live]), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "start", side_effect=lambda **k: (calls.append("backend"), backend_live)[1]), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "retune", return_value=backend_live), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "stop", return_value=backend_stopped):
            started = hf_monitor_controller.start(
                normalized,
                service_state=lambda service: {"active": True, "state": "active"},
                service_action=lambda action, service: {"ok": True},
                wait_for_service=lambda service, state, timeout: True,
            )
            check(started["ok"] and calls == ["handover", "backend", "activate"], "HF lifecycle uses handover-before-backend order")
            check(session_path.is_file(), "live HF session is durable")
            retuned_selection = dict(normalized, frequency_hz=7_101_250)
            retuned = hf_monitor_controller.retune(retuned_selection)
            check(retuned["ok"] and not retuned["receiver_handover_changed"], "live retune preserves the active Receiver Manager handover")
            durable = json.loads(session_path.read_text(encoding="utf-8"))
            check(durable["selection"]["frequency_hz"] == 7_101_250, "confirmed live frequency is persisted in the durable session")
            stopped = hf_monitor_controller.stop(
                service_state=lambda service: {"active": False, "state": "inactive"},
                service_action=lambda action, service: {"ok": True},
                wait_for_service=lambda service, state, timeout: True,
            )
            check(stopped["ok"] and not session_path.exists(), "HF Stop restores and clears its durable session")

        restore_calls = []
        with patch.object(hf_monitor_controller, "SESSION_FILE", session_path), \
             patch.object(hf_monitor_controller.device_manager, "get_device", return_value=device), \
             patch.object(hf_monitor_controller, "_conflicting_services", return_value=["readsb.service"]), \
             patch.object(hf_monitor_controller.receiver_manager, "begin_handover", return_value={"ok": True}), \
             patch.object(hf_monitor_controller.receiver_manager, "restore_handover", side_effect=lambda **k: (restore_calls.append("restore"), {"ok": True, "errors": []})[1]), \
             patch.object(hf_monitor_controller.receiver_manager, "release", return_value={"ok": True}), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "get_status", return_value=backend_stopped), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "start", side_effect=RuntimeError("injected backend failure")), \
             patch.object(hf_monitor_controller.hf_monitor_backend, "stop", return_value=backend_stopped):
            try:
                hf_monitor_controller.start(
                    normalized,
                    service_state=lambda service: {"active": True, "state": "active"},
                    service_action=lambda action, service: {"ok": True},
                    wait_for_service=lambda service, state, timeout: True,
                )
            except RuntimeError as error:
                check("injected backend failure" in str(error), "injected backend failure reaches the caller")
            else:
                raise RuntimeError("injected backend failure was ignored")
            check(restore_calls == ["restore"] and not session_path.exists(), "failed HF Start restores receiver context and clears session")

    return {
        "version": snapshot["version"],
        "bands": [item["id"] for item in snapshot["bands"]],
        "modes": snapshot["modes"],
        "receivers": labels,
        "backend": snapshot["backend"]["selected"],
        "receiver_authority": snapshot["authorities"]["receiver_handover"],
    }


def main() -> int:
    try:
        validate_static_boundaries()
        validate_dsp()
        validate_backend_worker()
        result = validate_runtime_and_lifecycle()
    except Exception as error:  # noqa: BLE001 - release validator
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("VALIDATION PASS: SDRCC v0.56.0b live HF Amateur Monitor")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
