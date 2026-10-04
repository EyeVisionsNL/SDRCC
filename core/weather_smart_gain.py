"""One-shot Smart Gain selection for Weather / METEOR recordings.

The caller must first reserve and activate the Weather receiver. This module
only measures the tuned RF channel; it never changes service or receiver
ownership. The selected tuner gain is held fixed for the complete SatDump pass.
"""
from __future__ import annotations

import math
from typing import Any

from core import config as config_core


WEATHER_PROBE_BANDWIDTH_HZ = 120_000
WEATHER_MINIMUM_SNR_DB = 4.0
WEATHER_CLIPPING_FRACTION_LIMIT = 0.01
WEATHER_MAXIMUM_PROBE_SAMPLE_RATE_HZ = 3_200_000


def _supported_fallback_gain(value: Any, supported: list[float]) -> float:
    try:
        requested = float(value)
    except (TypeError, ValueError):
        requested = 38.6
    if not math.isfinite(requested):
        requested = 38.6
    return min(supported, key=lambda gain: (abs(gain - requested), gain))


def resolve_capture_gain(
    *,
    settings: dict[str, Any],
    receiver_serial: str,
    frequency_hz: int,
    sample_rate_hz: int,
) -> dict[str, Any]:
    """Resolve Auto, Smart or Manual to a single fixed capture gain.

    Smart mode probes only after the receiver handover, at the exact Weather
    pass frequency and sample rate. An unclear or failed probe retains the
    operator's configured tuner gain as the fallback.
    """
    mode = str(settings.get("gain_mode") or "auto").strip().lower()
    if mode not in {"auto", "smart", "manual"}:
        mode = "auto"

    supported = list(config_core.get_rtl_sdr_valid_gains())
    if not supported:
        raise RuntimeError("RTL-SDR tuner did not report any supported gain")
    fallback_gain_db = _supported_fallback_gain(settings.get("gain_db"), supported)

    if mode == "auto":
        return {"gain_mode": "auto", "gain_db": fallback_gain_db, "smart_gain": None}
    if mode == "manual":
        return {"gain_mode": "manual", "gain_db": fallback_gain_db, "smart_gain": None}

    sample_rate = int(sample_rate_hz)
    probe_bandwidth = min(
        WEATHER_PROBE_BANDWIDTH_HZ,
        int(sample_rate * 0.25),
    ) if sample_rate > 0 else 0
    maximum_gain_db = max(supported)
    details: dict[str, Any] = {
        "enabled": True,
        "source": "configured_fallback",
        "selected_gain_db": fallback_gain_db,
        "fallback_gain_db": fallback_gain_db,
        "probe_frequency_hz": int(frequency_hz),
        "probe_sample_rate_hz": sample_rate,
        "probe_bandwidth_hz": probe_bandwidth,
        "minimum_snr_db": WEATHER_MINIMUM_SNR_DB,
        "maximum_gain_db": maximum_gain_db,
        "measurement": None,
        "fallback_reason": None,
    }

    if (
        sample_rate <= 0
        or sample_rate > WEATHER_MAXIMUM_PROBE_SAMPLE_RATE_HZ
        or probe_bandwidth < 20_000
        or probe_bandwidth >= sample_rate * 0.4
    ):
        details["fallback_reason"] = "unsupported_probe_configuration"
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    try:
        # The receiver has already been handed over by Receiver Manager.
        from core.hf_monitor_backend import probe_smart_gain_for_channels

        probe = probe_smart_gain_for_channels(
            serial=str(receiver_serial),
            frequencies_hz=[int(frequency_hz)],
            minimum_snr_db=WEATHER_MINIMUM_SNR_DB,
            channel_bandwidth_hz=probe_bandwidth,
            sample_rate_hz=sample_rate,
            reference_gain_db=fallback_gain_db,
            maximum_gain_db=maximum_gain_db,
        )
    except Exception as exc:
        details["fallback_reason"] = "probe_error"
        details["probe_error"] = str(exc)[:500]
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    details["probe"] = probe
    measurement = probe.get("measurement") if isinstance(probe, dict) else None
    details["measurement"] = measurement
    try:
        measured_snr = float(measurement["snr_db"])
        signal_dbfs = float(measurement["signal_dbfs"])
        selected_gain_db = float(probe["gain_db"])
        if (
            not math.isfinite(measured_snr)
            or not math.isfinite(signal_dbfs)
            or measured_snr < WEATHER_MINIMUM_SNR_DB
            or selected_gain_db not in supported
        ):
            raise ValueError("Probe did not return a clear supported gain")
    except (KeyError, TypeError, ValueError):
        details["fallback_reason"] = "no_clear_signal"
        return {"gain_mode": "smart", "gain_db": fallback_gain_db, "smart_gain": details}

    try:
        clipping_fraction = float(measurement.get("clip_fraction") or 0.0)
    except (TypeError, ValueError):
        clipping_fraction = 1.0
    if not math.isfinite(clipping_fraction):
        clipping_fraction = 1.0
    if clipping_fraction >= WEATHER_CLIPPING_FRACTION_LIMIT:
        # Stay at least about 6 dB below the probe reference when the tuner
        # supports that step, and never raise gain above the configured fallback.
        safer_steps = [gain for gain in supported if gain <= fallback_gain_db - 6.0]
        if safer_steps:
            selected_gain_db = min(selected_gain_db, max(safer_steps))
        else:
            selected_gain_db = min(selected_gain_db, min(supported))
        details["source"] = "smart_probe_clipping_guard"
        details["fallback_reason"] = "input_clipping"
    else:
        details["source"] = "smart_probe"

    details["selected_gain_db"] = selected_gain_db
    return {"gain_mode": "smart", "gain_db": selected_gain_db, "smart_gain": details}
