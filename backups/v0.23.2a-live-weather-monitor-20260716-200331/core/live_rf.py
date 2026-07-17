#!/usr/bin/env python3

"""Live RF telemetry state for active SatDump missions."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "state" / "live_rf.json"

_LOCK = threading.RLock()

_DEFAULT_STATE: dict[str, Any] = {
    "active": False,
    "state": "IDLE",
    "satellite": None,
    "receiver": None,
    "serial": None,
    "frequency_hz": None,
    "sample_rate": None,
    "gain_mode": None,
    "gain_db": None,
    "dc_block": False,
    "iq_swap": False,
    "pid": None,
    "output_path": None,
    "timeout_seconds": None,
    "started_at": None,
    "started_epoch": None,
    "ended_at": None,
    "elapsed_seconds": 0,
    "remaining_seconds": None,
    "snr_db": None,
    "peak_snr_db": None,
    "ber": None,
    "viterbi": "UNKNOWN",
    "deframer": "UNKNOWN",
    "frames": 0,
    "cadu_bytes": 0,
    "image_count": 0,
    "last_line": None,
    "result": None,
    "detail": None,
    "updated_at": None,
}

_STATE = dict(_DEFAULT_STATE)

_SNR_RE = re.compile(
    r"SNR\s*:\s*(-?\d+(?:\.\d+)?)\s*dB\s*,?\s*Peak SNR\s*:\s*(-?\d+(?:\.\d+)?)\s*dB",
    re.IGNORECASE,
)
_DECODER_RE = re.compile(
    r"Viterbi\s*:\s*([A-Z]+)\s+BER\s*:\s*(-?\d+(?:\.\d+)?)\s*,?\s*Deframer\s*:\s*([A-Z]+)",
    re.IGNORECASE,
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _save_locked() -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(_STATE, indent=2, ensure_ascii=False) + "\n")
    temp.replace(STATE_FILE)


def _output_metrics(output_path: str | None) -> tuple[int, int, int]:
    if not output_path:
        return 0, 0, 0

    root = Path(output_path)
    if not root.exists():
        return 0, 0, 0

    cadu_bytes = sum(
        item.stat().st_size
        for item in root.rglob("*.cadu")
        if item.is_file()
    )
    image_count = sum(
        1
        for pattern in ("*.png", "*.jpg", "*.jpeg")
        for item in root.rglob(pattern)
        if item.is_file()
    )
    return cadu_bytes // 8192, cadu_bytes, image_count


def start(record_data: dict[str, Any], pid: int) -> dict[str, Any]:
    pass_data = record_data.get("pass") or {}
    device = record_data.get("device") or {}
    rf = record_data.get("rf") or {}

    now_epoch = time.time()
    with _LOCK:
        _STATE.clear()
        _STATE.update(_DEFAULT_STATE)
        _STATE.update({
            "active": True,
            "state": "RECORDING",
            "satellite": pass_data.get("name"),
            "receiver": device.get("number") or device.get("id"),
            "serial": device.get("serial"),
            "frequency_hz": pass_data.get("frequency"),
            "sample_rate": pass_data.get("sample_rate"),
            "gain_mode": rf.get("gain_mode"),
            "gain_db": rf.get("gain_db"),
            "dc_block": bool(rf.get("dc_block")),
            "iq_swap": bool(rf.get("iq_swap")),
            "pid": pid,
            "output_path": str(record_data.get("output_path") or ""),
            "timeout_seconds": record_data.get("timeout_seconds"),
            "started_at": _now_text(),
            "started_epoch": now_epoch,
            "updated_at": _now_text(),
        })
        _save_locked()
        return dict(_STATE)


def update_line(line: str) -> None:
    clean = line.strip()
    if not clean:
        return

    with _LOCK:
        _STATE["last_line"] = clean
        _STATE["updated_at"] = _now_text()

        match = _SNR_RE.search(clean)
        if match:
            _STATE["snr_db"] = float(match.group(1))
            reported_peak = float(match.group(2))
            current_peak = _STATE.get("peak_snr_db")
            _STATE["peak_snr_db"] = (
                reported_peak
                if current_peak is None
                else max(float(current_peak), reported_peak)
            )

        match = _DECODER_RE.search(clean)
        if match:
            _STATE["viterbi"] = match.group(1).upper()
            _STATE["ber"] = float(match.group(2))
            _STATE["deframer"] = match.group(3).upper()

        _save_locked()


def finish(result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = result or {}
    with _LOCK:
        _refresh_runtime_locked()
        _STATE.update({
            "active": False,
            "state": "COMPLETE",
            "ended_at": _now_text(),
            "result": result.get("result"),
            "detail": result.get("detail"),
            "peak_snr_db": result.get("peak_snr_db", _STATE.get("peak_snr_db")),
            "frames": result.get("frames", _STATE.get("frames", 0)),
            "cadu_bytes": result.get("cadu_bytes", _STATE.get("cadu_bytes", 0)),
            "image_count": result.get("image_count", _STATE.get("image_count", 0)),
            "remaining_seconds": 0,
            "updated_at": _now_text(),
        })
        _save_locked()
        return dict(_STATE)


def fail(detail: str) -> dict[str, Any]:
    return finish({"result": "FAILED", "detail": detail})


def _refresh_runtime_locked() -> None:
    started_epoch = _STATE.get("started_epoch")
    if started_epoch:
        elapsed = max(0, int(time.time() - float(started_epoch)))
        _STATE["elapsed_seconds"] = elapsed
        timeout = _STATE.get("timeout_seconds")
        if timeout is not None:
            _STATE["remaining_seconds"] = max(0, int(timeout) - elapsed)

    frames, cadu_bytes, image_count = _output_metrics(_STATE.get("output_path"))
    _STATE["frames"] = frames
    _STATE["cadu_bytes"] = cadu_bytes
    _STATE["image_count"] = image_count


def get_status() -> dict[str, Any]:
    with _LOCK:
        _refresh_runtime_locked()
        return dict(_STATE)
