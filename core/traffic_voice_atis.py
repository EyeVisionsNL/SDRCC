#!/usr/bin/env python3
"""Passive Automatic Transmitter Identification System (ATIS) decoder.

RTLSDR-Airband and :mod:`core.traffic_voice_audio` retain all receiver and
socket ownership.  This module only observes copies of the already received
16 kHz audio blocks through a bounded in-process queue.  Decoded state is
ephemeral and read-only; it never changes receiver, service, configuration or
AIS state.
"""

from __future__ import annotations

from datetime import datetime
import math
import queue
import threading
import time
from typing import Any

import numpy as np

from core import config


DECODER_VERSION = 2
SAMPLE_RATE_HZ = 16_000
BIT_RATE = 1_200.0
LOW_TONE_HZ = 1_300.0
HIGH_TONE_HZ = 2_100.0
PACKET_SYMBOLS = 34
PACKET_BITS = PACKET_SYMBOLS * 10
BUFFER_SECONDS = 1.0
SCAN_INTERVAL_SECONDS = 0.25
RESULT_FRESH_SECONDS = 120.0
QUEUE_BLOCKS = 64

_PHASING_SYMBOLS = (
    125, 111, 125, 110, 125, 109, 125, 108,
    125, 107, 125, 106, 121, 105, 121, 104,
)

# Country metadata is presentation-only. ATIS-to-vessel correlation no longer
# depends on a guessed national callsign prefix; it is derived from each live
# AIS target's own MMSI/callsign in receiver_monitor.
_MID_COUNTRIES = {
    203: "Austria",
    205: "Belgium",
    211: "Germany",
    218: "Germany",
    226: "France",
    227: "France",
    228: "France",
    244: "Netherlands",
    245: "Netherlands",
    246: "Netherlands",
    253: "Luxembourg",
    269: "Switzerland",
}

# Preserve the familiar Dutch two-letter projection for display only.
# Foreign RAINWAT callsigns may encode their second OR third letter, so those
# are correlated against live AIS instead of being reconstructed heuristically.
_SIMPLE_CALLSIGN_PREFIXES = {
    244: "P",
    245: "P",
    246: "P",
}
_state_lock = threading.RLock()
_audio_queue: queue.Queue[tuple[bytes, float]] = queue.Queue(maxsize=QUEUE_BLOCKS)
_worker: threading.Thread | None = None
_worker_error: str | None = None
_blocks_observed = 0
_blocks_dropped = 0
_samples_observed = 0
_candidate_count = 0
_valid_count = 0
_duplicate_count = 0
_last_result: dict[str, Any] | None = None


def _ten_unit_bits(value: int) -> tuple[int, ...]:
    """Return the ten transmitted B/Y units as zero/one integers."""
    if value < 0 or value > 127:
        raise ValueError("ATIS symbol must be between 0 and 127")
    bits: list[int] = []
    b_count = 0
    for bit in range(7):
        unit = 1 if value & (1 << bit) else 0
        bits.append(unit)
        if unit == 0:
            b_count += 1
    bits.extend(1 if b_count & mask else 0 for mask in (4, 2, 1))
    return tuple(bits)


_PHASING_BITS = np.asarray(
    [bit for symbol in _PHASING_SYMBOLS for bit in _ten_unit_bits(symbol)],
    dtype=np.int8,
)
_PHASING_POLARITY = np.where(_PHASING_BITS == 1, 1.0, -1.0)


def _decode_symbol(bits: np.ndarray, position: int) -> tuple[int | None, bool]:
    offset = (position - 1) * 10
    units = bits[offset:offset + 10]
    if len(units) != 10:
        return None, False
    information = units[:7]
    b_count = int(np.count_nonzero(information == 0))
    value = sum(int(unit) << bit for bit, unit in enumerate(information))
    expected = np.asarray(
        [1 if b_count & mask else 0 for mask in (4, 2, 1)],
        dtype=np.int8,
    )
    return int(value), bool(np.array_equal(units[7:], expected))


def _choose_time_diverse_symbol(
    symbols: dict[int, tuple[int | None, bool]],
    primary: int,
    repeated: int,
) -> tuple[int | None, bool]:
    first, first_ok = symbols[primary]
    second, second_ok = symbols[repeated]
    if first_ok and second_ok:
        return (first, False) if first == second else (None, False)
    if first_ok:
        return first, True
    if second_ok:
        return second, True
    return None, False


