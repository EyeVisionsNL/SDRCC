#!/usr/bin/env python3
"""Local UDP float32 to browser WAV bridge for Traffic Voice.

RTLSDR-Airband remains the sole SDR owner. This bridge only receives the
backend's localhost audio datagrams and keeps a small in-memory fan-out.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
import json
import math
import re
import socket
import struct
import subprocess
import threading
import time
from typing import Any, Iterator
from uuid import uuid4

from core import config

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAVED_RECORDINGS_DIR = PROJECT_ROOT / "data" / "traffic_voice" / "saved_recordings"
from core import traffic_voice_atis, traffic_voice_denoise


SPEECH_FILTERS = {"off": None, "light": 3800.0, "normal": 3000.0, "strong": 2400.0}

MAX_CLIENTS = 3
MAX_CHUNKS = 96
RECORDING_UDP_PORT_OFFSET = 1
RECORDING_PREROLL_SECONDS = 0.4
RECORDING_POSTROLL_SECONDS = 0.4
RECORDING_GAP_SECONDS = 0.7
RECORDING_MAX_SECONDS = 120.0
RECORDING_COUNT = 4
SCAN_CHANNEL_RESOLUTION_ATTEMPTS = 5
SCAN_CHANNEL_RESOLUTION_RETRY_SECONDS = 0.25
SCAN_ACTIVITY_MATCH_TOLERANCE_SECONDS = 2.5
SCAN_ACTIVITY_LOOKBACK_SECONDS = 20.0
SCAN_STATS_POLL_INTERVAL_SECONDS = 0.2
SCAN_STATS_MATCH_TOLERANCE_SECONDS = 3.0
SCAN_STATS_EVENT_COUNT = 128
_lock = threading.Condition(threading.RLock())
_chunks: deque[tuple[int, bytes]] = deque(maxlen=MAX_CHUNKS)
_sequence = 0
_listener: threading.Thread | None = None
_recording_listener: threading.Thread | None = None
_recording_listener_retry_at = 0.0
_listener_error: str | None = None
_recording_listener_error: str | None = None
_last_packet_epoch: float | None = None
_last_recording_packet_epoch: float | None = None
_packets = 0
_bytes = 0
_active_clients = 0
_total_clients = 0
_scan_stats_lock = threading.RLock()
_scan_stats_last_poll_epoch = 0.0
_scan_stats_squelch_counts: dict[str, int] = {}
_scan_stats_events: deque[tuple[float, dict[str, Any]]] = deque(maxlen=SCAN_STATS_EVENT_COUNT)
_scan_stats_snapshot: dict[str, Any] | None = None
_scan_stats_snapshot_epoch: float | None = None


def _settings() -> tuple[str, int, int]:
    backend = config.get_traffic_voice_config().get("backend") or {}
    return (
        str(backend.get("audio_host") or "127.0.0.1"),
        int(backend.get("audio_port") or 49555),
        int(backend.get("audio_sample_rate_hz") or 16000),
    )


def _recording_settings() -> tuple[str, int, int]:
    host, port, sample_rate = _settings()
    if port <= 0 or port + RECORDING_UDP_PORT_OFFSET > 65535:
        raise ValueError("Traffic Voice audio port leaves no room for Marine recording")
    return host, port + RECORDING_UDP_PORT_OFFSET, sample_rate


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


def _finite_wav(pcm: bytes, sample_rate: int) -> bytes:
    data_size = len(pcm)
    return b"".join((
        b"RIFF", struct.pack("<I", 36 + data_size), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                             sample_rate * 2, 2, 16),
        b"data", struct.pack("<I", data_size), pcm,
    ))


class MarineRecordingStore:
    """Bounded store for the latest four squelch-open Marine transmissions."""

    def __init__(
        self,
        sample_rate: int = 16000,
        *,
        recording_count: int = RECORDING_COUNT,
        pre_roll_seconds: float = RECORDING_PREROLL_SECONDS,
        post_roll_seconds: float = RECORDING_POSTROLL_SECONDS,
        gap_seconds: float = RECORDING_GAP_SECONDS,
        max_seconds: float = RECORDING_MAX_SECONDS,
    ) -> None:
        self.sample_rate = max(1, int(sample_rate))
        self.recording_count = max(1, int(recording_count))
        self.pre_roll_seconds = max(0.0, float(pre_roll_seconds))
        self.post_roll_seconds = max(0.0, float(post_roll_seconds))
        self.gap_seconds = max(0.1, float(gap_seconds))
        self.max_bytes = max(1, int(self.sample_rate * 2 * float(max_seconds)))
        self._lock = threading.RLock()
        self._live_history: deque[tuple[float, bytes]] = deque()
        self._completed: deque[dict[str, Any]] = deque(maxlen=self.recording_count)
        self._active: dict[str, Any] | None = None

    @staticmethod
    def _append_bounded(clip: dict[str, Any], pcm: bytes, maximum: int) -> None:
        available = maximum - len(clip["pcm"])
        if available > 0:
            clip["pcm"].extend(pcm[:available])

    def observe_live_chunk(self, pcm: bytes, received_at: float | None = None) -> None:
        """Retain a short rolling buffer for clean squelch-open pre-roll."""
        if not pcm:
            return
        moment = time.monotonic() if received_at is None else float(received_at)
        with self._lock:
            self._live_history.append((moment, bytes(pcm)))
            history_age = self.pre_roll_seconds + self.post_roll_seconds + self.gap_seconds + 1.0
            while self._live_history and self._live_history[0][0] < moment - history_age:
                self._live_history.popleft()
            active = self._active
            if active and len(active["pcm"]) < self.max_bytes:
                # Keep post-roll from the always-on listener. The gated stream
                # itself supplies the speech-bearing body of the recording.
                if moment > active["last_gate_at"]:
                    active["postroll"].append((moment, bytes(pcm)))

    def is_recording(self) -> bool:
        with self._lock:
            return self._active is not None

    def needs_new_recording(self, received_at: float) -> bool:
        moment = float(received_at)
        with self._lock:
            return (
                self._active is None
                or moment - self._active["last_gate_at"] >= self.gap_seconds
            )

    def observe_gated_chunk(
        self,
        pcm: bytes,
        received_at: float,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, bool]:
        """Start or extend a clip from the squelch-gated UDP stream."""
        if not pcm:
            return "", False
        moment = float(received_at)
        with self._lock:
            if self._active and moment - self._active["last_gate_at"] >= self.gap_seconds:
                self._finish_locked(moment)
            started = self._active is None
            if self._active is None:
                pre_roll = [
                    (stamp, chunk) for stamp, chunk in self._live_history
                    if moment - self.pre_roll_seconds <= stamp < moment
                ]
                detail = metadata if isinstance(metadata, dict) else {}
                self._active = {
                    "id": uuid4().hex,
                    "received_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "channel": str(detail.get("channel") or "Marine scan · channel unknown"),
                    "frequency_mhz": detail.get("frequency_mhz"),
                    "pcm": bytearray(),
                    "postroll": [],
                    "last_gate_at": moment,
                }
                for _stamp, chunk in pre_roll:
                    self._append_bounded(self._active, chunk, self.max_bytes)
            self._append_bounded(self._active, pcm, self.max_bytes)
            self._active["last_gate_at"] = moment
            return self._active["id"], started

    def finish_if_idle(self, now: float | None = None, *, force: bool = False) -> bool:
        moment = time.monotonic() if now is None else float(now)
        with self._lock:
            if not self._active:
                return False
            if not force and moment - self._active["last_gate_at"] < self.gap_seconds:
                return False
            self._finish_locked(moment)
            return True

    def _finish_locked(self, now: float) -> None:
        del now  # the tail length is bounded relative to the final gated packet
        clip = self._active
        if not clip:
            return
        tail_until = clip["last_gate_at"] + self.post_roll_seconds
        for stamp, chunk in clip["postroll"]:
            if clip["last_gate_at"] < stamp <= tail_until:
                self._append_bounded(clip, chunk, self.max_bytes)
        clip.pop("postroll", None)
        clip.pop("last_gate_at", None)
        if len(clip["pcm"]) >= int(self.sample_rate * 2 * 0.08):
            clip["pcm"] = bytes(clip["pcm"])
            self._completed.append(clip)
        self._active = None

    def list_recordings(self) -> list[dict[str, Any]]:
        with self._lock:
            selected: list[dict[str, Any]] = []
            if self._active:
                selected.append(self._active)
                completed = list(self._completed)
                if self.recording_count > 1:
                    selected.extend(reversed(completed[-(self.recording_count - 1):]))
            else:
                selected.extend(reversed(self._completed))
            result = []
            for clip in selected[:self.recording_count]:
                pcm_size = len(clip["pcm"])
                result.append({
                    "id": clip["id"],
                    "received_at": clip["received_at"],
                    "channel": clip["channel"],
                    "frequency_mhz": clip["frequency_mhz"],
                    "duration_seconds": round(pcm_size / (self.sample_rate * 2), 1),
                    "complete": "postroll" not in clip,
                    "play_url": (
                        f"/api/traffic-voice/recordings/{clip['id']}.wav"
                        if "postroll" not in clip else None
                    ),
                })
            return result

    def get_wav(self, recording_id: str) -> bytes | None:
        with self._lock:
            clip = next(
                (item for item in self._completed if item["id"] == recording_id),
                None,
            )
            if clip is None:
                return None
            pcm = bytes(clip["pcm"])
        return _finite_wav(pcm, self.sample_rate)

    def update_metadata(self, recording_id: str, metadata: dict[str, Any]) -> None:
        with self._lock:
            clips = [*self._completed]
            if self._active:
                clips.append(self._active)
            for clip in clips:
                if clip.get("id") == recording_id:
                    if metadata.get("frequency_mhz") is not None:
                        clip["frequency_mhz"] = metadata["frequency_mhz"]
                    channel = str(metadata.get("channel") or "").strip()
                    if channel and "unknown" not in channel.lower():
                        clip["channel"] = channel
                    return


_marine_recordings = MarineRecordingStore()


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
                _marine_recordings.observe_live_chunk(pcm, time.monotonic())
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


_SCAN_ACTIVITY_RE = re.compile(
    r"^(?P<epoch>\d+(?:\.\d+)?)\s+.*?Activity on "
    r"(?P<frequency>\d+(?:\.\d+)?) MHz(?: \((?P<label>[^)]*)\))?"
)


def _poll_scan_statistics(
    observed_epoch: float | None = None,
    *,
    force: bool = False,
) -> tuple[dict[str, Any] | None, float | None]:
    """Track per-channel squelch counter changes without needing journal access."""
    global _scan_stats_last_poll_epoch, _scan_stats_squelch_counts
    global _scan_stats_snapshot, _scan_stats_snapshot_epoch

    moment = time.time() if observed_epoch is None else float(observed_epoch)
    with _scan_stats_lock:
        if not force and moment - _scan_stats_last_poll_epoch < SCAN_STATS_POLL_INTERVAL_SECONDS:
            return _scan_stats_snapshot, _scan_stats_snapshot_epoch
        _scan_stats_last_poll_epoch = moment

    try:
        document = config.get_traffic_voice_config()
        settings = (document.get("traffic_voice") or document) if isinstance(document, dict) else {}
        backend = settings.get("backend") or {}
        stats_path = str(backend.get("stats_file") or "/run/sdrcc-traffic-voice/channel-stats.prom")
        try:
            threshold = float(backend.get("squelch_snr_db") or 6.0)
        except (TypeError, ValueError):
            threshold = 6.0
        from core import traffic_voice

        snapshot = traffic_voice.read_statistics(
            stats_path,
            possible_active_snr_db=threshold,
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, ImportError):
        snapshot = None

    if not snapshot or not snapshot.get("available") or not snapshot.get("fresh"):
        with _scan_stats_lock:
            _scan_stats_snapshot = None
            _scan_stats_snapshot_epoch = None
        return None, None

    with _scan_stats_lock:
        previous_counts = dict(_scan_stats_squelch_counts)

    counts: dict[str, int] = {}
    changes: list[tuple[float, dict[str, Any]]] = []
    for item in snapshot.get("channels") or []:
        try:
            frequency = round(float(item.get("frequency_mhz")), 6)
            count = int(item.get("squelch_count") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if frequency <= 0:
            continue
        key = f"{frequency:.6f}"
        counts[key] = count
        previous = previous_counts.get(key)
        if previous is not None and count > previous:
            label = str(item.get("label") or "Marine channel").strip()
            changes.append((moment, {
                "channel": label,
                "frequency_mhz": frequency,
            }))

    with _scan_stats_lock:
        _scan_stats_squelch_counts = counts
        _scan_stats_events.extend(changes)
        _scan_stats_snapshot = snapshot
        _scan_stats_snapshot_epoch = moment
    return snapshot, moment


def _scan_statistics_metadata(started_epoch: float) -> dict[str, Any] | None:
    """Resolve a clip from a nearby squelch-counter edge or one active channel."""
    snapshot, snapshot_epoch = _poll_scan_statistics()
    with _scan_stats_lock:
        events = tuple(_scan_stats_events)

    close_events = [
        (abs(event_epoch - started_epoch), metadata)
        for event_epoch, metadata in events
        if abs(event_epoch - started_epoch) <= SCAN_STATS_MATCH_TOLERANCE_SECONDS
    ]
    if close_events:
        return min(close_events, key=lambda item: item[0])[1]

    if (
        not snapshot
        or snapshot_epoch is None
        or abs(snapshot_epoch - started_epoch) > SCAN_STATS_MATCH_TOLERANCE_SECONDS
    ):
        return None
    active = [item for item in snapshot.get("channels") or [] if item.get("possible_active")]
    if len(active) != 1:
        return None
    item = active[0]
    try:
        frequency = round(float(item.get("frequency_mhz")), 6)
    except (TypeError, ValueError):
        return None
    if frequency <= 0:
        return None
    return {
        "channel": str(item.get("label") or "Marine channel").strip(),
        "frequency_mhz": frequency,
    }


def _marine_channel_metadata(
    started_epoch: float,
    *,
    include_scan_log: bool = True,
) -> dict[str, Any]:
    """Resolve fixed channels directly and scanned channels from RTLSDR-Airband logs."""
    fallback = {"channel": "Marine scan · channel unknown", "frequency_mhz": None}
    try:
        document = config.get_traffic_voice_config()
        settings = (document.get("traffic_voice") or document) if isinstance(document, dict) else {}
        marine = (settings.get("modes") or {}).get("marine_ais") or {}
        channels = marine.get("channels") or []
        if marine.get("tuning_mode") == "fixed":
            selected_id = str(marine.get("selected_channel_id") or "")
            selected = next((item for item in channels if str(item.get("id")) == selected_id), None)
            if selected:
                return {
                    "channel": str(selected.get("label") or "Marine channel"),
                    "frequency_mhz": round(float(selected["frequency_mhz"]), 6),
                }
        stats_metadata = _scan_statistics_metadata(started_epoch)
        if not include_scan_log:
            return stats_metadata or fallback

        # RTLSDR-Airband logs when a scanned channel opens squelch, which may
        # happen before the first gated audio packet starts a recording. Prefer
        # a close event; otherwise use the latest recent event before the clip,
        # provided no newer channel event has superseded it.
        command = [
            "/usr/bin/journalctl", "--unit=sdrcc-traffic-voice.service",
            "--since", f"@{max(0.0, started_epoch - SCAN_ACTIVITY_LOOKBACK_SECONDS):.3f}",
            "--output=short-unix", "--no-pager", "-n", "60",
        ]
        result = subprocess.run(
            command, text=True, capture_output=True, timeout=1.2, check=False,
        )
        if result.returncode != 0:
            return fallback
        close_candidates: list[tuple[float, dict[str, Any]]] = []
        recent_prior_candidates: list[tuple[float, dict[str, Any]]] = []
        for line in result.stdout.splitlines():
            match = _SCAN_ACTIVITY_RE.search(line.strip())
            if not match:
                continue
            event_epoch = float(match.group("epoch"))
            age = started_epoch - event_epoch
            if age < -SCAN_ACTIVITY_MATCH_TOLERANCE_SECONDS:
                continue
            if age > SCAN_ACTIVITY_LOOKBACK_SECONDS:
                continue
            frequency = round(float(match.group("frequency")), 6)
            channel = next((
                item for item in channels
                if abs(float(item.get("frequency_mhz") or 0.0) - frequency) <= 0.0005
            ), None)
            label = str((channel or {}).get("label") or match.group("label") or "Marine channel")
            metadata = {
                "channel": label,
                "frequency_mhz": frequency,
            }
            delta = abs(age)
            if delta <= SCAN_ACTIVITY_MATCH_TOLERANCE_SECONDS:
                close_candidates.append((delta, metadata))
            elif event_epoch <= started_epoch:
                recent_prior_candidates.append((event_epoch, metadata))
        if close_candidates:
            return min(close_candidates, key=lambda item: item[0])[1]
        if stats_metadata:
            return stats_metadata
        if recent_prior_candidates:
            return max(recent_prior_candidates, key=lambda item: item[0])[1]
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    return fallback


def _resolve_recording_channel(recording_id: str, started_epoch: float) -> None:
    """Retry briefly because scanner activity and its UDP audio arrive together."""
    for attempt in range(SCAN_CHANNEL_RESOLUTION_ATTEMPTS):
        metadata = _marine_channel_metadata(started_epoch)
        channel = str(metadata.get("channel") or "").strip()
        if (
            metadata.get("frequency_mhz") is not None
            and channel
            and "unknown" not in channel.lower()
        ):
            _marine_recordings.update_metadata(recording_id, metadata)
            return
        if attempt + 1 < SCAN_CHANNEL_RESOLUTION_ATTEMPTS:
            time.sleep(SCAN_CHANNEL_RESOLUTION_RETRY_SECONDS)


def _listen_recordings() -> None:
    global _recording_listener_error, _recording_listener_retry_at
    global _last_recording_packet_epoch
    try:
        host, port, _sample_rate = _recording_settings()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)
            server.bind((host, port))
            server.settimeout(0.2)
            with _lock:
                _recording_listener_error = None
            _poll_scan_statistics(time.time(), force=True)
            while True:
                try:
                    payload, _address = server.recvfrom(65536)
                except socket.timeout:
                    _poll_scan_statistics(time.time())
                    _marine_recordings.finish_if_idle()
                    continue
                pcm = float32_to_pcm16(payload)
                if not pcm:
                    continue
                received_at = time.monotonic()
                started_epoch = time.time()
                _poll_scan_statistics(started_epoch)
                needs_channel = _marine_recordings.needs_new_recording(received_at)
                metadata = (
                    _marine_channel_metadata(started_epoch, include_scan_log=False)
                    if needs_channel else None
                )
                recording_id, started = _marine_recordings.observe_gated_chunk(
                    pcm, received_at, metadata,
                )
                if started and needs_channel and metadata and "unknown" in metadata["channel"].lower():
                    threading.Thread(
                        target=_resolve_recording_channel,
                        args=(recording_id, started_epoch),
                        daemon=True,
                        name="sdrcc-traffic-voice-channel-label",
                    ).start()
                with _lock:
                    _last_recording_packet_epoch = time.time()
    except Exception as error:  # noqa: BLE001 - recording must not break live audio
        _marine_recordings.finish_if_idle(force=True)
        with _lock:
            _recording_listener_error = str(error)
            _recording_listener_retry_at = time.monotonic() + 30.0


def ensure_listener() -> None:
    global _listener, _recording_listener
    with _lock:
        if _listener is None or not _listener.is_alive():
            _listener = threading.Thread(
                target=_listen,
                daemon=True,
                name="sdrcc-traffic-voice-audio",
            )
            _listener.start()
        if (
            (_recording_listener is None or not _recording_listener.is_alive())
            and time.monotonic() >= _recording_listener_retry_at
        ):
            _recording_listener = threading.Thread(
                target=_listen_recordings,
                daemon=True,
                name="sdrcc-traffic-voice-recorder",
            )
            _recording_listener.start()


def get_status() -> dict[str, Any]:
    ensure_listener()
    host, port, sample_rate = _settings()
    denoisers = traffic_voice_denoise.capabilities()
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
            "marine_recordings": _marine_recordings.list_recordings(),
            "recording_listener_error": _recording_listener_error,
            "last_recording_packet_age_seconds": (
                round(time.time() - _last_recording_packet_epoch, 2)
                if _last_recording_packet_epoch is not None else None
            ),
            "observers": ["traffic_voice_atis"],
            "denoisers": denoisers,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }


def get_recording_wav(recording_id: str) -> bytes | None:
    """Return a completed Marine replay as a finite WAV file."""
    if not re.fullmatch(r"[a-f0-9]{32}", str(recording_id or "")):
        return None
    return _marine_recordings.get_wav(recording_id)


def save_recording(recording_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist one temporary Marine replay plus bounded ATIS/AIS metadata."""
    if not re.fullmatch(r"[a-f0-9]{32}", str(recording_id or "")):
        raise ValueError("Invalid recording id")
    wav = _marine_recordings.get_wav(recording_id)
    if wav is None:
        raise ValueError("Recording is no longer available or is not complete")
    metadata = metadata if isinstance(metadata, dict) else {}
    safe = {
        "recording_id": recording_id,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "channel": str(metadata.get("channel") or "")[:120],
        "frequency_mhz": metadata.get("frequency_mhz"),
        "atis": metadata.get("atis") if isinstance(metadata.get("atis"), dict) else {},
        "ais_match": metadata.get("ais_match") if isinstance(metadata.get("ais_match"), dict) else {},
    }
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    mmsi = str((safe["ais_match"] or {}).get("mmsi") or "")
    suffix = f"-mmsi-{mmsi}" if re.fullmatch(r"\d{9}", mmsi) else ""
    stem = f"{stamp}{suffix}-{recording_id[:8]}"
    SAVED_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    wav_path = SAVED_RECORDINGS_DIR / f"{stem}.wav"
    json_path = SAVED_RECORDINGS_DIR / f"{stem}.json"
    wav_path.write_bytes(wav)
    json_path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "ok": True, "recording_id": recording_id, "filename": wav_path.name,
        "metadata_filename": json_path.name, "saved_at": safe["saved_at"],
    }


