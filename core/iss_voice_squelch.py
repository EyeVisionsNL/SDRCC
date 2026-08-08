#!/usr/bin/env python3
"""RF-power squelch for ISS Voice demodulated audio.

The helper transforms already-captured samples only. It owns no receiver,
mission, scheduler, process, or service-control authority.
"""
from __future__ import annotations

from typing import Any
import math

import numpy as np


class RfPowerSquelch:
    """Stateful RF-level gate with hysteresis, hang time and click-free fades."""

    def __init__(
        self,
        *,
        rf_sample_rate_hz: int,
        audio_sample_rate_hz: int,
        enabled: bool,
        threshold_dbfs: float,
    ) -> None:
        self.rf_sample_rate_hz = int(rf_sample_rate_hz)
        self.audio_sample_rate_hz = int(audio_sample_rate_hz)
        self.enabled = bool(enabled)
        self.threshold_dbfs = float(threshold_dbfs)
        if self.rf_sample_rate_hz <= 0 or self.audio_sample_rate_hz <= 0:
            raise ValueError("Sample rates must be positive")
        if self.threshold_dbfs < -65.0 or self.threshold_dbfs > -10.0:
            raise ValueError("Squelch threshold must be between -65 and -10 dBFS")
        self._block_audio_samples = max(1, int(self.audio_sample_rate_hz * 0.1))
        self._hang_blocks = max(1, int(round(0.3 / 0.1)))
        self._hang_remaining = 0
        self._gate_open = False
        self._envelope = 0.0 if self.enabled else 1.0
        self._processed_audio_samples = 0
        self._open_audio_samples = 0
        self._last_level_dbfs: float | None = None

    @staticmethod
    def rf_level_dbfs(iq: np.ndarray) -> float:
        if iq.size == 0:
            return -120.0
        power = float(np.mean(np.square(np.abs(iq)), dtype=np.float64)) / 2.0
        return 10.0 * math.log10(max(power, 1e-12))

    def _target_for_level(self, level_dbfs: float) -> float:
        # Three dB hysteresis prevents chatter at the configured boundary.
        signal_present = level_dbfs >= (
            self.threshold_dbfs - 3.0 if self._gate_open else self.threshold_dbfs
        )
        if signal_present:
            self._gate_open = True
            self._hang_remaining = self._hang_blocks
        elif self._hang_remaining > 0:
            self._hang_remaining -= 1
        else:
            self._gate_open = False
        return 1.0 if self._gate_open or self._hang_remaining > 0 else 0.0

    def _fade(self, samples: np.ndarray, target: float) -> np.ndarray:
        if samples.size == 0:
            return samples
        time_constant = 0.008 if target > self._envelope else 0.04
        alpha = math.exp(-1.0 / (self.audio_sample_rate_hz * time_constant))
        positions = np.arange(1, samples.size + 1, dtype=np.float64)
        envelope = target + (self._envelope - target) * np.power(alpha, positions)
        self._envelope = float(envelope[-1])
        return samples * envelope.astype(np.float32)

    def process(self, iq: np.ndarray, audio: np.ndarray) -> np.ndarray:
        if not self.enabled or audio.size == 0:
            self._processed_audio_samples += int(audio.size)
            self._open_audio_samples += int(audio.size)
            return audio

        result = np.empty_like(audio, dtype=np.float32)
        ratio = iq.size / max(1, audio.size)
        for audio_start in range(0, audio.size, self._block_audio_samples):
            audio_end = min(audio.size, audio_start + self._block_audio_samples)
            rf_start = min(iq.size, int(round(audio_start * ratio)))
            rf_end = min(iq.size, max(rf_start + 1, int(round(audio_end * ratio))))
            level = self.rf_level_dbfs(iq[rf_start:rf_end])
            self._last_level_dbfs = level
            target = self._target_for_level(level)
            block = self._fade(audio[audio_start:audio_end], target)
            result[audio_start:audio_end] = block
            self._processed_audio_samples += int(block.size)
            if target > 0.0:
                self._open_audio_samples += int(block.size)
        return result

    def status(self) -> dict[str, Any]:
        total = self._processed_audio_samples
        open_fraction = self._open_audio_samples / total if total else 0.0
        return {
            "enabled": self.enabled,
            "threshold_dbfs": self.threshold_dbfs,
            "gate_open": self._gate_open or self._hang_remaining > 0,
            "last_rf_level_dbfs": (
                round(self._last_level_dbfs, 2)
                if self._last_level_dbfs is not None else None
            ),
            "open_fraction": round(open_fraction, 6),
        }
