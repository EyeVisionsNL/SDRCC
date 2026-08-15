#!/usr/bin/env python3
"""Validate the v0.55.0d passive Traffic Voice ATIS foundation."""

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
    bits: list[int] = []
    b_count = 0
    for bit in range(7):
        unit = 1 if value & (1 << bit) else 0
        bits.append(unit)
        b_count += unit == 0
    bits.extend(1 if b_count & mask else 0 for mask in (4, 2, 1))
    return bits


def packet_bits(*, corrupt_primary: bool = False) -> list[int]:
    groups = [92, 44, 8, 96, 29]
    ecc = 121
    for value in groups:
        ecc ^= value
    ecc ^= 127
    symbols = [
        125, 111, 125, 110, 125, 109, 125, 108,
        125, 107, 125, 106, 121, 105, 121, 104,
        groups[0], 121, groups[1], 121, groups[2], groups[0],
        groups[3], groups[1], groups[4], groups[2], 127, groups[3],
        ecc, groups[4], 127, 127, 127, ecc,
    ]
    bits = [unit for symbol in symbols for unit in ten_unit(symbol)]
    if corrupt_primary:
        bits[(17 - 1) * 10 + 7] ^= 1
    return bits


def synthesize(bits: list[int], *, seed: int = 4) -> np.ndarray:
    sample_rate = traffic_voice_atis.SAMPLE_RATE_HZ
    prefix = [1, 0] * 10
    framed = prefix + bits + [1] * 40
    count = int(len(framed) * sample_rate / traffic_voice_atis.BIT_RATE)
    indexes = np.minimum(
        (np.arange(count) * traffic_voice_atis.BIT_RATE / sample_rate).astype(int),
        len(framed) - 1,
    )
    units = np.asarray(framed, dtype=np.int8)[indexes]
    frequencies = np.where(
        units == 1,
        traffic_voice_atis.LOW_TONE_HZ,
        traffic_voice_atis.HIGH_TONE_HZ,
    )
    phase = np.cumsum(2.0 * np.pi * frequencies / sample_rate)
    random = np.random.default_rng(seed)
    return (0.32 * np.sin(phase) + 0.018 * random.standard_normal(count)).astype(np.float32)


def validate_source_contract() -> None:
    required = [
        "core/traffic_voice_atis.py",
        "core/traffic_voice_audio.py",
        "core/traffic_voice.py",
        "docs/traffic-voice-atis-v0550d.md",
    ]
    for relative in required:
        require((ROOT / relative).is_file(), f"required file present: {relative}")

    decoder = (ROOT / "core/traffic_voice_atis.py").read_text(encoding="utf-8")
    bridge = (ROOT / "core/traffic_voice_audio.py").read_text(encoding="utf-8")
    traffic = (ROOT / "core/traffic_voice.py").read_text(encoding="utf-8")
    require("import socket" not in decoder, "ATIS decoder creates no socket authority")
    require("subprocess" not in decoder, "ATIS decoder creates no process authority")
    require("systemctl" not in decoder, "ATIS decoder creates no service authority")
    require("save_traffic_voice" not in decoder, "ATIS decoder does not write configuration")
    require(bridge.count("server.bind(") == 1, "audio bridge remains the sole UDP listener")
    require(
        "traffic_voice_atis.observe_float32(payload)" in bridge,
        "audio bridge feeds the bounded ATIS observer",
    )
    require(
        "traffic_voice_atis.report_observer_error(error)" in bridge,
        "ATIS observer failure cannot stop live audio",
    )
    require(
        '"atis_decoder": "audio_bridge_read_only_observer"' in traffic,
        "Traffic Voice reports read-only ATIS authority",
    )
    require('VERSION = "0.55.0d"' in traffic, "Traffic Voice version is 0.55.0d")


def validate_decoder() -> None:
    decoded = traffic_voice_atis.decode_samples(synthesize(packet_bits()))
    require(len(decoded) == 1, "synthetic ATIS packet decodes exactly once")
    result = decoded[0]
    require(result["atis_code"] == "9244089629", "ten-digit ATIS identity decodes")
    require(result["callsign"] == "PH9629", "Dutch call sign conversion decodes")
    require(result["mid"] == 244, "Dutch MID decodes")
    require(result["ecc_received"] == result["ecc_calculated"] == 3, "vertical ECC validates")
    require(result["validation"] == "ten_unit_time_diversity_ecc", "validation contract is explicit")

    corrected = traffic_voice_atis.decode_samples(
        synthesize(packet_bits(corrupt_primary=True), seed=7),
    )
    require(len(corrected) == 1, "time diversity recovers one damaged primary symbol")
    require(corrected[0]["callsign"] == "PH9629", "recovered identity remains exact")
    require(corrected[0]["time_diversity_used"] is True, "time-diversity use is reported")

    silence = np.zeros(traffic_voice_atis.SAMPLE_RATE_HZ, dtype=np.float32)
    require(traffic_voice_atis.decode_samples(silence) == [], "silence creates no ATIS result")
    random = np.random.default_rng(10).standard_normal(
        traffic_voice_atis.SAMPLE_RATE_HZ,
    ).astype(np.float32) * 0.08
    require(traffic_voice_atis.decode_samples(random) == [], "wideband noise creates no ATIS result")


def main() -> int:
    validate_source_contract()
    validate_decoder()
    print("VALIDATION PASS: SDRCC v0.55.0d passive Traffic Voice ATIS foundation")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, RuntimeError, ValueError) as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        raise SystemExit(1)
