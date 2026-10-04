#!/usr/bin/env python3
"""One-shot, Doppler-aware tuner gain selection for ISS IQ recordings.

This resolver is called only after the caller has reserved the receiver and
completed its service handover. It never manages receiver or service authority.
"""
from __future__ import annotations

from typing import Any

from core import config as config_core
from core import iss_voice


ISS_PROBE_BANDWIDTH_HZ = 50_000
ISS_MINIMUM_SNR_DB = 4.0
ISS_SUPPORTED_PROBE_SAMPLE_RATE_HZ = 240_000
ISS_CLIPPING_FRACTION_LIMIT = 0.01


def resolve_capture_gain(
    *,
    config: dict[str, Any],
    receiver_serial: str,
    frequency_hz: int,
    sample_rate_hz: int,
) -> dict[str, Any]:
    """Resolve Auto, Smart or Manual into one fixed gain for an IQ capture.

    Smart mode makes one short measurement at the capture center frequency.
    A clear measurement selects a bounded gain for the whole capture. An
    unclear/failed probe uses the operator-selected gain as its safe fallback.
    """
    settings = iss_voice.get_settings(config)
    mode = settings["gain_mode"]
    fallback_gain_db = float(settings["gain_db"])
    if mode == "auto":
        return {
            "gain_mode": "auto",
            "gain_db": None,
            "smart_gain": None,
        }
    if mode == "manual":
        return {
            "gain_mode": "manual",
            "gain_db": fallback_gain_db,
            "smart_gain": None,
        }

    supported = config_core.get_rtl_sdr_valid_gains()
    if fallback_gain_db not in supported:
        fallback_gain_db = min(supported, key=lambda value: abs(value - fallback_gain_db))

    details: dict[str, Any] = {
        "enabled": True,
        "source": "configured_fallback",
        "selected_gain_db": fallback_gain_db,
        "fallback_gain_db": fallback_gain_db,
        "probe_frequency_hz": int(frequency_hz),
        "probe_sample_rate_hz": int(sample_rate_hz),
        "probe_bandwidth_hz": ISS_PROBE_BANDWIDTH_HZ,
        "minimum_snr_db": ISS_MINIMUM_SNR_DB,
        "measurement": None,
        "fallback_reason": None,
    }
    if int(sample_rate_hz) != ISS_SUPPORTED_PROBE_SAMPLE_RATE_HZ:
        details["fallback_reason"] = "unsupported_probe_sample_rate"
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    try:
        # Import lazily so settings/status validation never opens or probes a
        # receiver. Receiver Manager already owns the reservation at this call.
        from core.hf_monitor_backend import probe_smart_gain_for_channels

        probe = probe_smart_gain_for_channels(
            serial=str(receiver_serial),
            frequencies_hz=[int(frequency_hz)],
            minimum_snr_db=ISS_MINIMUM_SNR_DB,
            channel_bandwidth_hz=ISS_PROBE_BANDWIDTH_HZ,
        )
    except Exception as exc:
        details["fallback_reason"] = "probe_error"
        details["probe_error"] = str(exc)[:500]
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    measurement = probe.get("measurement")
    details["probe"] = probe
    details["measurement"] = measurement
    if not isinstance(measurement, dict):
        details["fallback_reason"] = "no_clear_signal"
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    try:
        selected_gain_db = float(probe["gain_db"])
        if selected_gain_db not in supported:
            raise ValueError("Smart Gain selected an unsupported tuner step")
    except (KeyError, TypeError, ValueError):
        details["fallback_reason"] = "invalid_probe_gain"
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    clipping_fraction = float(measurement.get("clip_fraction") or 0.0)
    if clipping_fraction >= ISS_CLIPPING_FRACTION_LIMIT:
        selected_gain_db = min(selected_gain_db, fallback_gain_db)
        details["source"] = "smart_probe_clipping_guard"
        details["fallback_reason"] = "input_clipping"
    else:
        details["source"] = "smart_probe"
    details["selected_gain_db"] = selected_gain_db
    return {"gain_mode": "smart", "gain_db": selected_gain_db, "smart_gain": details}
