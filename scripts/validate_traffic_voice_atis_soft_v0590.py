#!/usr/bin/env python3
"""Validate SDRCC Traffic Voice ATIS weak-signal soft decoding."""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import traffic_voice_atis  # noqa: E402


def passed(message: str) -> None:
    print(f"PASS: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)
    passed(message)


def ten_unit(value: int) -> list[int]:
    return list(traffic_voice_atis._ten_unit_bits(value))


def packet_symbols() -> list[int]:
    groups = [92, 44, 8, 96, 29]
    ecc = 121
    for value in groups:
        ecc ^= value
    ecc ^= 127
    return [
        125, 111, 125, 110, 125, 109, 125, 108,
        125, 107, 125, 106, 121, 105, 121, 104,
        groups[0], 121, groups[1], 121, groups[2], groups[0],
        groups[3], groups[1], groups[4], groups[2], 127, groups[3],
        ecc, groups[4], 127, 127, 127, ecc,
    ]


def packet_bits() -> np.ndarray:
    return np.asarray(
        [bit for symbol in packet_symbols() for bit in ten_unit(symbol)],
        dtype=np.int8,
    )


def synthesize(
    *,
    seed: int = 4,
    amplitude: float = 0.32,
    noise: float = 0.018,
    tone_offset_hz: float = 0.0,
) -> np.ndarray:
    sample_rate = traffic_voice_atis.SAMPLE_RATE_HZ
    prefix = [1, 0] * 10
    framed = np.asarray(prefix + packet_bits().tolist() + [1] * 40, dtype=np.int8)
    count = int(len(framed) * sample_rate / traffic_voice_atis.BIT_RATE)
    indexes = np.minimum(
        (np.arange(count) * traffic_voice_atis.BIT_RATE / sample_rate).astype(int),
        len(framed) - 1,
    )
    frequencies = np.where(
        framed[indexes] == 1,
        traffic_voice_atis.LOW_TONE_HZ,
        traffic_voice_atis.HIGH_TONE_HZ,
    ) + float(tone_offset_hz)
    phase = np.cumsum(2.0 * np.pi * frequencies / sample_rate)
    random = np.random.default_rng(seed)
    return (
        amplitude * np.sin(phase) + noise * random.standard_normal(count)
    ).astype(np.float32)


def soft_discriminator(
    *,
    weak_wrong_units: tuple[int, ...] = (),
    level: float = 0.90,
    weak_level: float = 0.08,
) -> np.ndarray:
    bits = packet_bits()
    units = np.where(bits == 1, level, -level).astype(np.float64)
    for index in weak_wrong_units:
        units[index] = -np.sign(units[index]) * weak_level

    step = traffic_voice_atis.SAMPLE_RATE_HZ / traffic_voice_atis.BIT_RATE
    length = int(np.ceil((len(units) + 2) * step)) + 4
    discriminator = np.zeros(length, dtype=np.float64)
    for index, value in enumerate(units):
        start = max(0, int(np.floor(index * step)))
        end = min(length, int(np.ceil((index + 1) * step)) + 1)
        discriminator[start:end] = value
    return discriminator


def unit_index(symbol_position: int, unit_offset: int) -> int:
    return (symbol_position - 1) * 10 + unit_offset


def decode_discriminator(discriminator: np.ndarray):
    return traffic_voice_atis._decode_packet(
        discriminator,
        0.0,
        traffic_voice_atis.SAMPLE_RATE_HZ,
        traffic_voice_atis.BIT_RATE,
        0.90,
    )


def validate_clean_and_noise() -> None:
    require(
        traffic_voice_atis.DECODER_VERSION == 4,
        "ATIS decoder version 4 is active",
    )
    require(
        traffic_voice_atis.DECODER_PROFILE == "sdrcc-atis-v4",
        "shared ATIS decoder profile is active",
    )
    decoded = traffic_voice_atis.decode_samples(synthesize())
    require(len(decoded) == 1, "clean synthetic ATIS packet decodes exactly once")
    require(decoded[0]["atis_code"] == "9244089629", "clean identity remains exact")
    require(decoded[0]["soft_decoding_used"] is False, "clean packet stays on hard path")
    shifted = traffic_voice_atis.decode_samples(synthesize(tone_offset_hz=25.0))
    require(len(shifted) == 1, "ATIS tone bank tolerates a +25 Hz transmitter/clock offset")
    require(shifted[0]["atis_code"] == "9244089629", "tone-offset identity remains exact")

    silence = np.zeros(traffic_voice_atis.SAMPLE_RATE_HZ, dtype=np.float32)
    require(traffic_voice_atis.decode_samples(silence) == [], "silence creates no ATIS result")

    random = np.random.default_rng(10).standard_normal(
        traffic_voice_atis.SAMPLE_RATE_HZ,
    ).astype(np.float32) * 0.10
    require(
        traffic_voice_atis.decode_samples(random) == [],
        "wideband noise creates no ATIS result",
    )


def validate_soft_duplicate_recovery() -> None:
    # Damage one checksum unit in both time-diverse copies of the first identity
    # group.  Hard decoding must reject both copies, while their analogue
    # confidence plus ECC still identify one unique original value.
    damaged = (
        unit_index(17, 7),
        unit_index(22, 7),
    )
    decoded = decode_discriminator(
        soft_discriminator(weak_wrong_units=damaged),
    )
    require(decoded is not None, "soft path recovers two damaged redundant copies")
    require(decoded["atis_code"] == "9244089629", "soft recovery preserves exact identity")
    require(decoded["soft_decoding_used"] is True, "soft recovery is explicitly reported")
    require(decoded["soft_corrected_symbols"] >= 1, "soft-corrected symbol count is reported")
    require(decoded["ecc_received"] == decoded["ecc_calculated"] == 3, "ECC still validates recovery")


def validate_tolerant_phasing() -> None:
    # Two phasing symbols have one weakly inverted checksum unit each.  The
    # complete phasing pattern remains strongly correlated, so the packet may
    # proceed to the strict message/ECC checks.
    damaged = (
        unit_index(2, 7),
        unit_index(9, 8),
    )
    decoded = decode_discriminator(
        soft_discriminator(weak_wrong_units=damaged),
    )
    require(decoded is not None, "damaged phasing symbols no longer discard a coherent packet")
    require(decoded["atis_code"] == "9244089629", "tolerant phasing keeps identity exact")
    require(decoded["phasing_exact_symbols"] == 14, "phasing damage is measured, not ignored")



def validate_ambiguous_letter_rejected() -> None:
    # F (06) and G (07) differ by only one information bit plus its checksum
    # consequence. Make both repeated letter symbols locally ambiguous while
    # leaving ECC intact. The decoder must reject rather than guess.
    original = packet_symbols
    try:
        def packet_with_f() -> list[int]:
            groups = [92, 44, 6, 96, 29]
            ecc = 121
            for value in groups:
                ecc ^= value
            ecc ^= 127
            return [
                125, 111, 125, 110, 125, 109, 125, 108,
                125, 107, 125, 106, 121, 105, 121, 104,
                groups[0], 121, groups[1], 121, groups[2], groups[0],
                groups[3], groups[1], groups[4], groups[2], 127, groups[3],
                ecc, groups[4], 127, 127, 127, ecc,
            ]

        globals()["packet_symbols"] = packet_with_f
        discriminator = soft_discriminator()
        step = traffic_voice_atis.SAMPLE_RATE_HZ / traffic_voice_atis.BIT_RATE
        for symbol_position in (21, 26):
            for unit_offset in (0, 9):
                index = unit_index(symbol_position, unit_offset)
                start = max(0, int(np.floor(index * step)))
                end = min(len(discriminator), int(np.ceil((index + 1) * step)) + 1)
                discriminator[start:end] = 0.0
        require(
            decode_discriminator(discriminator) is None,
            "ambiguous F/G callsign-letter soft correction is rejected",
        )
    finally:
        globals()["packet_symbols"] = original

def validate_no_ecc_guessing() -> None:
    # Destroy confidence in the complete message section.  A valid phasing
    # sequence by itself must never be enough to manufacture an identity.
    discriminator = soft_discriminator()
    step = traffic_voice_atis.SAMPLE_RATE_HZ / traffic_voice_atis.BIT_RATE
    start = int(np.floor(16 * 10 * step))
    end = int(np.ceil(34 * 10 * step)) + 1
    discriminator[start:end] = 0.0
    require(
        decode_discriminator(discriminator) is None,
        "ECC cannot manufacture an identity from confidence-free message data",
    )


def main() -> int:
    validate_clean_and_noise()
    validate_soft_duplicate_recovery()
    validate_tolerant_phasing()
    validate_ambiguous_letter_rejected()
    validate_no_ecc_guessing()
    print("VALIDATION PASS: SDRCC Traffic Voice ATIS soft decoding")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, ValueError) as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        raise SystemExit(1)
