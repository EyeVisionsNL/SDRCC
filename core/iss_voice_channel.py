#!/usr/bin/env python3
"""Shared streaming ISS Doppler, channel-filter and NFM decoder."""
from __future__ import annotations

from typing import Any, Callable
import math

import numpy as np

from core.iss_voice_squelch import RfPowerSquelch


OffsetProvider = Callable[[float], float]


def _lowpass(taps: int, cutoff_hz: float, sample_rate_hz: int) -> np.ndarray:
    if taps < 17 or taps % 2 == 0:
        raise ValueError("Kanaalfilter moet een oneven aantal van minimaal 17 taps hebben")
    normalized = float(cutoff_hz) / float(sample_rate_hz)
    if normalized <= 0.0 or normalized >= 0.5:
        raise ValueError("Ongeldige kanaalfilter-cutoff")
    indices = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
    coefficients = 2.0 * normalized * np.sinc(2.0 * normalized * indices)
    coefficients *= np.hamming(taps)
    coefficients /= np.sum(coefficients)
    return coefficients.astype(np.float32)


class NfmChannelDecoder:
    """Convert CU8 wideband IQ to PCM16 using one production DSP chain."""

    def __init__(self, *, rf_sample_rate_hz: int, audio_sample_rate_hz: int,
                 channel_bandwidth_hz: int, deemphasis_us: float,
                 capture_start_epoch: float, doppler_offset_provider: OffsetProvider,
                 initial_sample_index: int = 0, squelch_enabled: bool = False,
                 squelch_threshold_dbfs: float = -42.0, filter_taps: int = 65) -> None:
        self.rf_rate = int(rf_sample_rate_hz)
        self.audio_rate = int(audio_sample_rate_hz)
        self.bandwidth = int(channel_bandwidth_hz)
        self.capture_start_epoch = float(capture_start_epoch)
        self.offset_provider = doppler_offset_provider
        if self.rf_rate % self.audio_rate != 0:
            raise ValueError("RF sample rate moet exact deelbaar zijn door audio sample rate")
        self.factor = self.rf_rate // self.audio_rate
        if self.factor < 2:
            raise ValueError("Ongeldige decimatiefactor")
        self.filter_cutoff_hz = self.bandwidth * 0.45
        if self.filter_cutoff_hz >= self.audio_rate / 2.0:
            raise ValueError("Kanaalbandbreedte past niet binnen de audio sample rate")
        self.filter_taps = int(filter_taps)
        self._fir = _lowpass(self.filter_taps, self.filter_cutoff_hz, self.rf_rate)
        self._fir_state = np.zeros(self.filter_taps - 1, dtype=np.complex64)
        self.sample_index = max(0, int(initial_sample_index))
        self._nco_phase = 0.0
        self._previous_channel_iq: complex | None = None
        tau = float(deemphasis_us) / 1_000_000.0
        if tau <= 0.0:
            raise ValueError("Ongeldige de-emphasis")
        self._deemphasis_alpha = math.exp(-1.0 / (self.audio_rate * tau))
        self._deemphasis_previous = 0.0
        self._dc_previous_input = 0.0
        self._dc_previous_output = 0.0
        self._level = 0.08
        self._offset_min: float | None = None
        self._offset_max: float | None = None
        self._offset_current: float | None = None
        self._wideband_power_sum = 0.0
        self._channel_power_sum = 0.0
        self._power_samples = 0
        self.squelch = RfPowerSquelch(
            rf_sample_rate_hz=self.audio_rate,
            audio_sample_rate_hz=self.audio_rate,
            enabled=bool(squelch_enabled),
            threshold_dbfs=float(squelch_threshold_dbfs),
        )

    @staticmethod
    def _cu8(raw: bytes) -> np.ndarray:
        usable = len(raw) - len(raw) % 2
        if usable < 4:
            return np.empty(0, dtype=np.complex64)
        values = np.frombuffer(raw[:usable], dtype=np.uint8)
        i = (values[0::2].astype(np.float32) - 127.5) / 127.5
        q = (values[1::2].astype(np.float32) - 127.5) / 127.5
        return (i + 1j * q).astype(np.complex64)

    def _correct_doppler(self, iq: np.ndarray) -> np.ndarray:
        count = int(iq.size)
        start_epoch = self.capture_start_epoch + self.sample_index / self.rf_rate
        end_epoch = self.capture_start_epoch + (self.sample_index + max(0, count - 1)) / self.rf_rate
        start_offset = float(self.offset_provider(start_epoch))
        end_offset = float(self.offset_provider(end_epoch))
        offsets = np.linspace(start_offset, end_offset, count, dtype=np.float64)
        phase_steps = 2.0 * math.pi * offsets / self.rf_rate
        phases = self._nco_phase + np.cumsum(phase_steps) - phase_steps[0]
        corrected = iq * np.exp(-1j * phases).astype(np.complex64)
        self._nco_phase = float((phases[-1] + phase_steps[-1]) % (2.0 * math.pi))
        self._offset_current = end_offset
        local_min, local_max = float(np.min(offsets)), float(np.max(offsets))
        self._offset_min = local_min if self._offset_min is None else min(self._offset_min, local_min)
        self._offset_max = local_max if self._offset_max is None else max(self._offset_max, local_max)
        return corrected

    def _channelize(self, corrected: np.ndarray) -> np.ndarray:
        extended = np.concatenate((self._fir_state, corrected))
        filtered = np.convolve(extended, self._fir, mode="valid").astype(np.complex64)
        self._fir_state = extended[-(self.filter_taps - 1):].copy()
        first = (-self.sample_index) % self.factor
        return filtered[first::self.factor]

    def _audio(self, channel_iq: np.ndarray) -> np.ndarray:
        if channel_iq.size == 0:
            return np.empty(0, dtype=np.float32)
        if self._previous_channel_iq is not None:
            with_previous = np.concatenate((
                np.asarray([self._previous_channel_iq], dtype=np.complex64), channel_iq
            ))
        else:
            with_previous = channel_iq
        self._previous_channel_iq = complex(channel_iq[-1])
        if with_previous.size < 2:
            return np.empty(0, dtype=np.float32)
        audio = np.angle(with_previous[1:] * np.conj(with_previous[:-1])).astype(np.float32)

        previous = self._deemphasis_previous
        dc_in = self._dc_previous_input
        dc_out = self._dc_previous_output
        alpha = self._deemphasis_alpha
        for index in range(audio.size):
            previous = alpha * previous + (1.0 - alpha) * float(audio[index])
            high_pass = previous - dc_in + 0.995 * dc_out
            dc_in, dc_out = previous, high_pass
            audio[index] = high_pass
        self._deemphasis_previous = previous
        self._dc_previous_input = dc_in
        self._dc_previous_output = dc_out
        return self.squelch.process(channel_iq, audio)

    def process_float(self, raw: bytes) -> np.ndarray:
        iq = self._cu8(raw)
        if iq.size == 0:
            return np.empty(0, dtype=np.float32)
        wideband_power = float(np.mean(np.square(np.abs(iq)), dtype=np.float64))
        corrected = self._correct_doppler(iq)
        channel_iq = self._channelize(corrected)
        channel_power = (
            float(np.mean(np.square(np.abs(channel_iq)), dtype=np.float64))
            if channel_iq.size else 0.0
        )
        self._wideband_power_sum += wideband_power * iq.size
        self._channel_power_sum += channel_power * iq.size
        self._power_samples += int(iq.size)
        audio = self._audio(channel_iq)
        self.sample_index += int(iq.size)
        return audio

    def process_pcm16(self, raw: bytes) -> bytes:
        audio = self.process_float(raw)
        if audio.size == 0:
            return b""
        block_peak = float(np.percentile(np.abs(audio), 98.0))
        self._level = max(block_peak, self._level * 0.985, 0.015)
        gain = min(18.0, 0.55 / self._level)
        pcm = np.tanh(audio * gain * 1.35)
        return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()

    def status(self) -> dict[str, Any]:
        wideband = self._wideband_power_sum / self._power_samples if self._power_samples else 0.0
        channel = self._channel_power_sum / self._power_samples if self._power_samples else 0.0
        ratio_db = 10.0 * math.log10(max(channel, 1e-12) / max(wideband, 1e-12))
        return {
            "doppler_correction_enabled": True,
            "doppler_offset_hz": round(self._offset_current, 2) if self._offset_current is not None else None,
            "doppler_min_hz": round(self._offset_min, 2) if self._offset_min is not None else None,
            "doppler_max_hz": round(self._offset_max, 2) if self._offset_max is not None else None,
            "observed_carrier_offset_hz": (
                round(self._offset_current, 2) if self._offset_current is not None else None
            ),
            "channel_filter_enabled": True,
            "channel_bandwidth_hz": self.bandwidth,
            "channel_filter_cutoff_hz": self.filter_cutoff_hz,
            "channel_filter_taps": self.filter_taps,
            "decimation_factor": self.factor,
            "wideband_power": wideband,
            "channel_power": channel,
            "channel_to_wideband_db": round(ratio_db, 2),
            "processed_rf_samples": self.sample_index,
            "squelch": self.squelch.status(),
        }
