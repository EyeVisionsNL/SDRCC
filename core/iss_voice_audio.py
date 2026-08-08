#!/usr/bin/env python3
"""Offline NFM audio demodulation for ISS Voice CU8 captures.

This module reads an existing recording.iq and writes mono 16-bit PCM WAV.
It owns no receiver, scheduler, mission, or service-control authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import math
import wave

import numpy as np

from core.iss_voice_squelch import RfPowerSquelch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_ROOT = (PROJECT_ROOT / "data" / "recordings" / "iss_voice").resolve()
MAX_IQ_BYTES = 2 * 240000 * 1200  # CU8, bounded to 20 minutes at current rate.


@dataclass(frozen=True)
class DemodSpec:
    iq_path: Path
    wav_path: Path
    metadata_path: Path
    rf_sample_rate_hz: int
    audio_sample_rate_hz: int
    deemphasis_us: float
    channel_bandwidth_hz: int
    squelch_enabled: bool
    squelch_threshold_dbfs: float


def _inside_recordings(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(RECORDINGS_ROOT)
    except ValueError as exc:
        raise ValueError("IQ-pad moet binnen data/recordings/iss_voice liggen") from exc
    return resolved


def build_spec(*, iq_path: str | Path, rf_sample_rate_hz: int,
               audio_sample_rate_hz: int, deemphasis_us: float = 75.0,
               channel_bandwidth_hz: int = 25000,
               squelch_enabled: bool = False,
               squelch_threshold_dbfs: float = -42.0,
               wav_path: str | Path | None = None) -> DemodSpec:
    iq = _inside_recordings(Path(iq_path))
    if not iq.is_file():
        raise ValueError(f"IQ-bestand bestaat niet: {iq}")
    size = iq.stat().st_size
    if size < 4 or size % 2:
        raise ValueError("IQ-bestand moet een even aantal CU8-bytes bevatten")
    if size > MAX_IQ_BYTES:
        raise ValueError("IQ-bestand overschrijdt de veilige offline limiet")

    rf_rate = int(rf_sample_rate_hz)
    audio_rate = int(audio_sample_rate_hz)
    if rf_rate < 100000 or rf_rate > 3200000:
        raise ValueError("rf_sample_rate_hz buiten veilige grenzen")
    if audio_rate < 8000 or audio_rate > 96000:
        raise ValueError("audio_sample_rate_hz buiten veilige grenzen")
    if rf_rate % audio_rate != 0:
        raise ValueError("rf_sample_rate_hz moet exact deelbaar zijn door audio_sample_rate_hz")
    decimation = rf_rate // audio_rate
    if decimation < 2:
        raise ValueError("audio sample rate moet lager zijn dan RF sample rate")
    deemphasis = float(deemphasis_us)
    if deemphasis <= 0 or deemphasis > 1000:
        raise ValueError("deemphasis_us buiten veilige grenzen")
    bandwidth = int(channel_bandwidth_hz)
    if bandwidth < 5000 or bandwidth > rf_rate // 2:
        raise ValueError("channel_bandwidth_hz buiten veilige grenzen")
    threshold = float(squelch_threshold_dbfs)
    if threshold < -65.0 or threshold > -10.0:
        raise ValueError("squelch_threshold_dbfs buiten veilige grenzen")

    wav = _inside_recordings(Path(wav_path)) if wav_path else iq.with_name("audio.wav")
    if wav.parent != iq.parent:
        raise ValueError("WAV-bestand moet naast het IQ-bestand staan")
    metadata = iq.with_name("demodulation.json")
    return DemodSpec(
        iq, wav, metadata, rf_rate, audio_rate, deemphasis, bandwidth,
        bool(squelch_enabled), threshold,
    )


def _deemphasis(samples: np.ndarray, sample_rate: int, tau_us: float) -> np.ndarray:
    tau = tau_us / 1_000_000.0
    alpha = math.exp(-1.0 / (sample_rate * tau))
    output = np.empty(samples.shape, dtype=np.float32)
    previous = 0.0
    one_minus = 1.0 - alpha
    for index, value in enumerate(samples):
        previous = alpha * previous + one_minus * float(value)
        output[index] = previous
    return output


def demodulate(spec: DemodSpec) -> dict[str, Any]:
    started = datetime.now().astimezone()
    raw = np.fromfile(spec.iq_path, dtype=np.uint8)
    i = (raw[0::2].astype(np.float32) - 127.5) / 127.5
    q = (raw[1::2].astype(np.float32) - 127.5) / 127.5
    complex_iq = i + 1j * q

    # Quadrature discriminator: phase difference between adjacent IQ samples.
    discriminator = np.angle(complex_iq[1:] * np.conj(complex_iq[:-1])).astype(np.float32)

    # Boxcar low-pass followed by exact integer decimation (240 kHz -> 48 kHz = 5).
    factor = spec.rf_sample_rate_hz // spec.audio_sample_rate_hz
    usable = (discriminator.size // factor) * factor
    if usable < factor:
        raise RuntimeError("Te weinig IQ-samples voor demodulatie")
    audio = discriminator[:usable].reshape(-1, factor).mean(axis=1, dtype=np.float32)
    audio = _deemphasis(audio, spec.audio_sample_rate_hz, spec.deemphasis_us)

    # Remove DC, apply the optional RF-power squelch, then normalize. The gate
    # uses the captured IQ level and therefore suppresses receiver noise rather
    # than merely muting quiet speech samples.
    audio -= float(np.mean(audio))
    squelch = RfPowerSquelch(
        rf_sample_rate_hz=spec.rf_sample_rate_hz,
        audio_sample_rate_hz=spec.audio_sample_rate_hz,
        enabled=spec.squelch_enabled,
        threshold_dbfs=spec.squelch_threshold_dbfs,
    )
    audio = squelch.process(complex_iq, audio)
    squelch_status = squelch.status()
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    scale = 0.90 / peak if peak > 1e-9 else 0.0
    pcm = np.clip(audio * scale, -1.0, 1.0)
    pcm16 = (pcm * 32767.0).astype("<i2")

    spec.wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(spec.wav_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(spec.audio_sample_rate_hz)
        wav.writeframes(pcm16.tobytes())

    ended = datetime.now().astimezone()
    result = {
        "ok": True,
        "version": "0.54.0g",
        "mode": "offline_nfm_demodulation",
        "automatic_execution": False,
        "receiver_claimed": False,
        "service_control_used": False,
        "doppler_correction_enabled": False,
        "iq_path": str(spec.iq_path),
        "iq_bytes": int(spec.iq_path.stat().st_size),
        "wav_path": str(spec.wav_path),
        "wav_bytes": int(spec.wav_path.stat().st_size),
        "metadata_path": str(spec.metadata_path),
        "rf_sample_rate_hz": spec.rf_sample_rate_hz,
        "audio_sample_rate_hz": spec.audio_sample_rate_hz,
        "audio_channels": 1,
        "sample_width_bytes": 2,
        "deemphasis_us": spec.deemphasis_us,
        "channel_bandwidth_hz": spec.channel_bandwidth_hz,
        "squelch_enabled": spec.squelch_enabled,
        "squelch_threshold_dbfs": spec.squelch_threshold_dbfs,
        "squelch": squelch_status,
        "decimation_factor": factor,
        "audio_frames": int(pcm16.size),
        "audio_duration_seconds": round(pcm16.size / spec.audio_sample_rate_hz, 6),
        "input_peak": peak,
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"),
        "elapsed_seconds": round((ended - started).total_seconds(), 3),
    }
    spec.metadata_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def demodulate_mission(mission_id: str, config: dict[str, Any]) -> dict[str, Any]:
    mission = str(mission_id or "").strip()
    if not mission or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for c in mission):
        raise ValueError("Ongeldige mission_id")
    directory = _inside_recordings(RECORDINGS_ROOT / mission)
    spec = build_spec(
        iq_path=directory / str(config.get("iq_filename") or "recording.iq"),
        rf_sample_rate_hz=int(config["rf_sample_rate_hz"]),
        audio_sample_rate_hz=int(config["audio_sample_rate_hz"]),
        deemphasis_us=float(config.get("audio_deemphasis_us") or 75.0),
        channel_bandwidth_hz=int(config["channel_bandwidth_hz"]),
        squelch_enabled=bool(config.get("squelch_enabled", False)),
        squelch_threshold_dbfs=float(config.get("squelch_threshold_dbfs", -42.0)),
        wav_path=directory / str(config.get("audio_filename") or "audio.wav"),
    )
    return demodulate(spec)