class MarineSpeechFilter:
    """3 kHz fourth-order Butterworth low-pass for browser PCM only.

    Two biquads retain their state across chunks. No dependencies or changes
    to demodulation, de-emphasis, squelch or the ATIS observer are required.
    """

    def __init__(self, sample_rate: int, cutoff_hz: float = 3000.0) -> None:
        if not 0 < cutoff_hz < sample_rate / 2:
            raise ValueError("Marine speech filter cutoff must be below Nyquist")
        omega = 2.0 * math.pi * cutoff_hz / sample_rate
        cosine, sine = math.cos(omega), math.sin(omega)
        self.sections = []
        for q in (0.541196100146197, 1.306562964876377):
            alpha = sine / (2.0 * q)
            a0 = 1.0 + alpha
            b0 = (1.0 - cosine) / (2.0 * a0)
            self.sections.append((b0, 2.0 * b0, b0,
                                  -2.0 * cosine / a0, (1.0 - alpha) / a0))
        self.reset()

    def reset(self) -> None:
        self.state = [[0.0, 0.0] for _ in self.sections]

    def process(self, pcm: bytes) -> bytes:
        output = bytearray(len(pcm))
        for index, (sample,) in enumerate(struct.iter_unpack("<h", pcm)):
            value = float(sample)
            for coefficients, state in zip(self.sections, self.state):
                b0, b1, b2, a1, a2 = coefficients
                filtered = b0 * value + state[0]
                state[0] = b1 * value - a1 * filtered + state[1]
                state[1] = b2 * value - a2 * filtered
                value = filtered
            struct.pack_into("<h", output, index * 2,
                             max(-32768, min(32767, round(value))))
        return bytes(output)


