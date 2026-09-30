"""Bounded, one-shot RTL-SDR gain selection for SDRCC voice monitoring.

Smart Gain takes a short IQ sample at a conservative 12.5 dB reference,
estimates the tuned channel's signal-to-noise ratio, and chooses one supported
fixed tuner gain.  The selected gain stays fixed for the listening session.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np


REFERENCE_GAIN_DB = 12.5
MIN_SMART_GAIN_DB = 0.0
MAX_SMART_GAIN_DB = 25.4
TARGET_CHANNEL_DBFS = -28.0
DEFAULT_SIGNAL_SNR_DB = 4.0
MAX_PROBE_CHANNELS = 12


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def supported_smart_gains(gains_db: Iterable[float]) -> list[float]:
    """Return unique supported steps inside Smart Gain's conservative range."""
    values = sorted({
        round(number, 1)
        for raw in gains_db
        if (number := _finite(raw)) is not None
        and MIN_SMART_GAIN_DB <= number <= MAX_SMART_GAIN_DB
    })
    if not values:
        raise ValueError("RTL-SDR does not expose a gain step in Smart Gain's safe range")
    return values


def closest_gain(gains_db: Iterable[float], target_db: float) -> float:
    gains = supported_smart_gains(gains_db)
    target = min(MAX_SMART_GAIN_DB, max(MIN_SMART_GAIN_DB, float(target_db)))
    return min(gains, key=lambda value: (abs(value - target), value))


def analyze_iq_samples(
    payload: bytes,
    *,
    sample_rate_hz: int,
    channel_bandwidth_hz: int = 20_000,
) -> dict[str, float]:
    """Measure tuned-channel power and adjacent noise from unsigned RTL IQ."""
    usable = len(payload) - (len(payload) % 2)
    if usable < 8192:
        raise ValueError("Smart Gain needs at least 4096 complex IQ samples")
    sample_rate = int(sample_rate_hz)
    bandwidth = int(channel_bandwidth_hz)
    if sample_rate <= 0 or bandwidth <= 0 or bandwidth >= sample_rate * 0.4:
        raise ValueError("Smart Gain sample rate or channel bandwidth is invalid")

    raw = np.frombuffer(payload[:usable], dtype=np.uint8).astype(np.float64)
    i_samples = (raw[0::2] - 127.5) / 127.5
    q_samples = (raw[1::2] - 127.5) / 127.5
    iq = i_samples + 1j * q_samples
    iq -= np.mean(iq)

    window = np.hanning(len(iq))
    transformed = np.fft.fftshift(np.fft.fft(iq * window))
    power = (np.abs(transformed) ** 2) / max(float(np.sum(window) ** 2), 1e-18)
    frequency = np.fft.fftshift(np.fft.fftfreq(len(iq), d=1.0 / sample_rate))
    offset = np.abs(frequency)
    channel = offset <= bandwidth / 2.0
    noise = (
        (offset >= bandwidth * 1.5)
        & (offset <= min(sample_rate * 0.45, bandwidth * 5.0))
    )
    if int(np.count_nonzero(channel)) < 4 or int(np.count_nonzero(noise)) < 8:
        raise ValueError("Smart Gain could not form a channel/noise measurement")

    signal_power = float(np.sum(power[channel]))
    noise_power = float(np.median(power[noise]) * np.count_nonzero(channel))
    signal_dbfs = 10.0 * math.log10(max(signal_power, 1e-18))
    noise_dbfs = 10.0 * math.log10(max(noise_power, 1e-18))
    rms = float(np.sqrt(np.mean(np.abs(iq) ** 2)))
    return {
        "signal_dbfs": round(signal_dbfs, 2),
        "noise_dbfs": round(noise_dbfs, 2),
        "snr_db": round(signal_dbfs - noise_dbfs, 2),
        "iq_rms_dbfs": round(20.0 * math.log10(max(rms, 1e-12)), 2),
    }


def choose_smart_gain_db(
    measurement: dict[str, Any],
    gains_db: Iterable[float],
    *,
    minimum_snr_db: float = DEFAULT_SIGNAL_SNR_DB,
) -> float:
    """Choose a bounded fixed gain; keep 12.5 dB when signal is not distinct."""
    gains = supported_smart_gains(gains_db)
    reference = min(gains, key=lambda value: (abs(value - REFERENCE_GAIN_DB), value))
    signal_dbfs = _finite(measurement.get("signal_dbfs"))
    snr_db = _finite(measurement.get("snr_db"))
    if signal_dbfs is None or snr_db is None or snr_db < float(minimum_snr_db):
        return reference

    # Move toward the target channel level only when a real channel stands
    # above the measured noise.  Clamp both directions so one noisy probe
    # cannot command maximum RTL gain.
    adjustment = max(-12.5, min(8.2, TARGET_CHANNEL_DBFS - signal_dbfs))
    target = min(
        MAX_SMART_GAIN_DB,
        max(MIN_SMART_GAIN_DB, REFERENCE_GAIN_DB + adjustment),
    )
    return min(gains, key=lambda value: (abs(value - target), value))


def choose_for_measurements(
    measurements: list[dict[str, Any]],
    gains_db: Iterable[float],
    *,
    minimum_snr_db: float = DEFAULT_SIGNAL_SNR_DB,
) -> tuple[float, dict[str, float] | None]:
    """Select against the strongest clear measured channel, or use the reference."""
    gains = supported_smart_gains(gains_db)
    clear = [
        item for item in measurements
        if (_finite(item.get("snr_db")) is not None)
        and float(item["snr_db"]) >= float(minimum_snr_db)
    ]
    if not clear:
        reference = min(gains, key=lambda value: (abs(value - REFERENCE_GAIN_DB), value))
        return reference, None
    strongest = max(
        clear,
        key=lambda item: _finite(item.get("signal_dbfs"))
        if _finite(item.get("signal_dbfs")) is not None else -math.inf,
    )
    return choose_smart_gain_db(
        strongest, gains, minimum_snr_db=minimum_snr_db,
    ), {key: float(value) for key, value in strongest.items()}
