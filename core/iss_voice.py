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
    "output_format", "minimum_elevation", "execution_enabled",
    "receiver_claim_enabled", "planner_enabled",
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
    if bool(config.get("execution_enabled")):
        errors.append("execution_enabled moet in foundation false zijn")
    if bool(config.get("receiver_claim_enabled")):
        errors.append("receiver_claim_enabled moet in foundation false zijn")
    if bool(config.get("planner_enabled")):
        errors.append("planner_enabled moet in foundation false zijn")
    if int(config.get("rf_sample_rate_hz") or 0) < 100000:
        errors.append("rf_sample_rate_hz is te laag voor brede capture")
    if int(config.get("doppler_guard_hz") or 0) < 10000:
        errors.append("doppler_guard_hz moet minimaal 10000 Hz zijn")

    return {"ok": not errors, "errors": errors, "config": deepcopy(config)}


def get_status() -> dict[str, Any]:
    validation = validate_config()
    return {
        "ok": validation["ok"],
        "version": "0.46.0a",
        "foundation_only": True,
        "read_only": True,
        "planner_enabled": False,
        "execution_enabled": False,
        "receiver_claim_enabled": False,
        "validation": validation,
    }
