#!/usr/bin/env python3
"""Read-only live audio monitor for active ISS Voice CU8 recordings.

The existing recorder remains the sole owner of RTL-SDR hardware and the IQ
file. This module only tails the already-growing recording.iq file and exposes
an in-memory PCM/WAV stream to connected browser clients.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
import json
import struct
import threading
import time

from core import iss_voice, iss_voice_runtime
from core.iss_voice_channel import NfmChannelDecoder
from core.iss_voice_doppler import build_tracker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = (PROJECT_ROOT / "data" / "recordings" / "iss_voice").resolve()
VERSION = "0.54.0h"
AUDIO_SAMPLE_RATE = 48000
DEEMPHASIS_US = 75.0
READ_COMPLEX_SAMPLES = 24000       # 100 ms at the normal 240 kS/s rate
START_BUFFER_SECONDS = 0.75
IDLE_TIMEOUT_SECONDS = 12.0
MAX_CLIENTS = 3

_clients_lock = threading.RLock()
_active_clients = 0
_total_clients = 0
_last_client_at: str | None = None
_last_processing: dict[str, Any] = {}


def _inside_root(value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        return None
    return path


def _elapsed(started_at: Any) -> float | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(str(started_at))
        if started.tzinfo is None:
            started = started.astimezone()
        return max(0.0, (datetime.now().astimezone() - started).total_seconds())
    except (TypeError, ValueError):
        return None


def _runtime_paths(runtime: dict[str, Any]) -> tuple[str | None, Path | None, Path | None]:
    mission_id = str(runtime.get("mission_id") or "").strip() or None
    output_directory = _inside_root(runtime.get("output_directory"))
    if output_directory is None and mission_id:
        output_directory = _inside_root(ROOT / mission_id)
    iq_path = output_directory / "recording.iq" if output_directory else None
    return mission_id, output_directory, iq_path


def _client_snapshot() -> tuple[int, int, str | None]:
    with _clients_lock:
        return _active_clients, _total_clients, _last_client_at


def _register_client() -> None:
    global _active_clients, _total_clients, _last_client_at
    with _clients_lock:
        if _active_clients >= MAX_CLIENTS:
            raise RuntimeError("Maximum aantal live-audioclients bereikt")
        _active_clients += 1
        _total_clients += 1
        _last_client_at = datetime.now().astimezone().isoformat(timespec="seconds")


def _unregister_client() -> None:
    global _active_clients
    with _clients_lock:
        _active_clients = max(0, _active_clients - 1)


def _wav_stream_header(sample_rate: int) -> bytes:
    # Unknown stream length is represented with maximum RIFF/data sizes. Chrome
    # and Firefox can start playback while the response remains open.
    data_size = 0xFFFFFFFF - 36
    byte_rate = sample_rate * 2
    return b"".join((
        b"RIFF", struct.pack("<I", 0xFFFFFFFF), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, byte_rate, 2, 16),
        b"data", struct.pack("<I", data_size),
    ))


def get_status() -> dict[str, Any]:
    runtime = iss_voice_runtime.get_status()
    active = bool(runtime.get("active"))
    mission_id, _output_directory, iq_path = _runtime_paths(runtime)
    iq_bytes = 0
    iq_exists = False
    if iq_path and iq_path.is_file():
        iq_exists = True
        try:
            iq_bytes = int(iq_path.stat().st_size)
        except OSError:
            iq_bytes = 0

    sample_rate = int(runtime.get("sample_rate_hz") or 0)
    expected_byte_rate = sample_rate * 2 if sample_rate > 0 else 0
    elapsed = runtime.get("elapsed_seconds")
    try:
        elapsed = float(elapsed) if elapsed is not None else _elapsed(runtime.get("started_at"))
    except (TypeError, ValueError):
        elapsed = _elapsed(runtime.get("started_at"))
    observed_byte_rate = round(iq_bytes / elapsed, 1) if elapsed and elapsed > 0 else 0.0
    compatible = sample_rate > 0 and sample_rate % AUDIO_SAMPLE_RATE == 0
    available = bool(active and iq_exists and iq_bytes >= sample_rate * 2 * 0.25 and compatible)
    clients, total_clients, last_client_at = _client_snapshot()
    settings = iss_voice.get_settings()
    config = iss_voice.get_config()
    with _clients_lock:
        processing = dict(_last_processing)

    return {
        "ok": True,
        "version": VERSION,
        "authority": "observer_only",
        "active": active,
        "available": available,
        "mission_id": mission_id,
        "phase": runtime.get("phase"),
        "receiver_id": runtime.get("receiver_id"),
        "receiver_serial": runtime.get("receiver_serial"),
        "frequency_hz": runtime.get("frequency_hz"),
        "sample_rate_hz": sample_rate or None,
        "audio_sample_rate_hz": AUDIO_SAMPLE_RATE,
        "sample_format": "cu8",
        "transport": "streaming_wav_pcm16",
        "mime_type": "audio/wav",
        "iq_path": str(iq_path) if iq_path else None,
        "iq_bytes": iq_bytes,
        "expected_byte_rate": expected_byte_rate,
        "observed_byte_rate": observed_byte_rate,
        "elapsed_seconds": round(elapsed, 3) if elapsed is not None else None,
        "streaming_enabled": True,
        "squelch_enabled": settings["squelch_enabled"],
        "squelch_threshold_dbfs": settings["squelch_threshold_dbfs"],
        "nominal_frequency_hz": int(config["downlink_frequency_hz"]),
        "doppler_correction_enabled": bool(config.get("doppler_tracking")),
        "doppler_offset_hz": processing.get("doppler_offset_hz"),
        "corrected_frequency_hz": (
            int(config["downlink_frequency_hz"]) + float(processing["doppler_offset_hz"])
            if processing.get("doppler_offset_hz") is not None else None
        ),
        "channel_filter_enabled": True,
        "channel_bandwidth_hz": int(config["channel_bandwidth_hz"]),
        "stream_url": f"/api/iss-voice/audio-stream?mission_id={mission_id}" if available else None,
        "stream_state": "STREAMING" if clients else ("READY" if available else "STANDBY"),
        "active_clients": clients,
        "max_clients": MAX_CLIENTS,
        "total_clients": total_clients,
        "last_client_at": last_client_at,
        "detail": (
            f"Live monitor active for {clients} client(s)." if clients
            else "Live audio is ready. Press Play to listen." if available
            else "Waiting for a compatible active ISS Voice IQ recording."
        ),
        "receiver_claimed": False,
        "service_control_used": False,
        "process_started": False,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


class LiveWavStream:
    """Close-aware iterator with synchronous admission and client accounting."""

    def __init__(self, mission_id: str, iq_path: Path, sample_rate: int,
                 *, config: dict[str, Any], capture_start_epoch: float,
                 doppler_offset_provider, doppler_metadata: dict[str, Any]) -> None:
        self.mission_id = mission_id
        self.iq_path = iq_path
        self.sample_rate = sample_rate
        self.config = dict(config)
        self.capture_start_epoch = float(capture_start_epoch)
        self.doppler_offset_provider = doppler_offset_provider
        self.doppler_metadata = dict(doppler_metadata)
        self._closed = False
        _register_client()
        self._iterator = self._generate()

    def __iter__(self) -> "LiveWavStream":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        try:
            return next(self._iterator)
        except StopIteration:
            self.close()
            raise
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._iterator.close()
        finally:
            _unregister_client()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _generate(self) -> Iterator[bytes]:
        byte_rate = self.sample_rate * 2
        chunk_bytes = READ_COMPLEX_SAMPLES * 2
        yield _wav_stream_header(AUDIO_SAMPLE_RATE)
        with self.iq_path.open("rb", buffering=0) as handle:
            current_size = self.iq_path.stat().st_size
            start_offset = max(0, current_size - int(byte_rate * START_BUFFER_SECONDS))
            start_offset -= start_offset % 2
            demodulator = NfmChannelDecoder(
                rf_sample_rate_hz=self.sample_rate,
                audio_sample_rate_hz=int(self.config["audio_sample_rate_hz"]),
                channel_bandwidth_hz=int(self.config["channel_bandwidth_hz"]),
                deemphasis_us=float(self.config.get("audio_deemphasis_us") or DEEMPHASIS_US),
                capture_start_epoch=self.capture_start_epoch,
                doppler_offset_provider=self.doppler_offset_provider,
                initial_sample_index=start_offset // 2,
                squelch_enabled=bool(self.config.get("squelch_enabled", False)),
                squelch_threshold_dbfs=float(self.config.get("squelch_threshold_dbfs", -42.0)),
            )
            handle.seek(start_offset)
            last_data = time.monotonic()
            while not self._closed:
                current_runtime = iss_voice_runtime.get_status()
                current_mission = str(current_runtime.get("mission_id") or "")
                raw = handle.read(chunk_bytes)
                if raw:
                    last_data = time.monotonic()
                    pcm = demodulator.process_pcm16(raw)
                    with _clients_lock:
                        global _last_processing
                        _last_processing = {**self.doppler_metadata, **demodulator.status()}
                    if pcm:
                        yield pcm
                    continue
                idle_for = time.monotonic() - last_data
                if (not current_runtime.get("active") or current_mission != self.mission_id) and idle_for > 1.0:
                    break
                if idle_for > IDLE_TIMEOUT_SECONDS:
                    break
                time.sleep(0.08)


def stream_wav(requested_mission_id: str) -> LiveWavStream:
    """Validate synchronously, then return a close-aware live WAV iterator.

    Synchronous validation is deliberate: Flask can return a useful 409 before
    response headers are sent, instead of discovering admission errors only
    when the lazy generator starts iterating.
    """
    runtime = iss_voice_runtime.get_status()
    mission_id, _output_directory, iq_path = _runtime_paths(runtime)
    if not runtime.get("active") or not mission_id or requested_mission_id != mission_id:
        raise ValueError("ISS Voice mission is niet actief of mission_id komt niet overeen")
    sample_rate = int(runtime.get("sample_rate_hz") or 0)
    if sample_rate <= 0 or sample_rate % AUDIO_SAMPLE_RATE != 0:
        raise ValueError("Actieve RF sample rate is niet geschikt voor live audio")
    if iq_path is None or not iq_path.is_file():
        raise ValueError("Actief IQ-bestand is nog niet beschikbaar")
    config = iss_voice.get_config()
    tracker = build_tracker(config)
    capture_start = runtime.get("capture_started_at") or runtime.get("started_at")
    if not capture_start:
        try:
            capture_metadata = json.loads(
                iq_path.with_name("capture.json").read_text(encoding="utf-8")
            )
            capture_start = capture_metadata.get("capture_started_at") or capture_metadata.get("started_at")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            capture_start = None
    if not capture_start:
        raise ValueError("Capture starttijd ontbreekt; Dopplertracking kan niet veilig starten")
    parsed_start = datetime.fromisoformat(str(capture_start).replace("Z", "+00:00"))
    if parsed_start.tzinfo is None:
        parsed_start = parsed_start.astimezone()
    return LiveWavStream(
        mission_id,
        iq_path,
        sample_rate,
        config=config,
        capture_start_epoch=parsed_start.timestamp(),
        doppler_offset_provider=tracker.offset_hz,
        doppler_metadata=tracker.metadata,
    )
