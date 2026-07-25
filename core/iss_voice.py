#!/usr/bin/env python3
"""Read-only ISS Voice foundation configuration for SDRCC v0.46.0a.

This module exposes validated metadata only. It deliberately does not reserve a
receiver, launch rtl_sdr/rtl_fm, alter Mission Queue, or start a mission.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import yaml

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "iss_voice.yaml"
_REQUIRED = {
    "enabled", "profile", "mission_type", "satellite_name", "norad_id",
    "downlink_frequency_hz", "modulation", "doppler_tracking",
    "capture_strategy", "rf_sample_rate_hz", "doppler_guard_hz",
    "channel_bandwidth_hz", "audio_sample_rate_hz", "audio_channels",
    "iq_sample_format", "iq_filename", "metadata_filename",
    "output_format", "minimum_elevation", "execution_backend_enabled", "execution_enabled",
    "receiver_claim_enabled", "planner_enabled", "controlled_capture_enabled",
    "controlled_capture_max_seconds", "offline_demodulation_enabled",
    "audio_filename", "audio_deemphasis_us",
}


def get_config() -> dict[str, Any]:
    data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    config = data.get("iss_voice")
    if not isinstance(config, dict):
        raise ValueError("config/iss_voice.yaml mist een iss_voice mapping")
    return deepcopy(config)


def validate_config() -> dict[str, Any]:
    errors: list[str] = []
    try:
        config = get_config()
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)], "config": None}

    missing = sorted(_REQUIRED - set(config))
    if missing:
        errors.append("Ontbrekende velden: " + ", ".join(missing))
    if config.get("mission_type") != "iss_voice":
        errors.append("mission_type moet iss_voice zijn")
    if int(config.get("downlink_frequency_hz") or 0) != 437800000:
        errors.append("eerste profiel moet 437800000 Hz gebruiken")
    if config.get("capture_strategy") != "wideband_iq":
        errors.append("capture_strategy moet wideband_iq zijn")
    if not bool(config.get("doppler_tracking")):
        errors.append("doppler_tracking moet actief zijn")
    if not bool(config.get("execution_backend_enabled")):
        errors.append("execution_backend_enabled moet actief zijn")
    if bool(config.get("execution_enabled")):
        errors.append("execution_enabled moet in foundation false zijn")
    if bool(config.get("receiver_claim_enabled")):
        errors.append("receiver_claim_enabled moet in foundation false zijn")
    if bool(config.get("planner_enabled")):
        errors.append("planner_enabled moet in foundation false zijn")
    if not bool(config.get("controlled_capture_enabled")):
        errors.append("controlled_capture_enabled moet actief zijn")
    if not bool(config.get("offline_demodulation_enabled")):
        errors.append("offline_demodulation_enabled moet actief zijn")
    if not str(config.get("audio_filename") or "").endswith(".wav"):
        errors.append("audio_filename moet een WAV-bestand zijn")
    deemphasis = float(config.get("audio_deemphasis_us") or 0)
    if deemphasis <= 0 or deemphasis > 1000:
        errors.append("audio_deemphasis_us buiten veilige grenzen")
    controlled_max = int(config.get("controlled_capture_max_seconds") or 0)
    if controlled_max < 1 or controlled_max > 30:
        errors.append("controlled_capture_max_seconds moet 1..30 zijn")
    if int(config.get("rf_sample_rate_hz") or 0) < 100000:
        errors.append("rf_sample_rate_hz is te laag voor brede capture")
    if int(config.get("doppler_guard_hz") or 0) < 10000:
        errors.append("doppler_guard_hz moet minimaal 10000 Hz zijn")

    return {"ok": not errors, "errors": errors, "config": deepcopy(config)}


def get_status() -> dict[str, Any]:
    validation = validate_config()
    return {
        "ok": validation["ok"],
        "version": "0.46.0d",
        "foundation_only": False,
        "backend_only": True,
        "read_only": True,
        "planner_enabled": False,
        "execution_enabled": False,
        "receiver_claim_enabled": False,
        "offline_demodulation_enabled": bool((validation.get("config") or {}).get("offline_demodulation_enabled")),
        "validation": validation,
    }
