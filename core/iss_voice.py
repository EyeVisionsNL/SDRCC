#!/usr/bin/env python3
"""Read-only ISS Voice foundation configuration for SDRCC v0.46.0a.

This module exposes validated metadata only. It deliberately does not reserve a
receiver, launch rtl_sdr/rtl_fm, alter Mission Queue, or start a mission.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
import os
import threading
import yaml

from core import config as config_core

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "iss_voice.yaml"
_config_write_lock = threading.RLock()
_DEFAULT_SETTINGS = {
    "gain_mode": "auto",
    "gain_db": 37.2,
    "squelch_enabled": False,
    "squelch_threshold_dbfs": -42.0,
}
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
    result = deepcopy(config)
    result.update({
        key: value
        for key, value in get_settings(result).items()
        if key != "valid_gains"
    })
    return result


def _normalize_settings(config: dict[str, Any]) -> dict[str, Any]:
    valid_gains = config_core.get_rtl_sdr_valid_gains()
    mode = str(config.get("gain_mode", _DEFAULT_SETTINGS["gain_mode"])).strip().lower()
    if mode not in {"auto", "manual"}:
        mode = _DEFAULT_SETTINGS["gain_mode"]
    try:
        gain = float(config.get("gain_db", _DEFAULT_SETTINGS["gain_db"]))
    except (TypeError, ValueError):
        gain = float(_DEFAULT_SETTINGS["gain_db"])
    if gain not in valid_gains:
        gain = min(valid_gains, key=lambda value: abs(value - gain))
    try:
        threshold = float(config.get(
            "squelch_threshold_dbfs", _DEFAULT_SETTINGS["squelch_threshold_dbfs"]
        ))
    except (TypeError, ValueError):
        threshold = float(_DEFAULT_SETTINGS["squelch_threshold_dbfs"])
    if threshold < -65.0 or threshold > -10.0:
        threshold = float(_DEFAULT_SETTINGS["squelch_threshold_dbfs"])
    return {
        "gain_mode": mode,
        "gain_db": gain,
        "squelch_enabled": bool(config.get(
            "squelch_enabled", _DEFAULT_SETTINGS["squelch_enabled"]
        )),
        "squelch_threshold_dbfs": threshold,
        "valid_gains": valid_gains,
    }


def get_settings(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return validated operator-facing ISS receiver and audio settings."""
    if config is None:
        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        config = data.get("iss_voice")
        if not isinstance(config, dict):
            raise ValueError("config/iss_voice.yaml mist een iss_voice mapping")
    return _normalize_settings(config)


def capture_gain_db(config: dict[str, Any] | None = None) -> float | None:
    """Resolve the rtl_sdr gain argument without creating receiver authority."""
    settings = get_settings(config)
    return settings["gain_db"] if settings["gain_mode"] == "manual" else None


def _as_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise ValueError(f"{field} moet true of false zijn")


def set_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist the bounded ISS settings while preserving all metadata."""
    if not isinstance(settings, dict):
        raise ValueError("ISS Voice-instellingen moeten een object zijn")
    current = get_settings()
    mode = str(settings.get("gain_mode", current["gain_mode"])).strip().lower()
    if mode not in {"auto", "manual"}:
        raise ValueError("Gain mode must be auto or manual")
    try:
        gain = float(settings.get("gain_db", current["gain_db"]))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid tuner gain") from exc
    if gain not in current["valid_gains"]:
        raise ValueError("This tuner gain is not supported by the RTL-SDR")
    squelch_enabled = _as_bool(
        settings.get("squelch_enabled", current["squelch_enabled"]),
        field="squelch_enabled",
    )
    try:
        threshold = float(settings.get(
            "squelch_threshold_dbfs", current["squelch_threshold_dbfs"]
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid squelch threshold") from exc
    if threshold < -65.0 or threshold > -10.0:
        raise ValueError("Squelch threshold must be between -65 and -10 dBFS")

    with _config_write_lock:
        document = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        config = document.get("iss_voice")
        if not isinstance(config, dict):
            raise ValueError("config/iss_voice.yaml mist een iss_voice mapping")
        config["gain_mode"] = mode
        config["gain_db"] = gain
        config["squelch_enabled"] = squelch_enabled
        config["squelch_threshold_dbfs"] = threshold
        temporary = CONFIG_FILE.with_suffix(".yaml.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(document, handle, sort_keys=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, CONFIG_FILE.stat().st_mode & 0o777)
            temporary.replace(CONFIG_FILE)
            directory_fd = os.open(CONFIG_FILE.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
    return get_settings()


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
    if not bool(config.get("execution_enabled")):
        errors.append("execution_enabled moet actief zijn")
    if not bool(config.get("receiver_claim_enabled")):
        errors.append("receiver_claim_enabled moet actief zijn")
    if not bool(config.get("planner_enabled")):
        errors.append("planner_enabled moet actief zijn")
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
    settings = get_settings(config)
    if settings["gain_mode"] == "manual" and settings["gain_db"] not in settings["valid_gains"]:
        errors.append("gain_db wordt niet door de RTL-SDR ondersteund")
    if not -65.0 <= settings["squelch_threshold_dbfs"] <= -10.0:
        errors.append("squelch_threshold_dbfs buiten veilige grenzen")

    return {"ok": not errors, "errors": errors, "config": deepcopy(config)}


def get_status() -> dict[str, Any]:
    validation = validate_config()
    return {
        "ok": validation["ok"],
        "version": "0.54.0g",
        "foundation_only": False,
        "backend_only": False,
        "read_only": False,
        "planner_enabled": bool((validation.get("config") or {}).get("planner_enabled")),
        "execution_enabled": bool((validation.get("config") or {}).get("execution_enabled")),
        "receiver_claim_enabled": bool((validation.get("config") or {}).get("receiver_claim_enabled")),
        "offline_demodulation_enabled": bool((validation.get("config") or {}).get("offline_demodulation_enabled")),
        "settings": get_settings(validation.get("config") or {}) if validation.get("config") else None,
        "validation": validation,
    }