class LiveWavStream:
    def __init__(self, speech_filter: str = "normal", denoise: str = "off", mode: str | None = None) -> None:
        global _active_clients, _total_clients
        self._closed = True
        self._processor = None
        self._processing_lock = threading.RLock()
        if denoise not in traffic_voice_denoise.ENGINES:
            raise ValueError("Unknown denoiser")
        if mode not in (None, "marine_ais", "airband_adsb"):
            raise ValueError("Unknown audio mode")
        self._requested_engine = denoise
        self._explicit_mode = mode
        if speech_filter not in SPEECH_FILTERS:
            raise ValueError("Unknown speech filter")
        self._filter_enabled = speech_filter != "off"
        self._sample_rate = _settings()[2]
        self._speech_filter = MarineSpeechFilter(
            self._sample_rate, SPEECH_FILTERS[speech_filter] or 3000.0)
        self._marine_audio = False
        self._mode_check_at = 0.0
        self._last_chunk_at = 0.0
        ensure_listener()
        with _lock:
            if _active_clients >= MAX_CLIENTS:
                raise RuntimeError("Maximum aantal Traffic Voice audioclients bereikt")
            _active_clients += 1
            _total_clients += 1
            self._next_sequence = _sequence + 1
        self._closed = False
        self._header_sent = False
        self._reset_processor()

    def __iter__(self) -> "LiveWavStream":
        return self

    def __next__(self) -> bytes:
        if self._closed:
            raise StopIteration
        if not self._header_sent:
            self._header_sent = True
            return _wav_header(self._sample_rate)
        chunk, discontinuity = self._next_chunk()
        now = time.monotonic()
        with self._processing_lock:
            if self._closed:
                raise StopIteration
            if now >= self._mode_check_at:
                active_mode = config.get_traffic_voice_config().get("selected_mode")
                # Explicit per-mode streams end when the station changes mode.
                if self._explicit_mode and active_mode != self._explicit_mode:
                    self.close()
                    raise StopIteration
                marine = active_mode == "marine_ais"
                if marine != self._marine_audio:
                    self._speech_filter.reset()
                    self._reset_processor()
                self._marine_audio = marine
                self._mode_check_at = now + 1.0
            if discontinuity or (self._last_chunk_at and now - self._last_chunk_at > 0.5):
                self._speech_filter.reset()
                self._reset_processor()
            self._last_chunk_at = now
            # Both processors run after the ATIS fork, outside the queue lock.
            if self._processor:
                try:
                    chunk = self._processor.process(chunk)
                except (OSError, RuntimeError, ValueError) as error:
                    traffic_voice_denoise.report_error(self._requested_engine, error)
                    self._processor.close()
                    self._processor = None
            enabled = self._filter_enabled and (self._explicit_mode is not None or self._marine_audio)
            return self._speech_filter.process(chunk) if enabled else chunk

    def _reset_processor(self):
        if self._processor:
            self._processor.close()
            self._processor = None
        if self._requested_engine != "off":
            try:
                if self._sample_rate != 16000:
                    raise ValueError("Denoising requires 16 kHz audio")
                self._processor = traffic_voice_denoise.Denoiser(self._requested_engine)
                traffic_voice_denoise.report_error(self._requested_engine, None)
            except (OSError, RuntimeError, ValueError, AttributeError) as error:
                traffic_voice_denoise.report_error(self._requested_engine, error)


    def _next_chunk(self) -> tuple[bytes, bool]:
        deadline = time.monotonic() + 12.0
        with _lock:
            while not self._closed:
                for sequence, chunk in _chunks:
                    if sequence >= self._next_sequence:
                        discontinuity = sequence != self._next_sequence
                        self._next_sequence = sequence + 1
                        return chunk, discontinuity
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                _lock.wait(min(1.0, remaining))
        self.close()
        raise StopIteration

    def close(self) -> None:
        global _active_clients
        if self._closed:
            return
        with self._processing_lock:
            if self._closed:
                return
            with _lock:
                self._closed = True
                _active_clients = max(0, _active_clients - 1)
                _lock.notify_all()
            if self._processor:
                self._processor.close()
                self._processor = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def stream_wav(speech_filter: str = "normal", denoise: str = "off", mode: str | None = None) -> Iterator[bytes]:
    return LiveWavStream(speech_filter, denoise, mode)