def _identity_projection(groups: list[int]) -> dict[str, Any] | None:
    if len(groups) != 5 or any(value < 0 or value > 99 for value in groups):
        return None
    atis_code = "".join(f"{value:02d}" for value in groups)
    if len(atis_code) != 10 or not atis_code.startswith("9"):
        return None
    mid = int(atis_code[1:4])
    letter_code = int(atis_code[4:6])
    country = _MID_COUNTRIES.get(mid)
    callsign = None
    prefix = _SIMPLE_CALLSIGN_PREFIXES.get(mid)
    if prefix and 1 <= letter_code <= 26:
        callsign = f"{prefix}{chr(64 + letter_code)}{atis_code[6:]}"
    return {
        "atis_code": atis_code,
        "mid": mid,
        "country": country,
        "callsign": callsign,
    }


def _decode_packet(
    discriminator: np.ndarray,
    start_sample: float,
    sample_rate: int,
    bit_rate: float,
    phasing_score: float,
) -> dict[str, Any] | None:
    step = float(sample_rate) / bit_rate
    centers = start_sample + (np.arange(PACKET_BITS, dtype=np.float64) + 0.5) * step
    if centers[-1] >= len(discriminator) - 1:
        return None
    values = np.interp(centers, np.arange(len(discriminator)), discriminator)
    bits = np.where(values >= 0.0, 1, 0).astype(np.int8)
    symbols = {
        position: _decode_symbol(bits, position)
        for position in range(1, PACKET_SYMBOLS + 1)
    }

    # A complete phasing sequence prevents a speech-like false positive from
    # reaching the message parser.
    if any(
        not symbols[position][1] or symbols[position][0] != expected
        for position, expected in enumerate(_PHASING_SYMBOLS, start=1)
    ):
        return None

    format_one, corrected_one = _choose_time_diverse_symbol(symbols, 13, 18)
    format_two, corrected_two = _choose_time_diverse_symbol(symbols, 15, 20)
    if format_one != 121 or format_two != 121:
        return None

    groups: list[int] = []
    corrections = int(corrected_one) + int(corrected_two)
    for primary, repeated in ((17, 22), (19, 24), (21, 26), (23, 28), (25, 30)):
        value, corrected = _choose_time_diverse_symbol(symbols, primary, repeated)
        if value is None:
            return None
        groups.append(value)
        corrections += int(corrected)

    eos, corrected = _choose_time_diverse_symbol(symbols, 27, 32)
    corrections += int(corrected)
    if eos != 127:
        return None
    received_ecc, corrected = _choose_time_diverse_symbol(symbols, 29, 34)
    corrections += int(corrected)
    if received_ecc is None:
        return None

    calculated_ecc = 121
    for value in groups:
        calculated_ecc ^= value
    calculated_ecc ^= 127
    if received_ecc != calculated_ecc:
        return None

    identity = _identity_projection(groups)
    if identity is None:
        return None
    return {
        **identity,
        "format_specifier": 121,
        "end_of_sequence": 127,
        "ecc_received": int(received_ecc),
        "ecc_calculated": int(calculated_ecc),
        "time_diversity_used": corrections > 0,
        "corrected_symbols": corrections,
        "phasing_score": round(float(phasing_score), 4),
        "sample_index": int(round(start_sample)),
        "sample_time_seconds": round(float(start_sample) / sample_rate, 6),
        "validation": "ten_unit_time_diversity_ecc",
    }


