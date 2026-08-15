#!/usr/bin/env python3
"""Local UDP float32 to browser WAV bridge for Traffic Voice.

RTLSDR-Airband remains the sole SDR owner. This bridge only receives the
backend's localhost audio datagrams and keeps a small in-memory fan-out.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
import math
import socket
import struct
import threading
import time
from typing import Any, Iterator

from core import config
from core import traffic_voice_atis


MAX_CLIENTS = 3
MAX_CHUNKS = 96
_lock = threading.Condition(threading.RLock())
_chunks: deque[tuple[int, bytes]] = deque(maxlen=MAX_CHUNKS)
_sequence = 0
_listener: threading.Thread | None = None
_listener_error: str | None = None
_last_packet_epoch: float | None = None
_packets = 0
_bytes = 0
_active_clients = 0
_total_clients = 0


def _settings() -> tuple[str, int, int]:
    backend = config.get_traffic_voice_config().get("backend") or {}
    return (
        str(backend.get("audio_host") or "127.0.0.1"),
        int(backend.get("audio_port") or 49555),
        int(backend.get("audio_sample_rate_hz") or 16000),
    )


def _wav_header(sample_rate: int) -> bytes:
    return b"".join((
        b"RIFF", struct.pack("<I", 0xFFFFFFFF), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16),
        b"data", struct.pack("<I", 0xFFFFFFFF - 36),
    ))


def float32_to_pcm16(payload: bytes) -> bytes:
    """Convert complete little-endian float samples and reject trailing data."""
    usable = len(payload) - (len(payload) % 4)
    output = bytearray((usable // 4) * 2)
    offset = 0
    for (value,) in struct.iter_unpack("<f", payload[:usable]):
        sample = value if math.isfinite(value) else 0.0
        sample = max(-1.0, min(1.0, sample))
        integer = int(round(sample * 32767.0))
        struct.pack_into("<h", output, offset, integer)
        offset += 2
    return bytes(output)


def _listen() -> None:
    global _listener_error, _last_packet_epoch, _packets, _bytes, _sequence
    host, port, _sample_rate = _settings()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
            server.bind((host, port))
            server.settimeout(1.0)
            with _lock:
                _listener_error = None
            while True:
                try:
                    payload, _address = server.recvfrom(65536)
                except socket.timeout:
                    continue
                pcm = float32_to_pcm16(payload)
                if not pcm:
                    continue
                # ATIS receives a copy through a bounded in-process queue.
                # This bridge remains the sole UDP listener and never waits
                # for the read-only decoder observer.
                try:
                    traffic_voice_atis.observe_float32(payload)
                except Exception as error:  # noqa: BLE001 - optional observer fails open
                    traffic_voice_atis.report_observer_error(error)
                with _lock:
                    _sequence += 1
                    _chunks.append((_sequence, pcm))
                    _last_packet_epoch = time.time()
                    _packets += 1
                    _bytes += len(payload)
                    _lock.notify_all()
    except Exception as error:  # noqa: BLE001 - status reports listener failure
        with _lock:
            _listener_error = str(error)
            _lock.notify_all()


def ensure_listener() -> None:
    global _listener
    with _lock:
        if _listener is not None and _listener.is_alive():
            return
        _listener = threading.Thread(
            target=_listen,
            daemon=True,
            name="sdrcc-traffic-voice-audio",
        )
        _listener.start()


def get_status() -> dict[str, Any]:
    ensure_listener()
    host, port, sample_rate = _settings()
    with _lock:
        age = time.time() - _last_packet_epoch if _last_packet_epoch else None
        available = bool(_last_packet_epoch and age is not None and age < 3.0 and not _listener_error)
        return {
            "ok": _listener_error is None,
            "authority": "audio_bridge_only",
            "transport": "udp_float32_to_streaming_wav_pcm16",
            "host": host,
            "port": port,
            "sample_rate_hz": sample_rate,
            "available": available,
            "stream_url": "/api/traffic-voice/audio-stream" if available else None,
            "stream_state": "STREAMING" if _active_clients else ("READY" if available else "WAITING"),
            "active_clients": _active_clients,
            "max_clients": MAX_CLIENTS,
            "total_clients": _total_clients,
            "packets_received": _packets,
            "udp_bytes_received": _bytes,
            "last_packet_age_seconds": round(age, 2) if age is not None else None,
            "listener_error": _listener_error,
            "observers": ["traffic_voice_atis"],
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


class LiveWavStream:
    def __init__(self) -> None:
        global _active_clients, _total_clients
        ensure_listener()
        with _lock:
            if _active_clients >= MAX_CLIENTS:
                raise RuntimeError("Maximum aantal Traffic Voice audioclients bereikt")
            _active_clients += 1
            _total_clients += 1
            self._next_sequence = _sequence + 1
        self._closed = False
        self._header_sent = False

    def __iter__(self) -> "LiveWavStream":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        if not self._header_sent:
            self._header_sent = True
            return _wav_header(_settings()[2])
        deadline = time.monotonic() + 12.0
        with _lock:
            while not self._closed:
                for sequence, chunk in _chunks:
                    if sequence >= self._next_sequence:
                        self._next_sequence = sequence + 1
                        return chunk
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.close()
                    raise StopIteration
                _lock.wait(min(1.0, remaining))
        raise StopIteration

    def close(self) -> None:
        global _active_clients
        if self._closed:
            return
        with _lock:
            self._closed = True
            _active_clients = max(0, _active_clients - 1)
            _lock.notify_all()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def stream_wav() -> Iterator[bytes]:
    return LiveWavStream()
