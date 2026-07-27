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
import math
import struct
import threading
import time

import numpy as np

from core import iss_voice_runtime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROOT = (PROJECT_ROOT / "data" / "recordings" / "iss_voice").resolve()
VERSION = "0.52.0"
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


class _LiveNfmDemodulator:
    def __init__(self, rf_sample_rate: int, audio_sample_rate: int = AUDIO_SAMPLE_RATE) -> None:
        if rf_sample_rate % audio_sample_rate != 0:
            raise ValueError("RF sample rate moet exact deelbaar zijn door 48 kHz")
        self.factor = rf_sample_rate // audio_sample_rate
        if self.factor < 2:
            raise ValueError("Ongeldige decimatiefactor")
        self.audio_sample_rate = audio_sample_rate
        self.previous_iq: complex | None = None
        self.decimation_carry = np.empty(0, dtype=np.float32)
        tau = DEEMPHASIS_US / 1_000_000.0
        self.deemphasis_alpha = math.exp(-1.0 / (audio_sample_rate * tau))
        self.deemphasis_previous = 0.0
        self.dc_previous_input = 0.0
        self.dc_previous_output = 0.0
        self.level = 0.08

    def process(self, raw: bytes) -> bytes:
        usable_bytes = len(raw) - (len(raw) % 2)
        if usable_bytes < 4:
            return b""
        values = np.frombuffer(raw[:usable_bytes], dtype=np.uint8)
        i = (values[0::2].astype(np.float32) - 127.5) / 127.5
        q = (values[1::2].astype(np.float32) - 127.5) / 127.5
        iq = i + 1j * q
        if self.previous_iq is not None:
            iq = np.concatenate((np.asarray([self.previous_iq], dtype=np.complex64), iq))
        self.previous_iq = complex(iq[-1])
        discriminator = np.angle(iq[1:] * np.conj(iq[:-1])).astype(np.float32)
        if self.decimation_carry.size:
            discriminator = np.concatenate((self.decimation_carry, discriminator))
        usable = (discriminator.size // self.factor) * self.factor
        self.decimation_carry = discriminator[usable:].copy()
        if usable == 0:
            return b""
        audio = discriminator[:usable].reshape(-1, self.factor).mean(axis=1, dtype=np.float32)

        # Stateful de-emphasis and gentle DC blocking.
        alpha = self.deemphasis_alpha
        previous = self.deemphasis_previous
        dc_in = self.dc_previous_input
        dc_out = self.dc_previous_output
        for idx in range(audio.size):
            previous = alpha * previous + (1.0 - alpha) * float(audio[idx])
            high_pass = previous - dc_in + 0.995 * dc_out
            dc_in = previous
            dc_out = high_pass
            audio[idx] = high_pass
        self.deemphasis_previous = previous
        self.dc_previous_input = dc_in
        self.dc_previous_output = dc_out

        # Slow level tracking avoids loud jumps while retaining weak speech.
        block_peak = float(np.percentile(np.abs(audio), 98.0)) if audio.size else 0.0
        self.level = max(block_peak, self.level * 0.985, 0.015)
        gain = min(18.0, 0.55 / self.level)
        pcm = np.tanh(audio * gain * 1.35)
        return (np.clip(pcm, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


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

    def __init__(self, mission_id: str, iq_path: Path, sample_rate: int) -> None:
        self.mission_id = mission_id
        self.iq_path = iq_path
        self.sample_rate = sample_rate
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
        demodulator = _LiveNfmDemodulator(self.sample_rate)
        byte_rate = self.sample_rate * 2
        chunk_bytes = READ_COMPLEX_SAMPLES * 2
        yield _wav_stream_header(AUDIO_SAMPLE_RATE)
        with self.iq_path.open("rb", buffering=0) as handle:
            current_size = self.iq_path.stat().st_size
            start_offset = max(0, current_size - int(byte_rate * START_BUFFER_SECONDS))
            start_offset -= start_offset % 2
            handle.seek(start_offset)
            last_data = time.monotonic()
            while not self._closed:
                current_runtime = iss_voice_runtime.get_status()
                current_mission = str(current_runtime.get("mission_id") or "")
                raw = handle.read(chunk_bytes)
                if raw:
                    last_data = time.monotonic()
                    pcm = demodulator.process(raw)
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
    return LiveWavStream(mission_id, iq_path, sample_rate)
