#!/usr/bin/env python3
"""Offline ISS NFM audio using the shared Doppler/channel decoder."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import json
import wave

from core.iss_voice_channel import NfmChannelDecoder
from core.iss_voice_doppler import build_tracker


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_ROOT = (PROJECT_ROOT / "data" / "recordings" / "iss_voice").resolve()
MAX_IQ_BYTES = 2 * 240000 * 1200
READ_COMPLEX_SAMPLES = 24000


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
    rf_rate, audio_rate = int(rf_sample_rate_hz), int(audio_sample_rate_hz)
    if rf_rate < 100000 or rf_rate > 3200000 or rf_rate % audio_rate:
        raise ValueError("RF/audio sample rates vormen geen geldige gehele decimatie")
    bandwidth = int(channel_bandwidth_hz)
    if bandwidth < 5000 or bandwidth >= audio_rate:
        raise ValueError("channel_bandwidth_hz buiten veilige grenzen")
    deemphasis = float(deemphasis_us)
    if deemphasis <= 0 or deemphasis > 1000:
        raise ValueError("deemphasis_us buiten veilige grenzen")
    threshold = float(squelch_threshold_dbfs)
    if threshold < -65.0 or threshold > -10.0:
        raise ValueError("squelch_threshold_dbfs buiten veilige grenzen")
    wav = _inside_recordings(Path(wav_path)) if wav_path else iq.with_name("audio.wav")
    if wav.parent != iq.parent:
        raise ValueError("WAV-bestand moet naast het IQ-bestand staan")
    return DemodSpec(
        iq, wav, iq.with_name("demodulation.json"), rf_rate, audio_rate,
        deemphasis, bandwidth, bool(squelch_enabled), threshold,
    )


def _capture_start_epoch(spec: DemodSpec) -> float:
    metadata_path = spec.iq_path.with_name("capture.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        value = metadata.get("capture_started_at") or metadata.get("started_at")
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.timestamp()
    except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
        duration = spec.iq_path.stat().st_size / 2.0 / spec.rf_sample_rate_hz
        return spec.iq_path.stat().st_mtime - duration


def demodulate(spec: DemodSpec, *, config: dict[str, Any],
               doppler_offset_provider: Callable[[float], float] | None = None,
               doppler_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    started = datetime.now().astimezone()
    tracker = None
    if doppler_offset_provider is None:
        tracker = build_tracker(config)
        doppler_offset_provider = tracker.offset_hz
        doppler_metadata = dict(tracker.metadata)
    decoder = NfmChannelDecoder(
        rf_sample_rate_hz=spec.rf_sample_rate_hz,
        audio_sample_rate_hz=spec.audio_sample_rate_hz,
        channel_bandwidth_hz=spec.channel_bandwidth_hz,
        deemphasis_us=spec.deemphasis_us,
        capture_start_epoch=_capture_start_epoch(spec),
        doppler_offset_provider=doppler_offset_provider,
        squelch_enabled=spec.squelch_enabled,
        squelch_threshold_dbfs=spec.squelch_threshold_dbfs,
    )

    frames = 0
    spec.wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(spec.wav_path), "wb") as output, spec.iq_path.open("rb") as iq_handle:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(spec.audio_sample_rate_hz)
        while True:
            raw = iq_handle.read(READ_COMPLEX_SAMPLES * 2)
            if not raw:
                break
            pcm = decoder.process_pcm16(raw)
            if pcm:
                output.writeframesraw(pcm)
                frames += len(pcm) // 2

    ended = datetime.now().astimezone()
    processing = decoder.status()
    result = {
        "ok": True,
        "version": "0.54.0h",
        "mode": "offline_nfm_demodulation",
        "automatic_execution": False,
        "receiver_claimed": False,
        "service_control_used": False,
        "doppler_correction_enabled": True,
        "doppler": {**(doppler_metadata or {}), **{
            key: processing[key] for key in (
                "doppler_offset_hz", "doppler_min_hz", "doppler_max_hz"
            )
        }},
        "channel_filter_enabled": True,
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
        "channel_filter_cutoff_hz": processing["channel_filter_cutoff_hz"],
        "channel_filter_taps": processing["channel_filter_taps"],
        "squelch_enabled": spec.squelch_enabled,
        "squelch_threshold_dbfs": spec.squelch_threshold_dbfs,
        "squelch": processing["squelch"],
        "decimation_factor": processing["decimation_factor"],
        "audio_frames": frames,
        "audio_duration_seconds": round(frames / spec.audio_sample_rate_hz, 6),
        "signal_metrics": {
            key: processing[key] for key in (
                "wideband_power", "channel_power", "channel_to_wideband_db"
            )
        },
        "started_at": started.isoformat(timespec="seconds"),
        "ended_at": ended.isoformat(timespec="seconds"),
        "elapsed_seconds": round((ended - started).total_seconds(), 3),
    }
    spec.metadata_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def demodulate_mission(mission_id: str, config: dict[str, Any], *,
                       doppler_offset_provider: Callable[[float], float] | None = None,
                       doppler_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
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
    return demodulate(
        spec, config=config, doppler_offset_provider=doppler_offset_provider,
        doppler_metadata=doppler_metadata,
    )
