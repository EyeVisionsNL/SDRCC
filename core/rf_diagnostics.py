#!/usr/bin/env python3

import csv
import io
import subprocess
import time
from threading import Lock

from core import config as config_core
from core.device_manager import get_conflicting_service, get_weather_device

_SCAN_LOCK = Lock()


def _service_is_active(service):
    result = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True)
    return result.stdout.strip() == "active"


def _service_action(service, action):
    result = subprocess.run(
        ["sudo", "-n", "systemctl", action, service],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"{action} {service} mislukt")


def _parse_rtl_power(output):
    points = []
    for raw in output.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith('#'):
            continue
        row = next(csv.reader(io.StringIO(raw)))
        if len(row) < 7:
            continue
        low = float(row[2])
        high = float(row[3])
        step = float(row[4])
        values = []
        for value in row[6:]:
            try:
                values.append(float(value))
            except ValueError:
                pass
        for index, dbm in enumerate(values):
            freq = low + (index + 0.5) * step
            if freq <= high + step:
                points.append({"frequency_hz": round(freq), "dbm": round(dbm, 2)})
    if not points:
        raise RuntimeError("rtl_power leverde geen spectrumdata")
    points.sort(key=lambda item: item["frequency_hz"])
    peak = max(points, key=lambda item: item["dbm"])
    floor_values = sorted(item["dbm"] for item in points)
    noise = floor_values[max(0, len(floor_values)//4 - 1)]
    return points, peak, round(noise, 2)


def scan_spectrum(center_hz, mission_busy=False):
    if mission_busy:
        raise RuntimeError("Spectrumscan is geblokkeerd tijdens voorbereiding of opname")
    if not _SCAN_LOCK.acquire(blocking=False):
        raise RuntimeError("Er draait al een spectrumscan")
    device = get_weather_device()
    if not device:
        _SCAN_LOCK.release()
        raise RuntimeError("Geen Weather-ontvanger toegewezen")
    rf = config_core.get_weather_rf_config()
    span = max(200000, min(int(rf["spectrum_span_hz"]), 2400000))
    bin_hz = max(1000, min(int(rf["spectrum_bin_hz"]), 100000))
    low = int(center_hz - span / 2)
    high = int(center_hz + span / 2)
    service = get_conflicting_service(device["id"])
    restore = bool(service and _service_is_active(service))
    try:
        if restore:
            _service_action(service, "stop")
            deadline = time.monotonic() + 10
            while _service_is_active(service) and time.monotonic() < deadline:
                time.sleep(0.25)
            time.sleep(1)
        cmd = [
            "rtl_power", "-f", f"{low}:{high}:{bin_hz}",
            "-i", "1", "-1", "-d", str(device["serial"]),
            "-w", "blackman-harris", "-c", "20", "-",
        ]
        if rf["gain_mode"] == "manual":
            cmd[1:1] = ["-g", str(rf["gain_db"])]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "rtl_power is mislukt")
        points, peak, noise = _parse_rtl_power(result.stdout)
        return {
            "device": device, "center_hz": int(center_hz), "span_hz": span,
            "bin_hz": bin_hz, "gain_mode": rf["gain_mode"],
            "gain_db": rf["gain_db"] if rf["gain_mode"] == "manual" else None,
            "points": points, "peak": peak, "noise_floor_dbm": noise,
            "signal_above_noise_db": round(peak["dbm"] - noise, 2),
        }
    finally:
        if restore and service:
            try:
                _service_action(service, "start")
            except Exception:
                pass
        _SCAN_LOCK.release()