def _tone_discriminator(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    window_length = max(9, int(round(sample_rate / BIT_RATE)))
    if window_length % 2 == 0:
        window_length += 1
    offsets = np.arange(window_length, dtype=np.float64)
    window = np.hanning(window_length)

    def energy(frequency: float) -> np.ndarray:
        kernel = window * np.exp(-2j * np.pi * frequency * offsets / sample_rate)
        filtered = np.convolve(samples, kernel[::-1], mode="same")
        return np.square(filtered.real) + np.square(filtered.imag)

    low = energy(LOW_TONE_HZ)
    high = energy(HIGH_TONE_HZ)
    return (low - high) / (low + high + 1e-7)


def _refine_candidate(
    discriminator: np.ndarray,
    start_sample: float,
    sample_rate: int,
) -> tuple[float, float, float, int]:
    best: tuple[int, float, float, float] | None = None
    axis = np.arange(len(discriminator))
    for bit_rate in (1198.0, 1200.0, 1202.0):
        step = sample_rate / bit_rate
        for offset in (-2.0, -1.0, 0.0, 1.0, 2.0):
            candidate = start_sample + offset
            centers = candidate + (np.arange(len(_PHASING_BITS)) + 0.5) * step
            if centers[0] < 0 or centers[-1] >= len(discriminator) - 1:
                continue
            values = np.interp(centers, axis, discriminator)
            decided = np.where(values >= 0.0, 1.0, -1.0)
            hard_matches = int(np.count_nonzero(decided == _PHASING_POLARITY))
            score = float(
                np.dot(values, _PHASING_POLARITY)
                / (np.sum(np.abs(values)) + 1e-9)
            )
            key = (hard_matches, score, -abs(offset), -abs(bit_rate - BIT_RATE))
            if best is None or key > (best[0], best[1], -abs(best[2]), -abs(best[3] - BIT_RATE)):
                best = (hard_matches, score, offset, bit_rate)
    if best is None:
        return start_sample, BIT_RATE, 0.0, 0
    return start_sample + best[2], best[3], best[1], best[0]


def decode_samples(samples: np.ndarray, sample_rate: int = SAMPLE_RATE_HZ) -> list[dict[str, Any]]:
    """Decode complete, validated ATIS packets from mono float audio."""
    if sample_rate < 8_000:
        raise ValueError("ATIS decoding requires an audio sample rate of at least 8 kHz")
    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    if len(audio) < int((PACKET_BITS + 10) * sample_rate / BIT_RATE):
        return []
    audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
    audio = np.clip(audio, -1.0, 1.0)
    discriminator = _tone_discriminator(audio, sample_rate)
    step = sample_rate / BIT_RATE
    template_length = len(_PHASING_POLARITY)
    minimum_matches = template_length - 10
    candidates: list[tuple[float, float]] = []
    axis = np.arange(len(discriminator))

    # One sample of phase resolution is sufficient at 16 kHz.  A later local
    # refinement handles the small real-world modulation-rate error.
    for phase in np.arange(0.0, step, 1.0):
        count = int((len(discriminator) - phase) / step)
        if count < template_length:
            continue
        centers = phase + (np.arange(count) + 0.5) * step
        values = np.interp(centers, axis, discriminator)
        decided = np.where(values >= 0.0, 1.0, -1.0)
        hard_correlation = np.correlate(decided, _PHASING_POLARITY, mode="valid")
        hard_matches = np.rint((hard_correlation + template_length) / 2.0).astype(int)
        numerator = np.correlate(values, _PHASING_POLARITY, mode="valid")
        denominator = np.correlate(
            np.abs(values), np.ones(template_length), mode="valid",
        ) + 1e-9
        scores = numerator / denominator
        indexes = np.flatnonzero((hard_matches >= minimum_matches) & (scores >= 0.85))
        for index in indexes:
            start = phase + float(index) * step
            if start + (PACKET_BITS + 1) * step < len(discriminator):
                candidates.append((start, float(scores[index])))

    if not candidates:
        return []
    candidates.sort(key=lambda item: item[0])
    clustered: list[tuple[float, float]] = []
    for start, score in candidates:
        if clustered and start - clustered[-1][0] < step:
            if score > clustered[-1][1]:
                clustered[-1] = (start, score)
        else:
            clustered.append((start, score))

    results: list[dict[str, Any]] = []
    for start, _score in clustered:
        refined_start, bit_rate, score, matches = _refine_candidate(
            discriminator, start, sample_rate,
        )
        if matches < minimum_matches or score < 0.85:
            continue
        decoded = _decode_packet(
            discriminator, refined_start, sample_rate, bit_rate, score,
        )
        if decoded is None:
            continue
        if results and abs(decoded["sample_index"] - results[-1]["sample_index"]) < step:
            if decoded["phasing_score"] > results[-1]["phasing_score"]:
                results[-1] = decoded
        else:
            results.append(decoded)
    return results


def _current_channel_context() -> dict[str, Any]:
    try:
        settings = config.get_traffic_voice_config()
        mode_id = str(settings.get("selected_mode") or "")
        mode = ((settings.get("modes") or {}).get(mode_id) or {})
        context: dict[str, Any] = {
            "mode_id": mode_id or None,
            "tuning_mode": str(mode.get("tuning_mode") or "").lower() or None,
            "channel_id": None,
            "channel_label": None,
            "frequency_mhz": None,
        }
        if mode_id != "marine_ais" or context["tuning_mode"] != "fixed":
            return context
        selected = str(mode.get("selected_channel_id") or "")
        for channel in mode.get("channels") or []:
            if str(channel.get("id") or "") == selected:
                context.update({
                    "channel_id": selected,
                    "channel_label": channel.get("label"),
                    "frequency_mhz": channel.get("frequency_mhz"),
                })
                break
        return context
    except Exception:  # noqa: BLE001 - context is optional observer metadata
        return {
            "mode_id": None,
            "tuning_mode": None,
            "channel_id": None,
            "channel_label": None,
            "frequency_mhz": None,
        }


def _publish_result(result: dict[str, Any], received_epoch: float) -> None:
    global _candidate_count, _duplicate_count, _last_result, _valid_count
    projected = {
        **result,
        **_current_channel_context(),
        "received_at": datetime.fromtimestamp(received_epoch).astimezone().isoformat(
            timespec="milliseconds",
        ),
        "received_epoch": received_epoch,
    }
    with _state_lock:
        _candidate_count += 1
        if (
            _last_result
            and _last_result.get("atis_code") == projected.get("atis_code")
            and abs(float(_last_result.get("received_epoch") or 0.0) - received_epoch) < 1.0
        ):
            _duplicate_count += 1
            return
        _last_result = projected
        _valid_count += 1


def _decode_worker() -> None:
    global _samples_observed, _worker_error
    buffer = np.empty(0, dtype=np.float32)
    buffer_end_epoch: float | None = None
    unscanned_samples = 0
    maximum_samples = int(BUFFER_SECONDS * SAMPLE_RATE_HZ)
    scan_interval = int(SCAN_INTERVAL_SECONDS * SAMPLE_RATE_HZ)
    try:
        while True:
            payload, packet_epoch = _audio_queue.get()
            usable_bytes = len(payload) - (len(payload) % 4)
            if usable_bytes == 0:
                continue
            samples = np.frombuffer(payload[:usable_bytes], dtype="<f4")
            usable = samples[np.isfinite(samples)].astype(np.float32, copy=False)
            if len(usable) != len(samples):
                cleaned = np.zeros(len(samples), dtype=np.float32)
                cleaned[np.isfinite(samples)] = usable
                samples = cleaned
            else:
                samples = usable
            samples = np.clip(samples, -1.0, 1.0)
            if (
                buffer_end_epoch is not None
                and packet_epoch - buffer_end_epoch > 1.0
            ):
                buffer = np.empty(0, dtype=np.float32)
                unscanned_samples = 0
            buffer_end_epoch = packet_epoch
            buffer = np.concatenate((buffer, samples))
            if len(buffer) > maximum_samples:
                buffer = buffer[-maximum_samples:]
            unscanned_samples += len(samples)
            with _state_lock:
                _samples_observed += len(samples)
                _worker_error = None
            if unscanned_samples < scan_interval:
                continue
            unscanned_samples = 0
            for decoded in decode_samples(buffer, SAMPLE_RATE_HZ):
                offset_from_end = len(buffer) - int(decoded["sample_index"])
                received_epoch = packet_epoch - offset_from_end / SAMPLE_RATE_HZ
                _publish_result(decoded, received_epoch)
    except Exception as error:  # noqa: BLE001 - status reports observer failure
        with _state_lock:
            _worker_error = str(error)


def ensure_worker() -> None:
    global _worker
    with _state_lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(
            target=_decode_worker,
            daemon=True,
            name="sdrcc-traffic-voice-atis",
        )
        _worker.start()


def report_observer_error(error: Exception) -> None:
    """Expose an observer fault without allowing it to stop live audio."""
    global _worker_error
    with _state_lock:
        _worker_error = f"{type(error).__name__}: {error}"


def observe_float32(payload: bytes) -> None:
    """Queue one copied backend datagram without delaying the audio bridge."""
    global _blocks_dropped, _blocks_observed
    ensure_worker()
    with _state_lock:
        _blocks_observed += 1
    try:
        _audio_queue.put_nowait((bytes(payload), time.time()))
    except queue.Full:
        with _state_lock:
            _blocks_dropped += 1


def get_status() -> dict[str, Any]:
    with _state_lock:
        latest = dict(_last_result) if _last_result else None
        error = _worker_error
        blocks = _blocks_observed
        dropped = _blocks_dropped
        samples = _samples_observed
        candidates = _candidate_count
        valid = _valid_count
        duplicates = _duplicate_count
        worker_running = bool(_worker and _worker.is_alive())
    now = time.time()
    if latest:
        epoch = float(latest.pop("received_epoch", 0.0) or 0.0)
        age = max(0.0, now - epoch) if epoch else None
        latest["age_seconds"] = round(age, 2) if age is not None else None
        latest["fresh"] = bool(age is not None and age <= RESULT_FRESH_SECONDS)
    return {
        "ok": error is None,
        "decoder_version": DECODER_VERSION,
        "authority": "read_only_audio_observer",
        "transport": "existing_audio_bridge_queue",
        "state": "DECODED" if latest and latest.get("fresh") else (
            "LISTENING" if worker_running else "WAITING"
        ),
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "blocks_observed": blocks,
        "blocks_dropped": dropped,
        "samples_observed": samples,
        "candidate_packets": candidates,
        "valid_packets": valid,
        "duplicate_packets": duplicates,
        "latest": latest,
        "worker_running": worker_running,
        "worker_error": error,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
