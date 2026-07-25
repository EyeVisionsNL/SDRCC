#!/usr/bin/env python3
"""Bounded wideband RTL-SDR IQ recorder for future ISS Voice missions.

This backend owns no scheduling or service-control authority. A caller must
resolve the assigned receiver, stop conflicting services, reserve the receiver,
and provide a bounded duration before execute_capture() may be used.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import shutil
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_ROOT = PROJECT_ROOT / "data" / "recordings" / "iss_voice"
MAX_CAPTURE_SECONDS = 1200

@dataclass(frozen=True)
class CaptureSpec:
    mission_id: str
    receiver_serial: str
    frequency_hz: int
    sample_rate_hz: int
    duration_seconds: int
    output_directory: Path
    gain_db: float | None = None
    ppm: int = 0

    @property
    def sample_count(self) -> int:
        return self.sample_rate_hz * self.duration_seconds

    @property
    def iq_path(self) -> Path:
        return self.output_directory / "recording.iq"

    @property
    def metadata_path(self) -> Path:
        return self.output_directory / "capture.json"


def _safe_mission_id(value: str) -> str:
    text = str(value or "").strip()
    if not text or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in text):
        raise ValueError("Ongeldige mission_id")
    return text


def build_spec(*, mission_id: str, receiver_serial: str, frequency_hz: int,
               sample_rate_hz: int, duration_seconds: int,
               gain_db: float | None = None, ppm: int = 0,
               output_directory: str | Path | None = None) -> CaptureSpec:
    mission = _safe_mission_id(mission_id)
    serial = str(receiver_serial or "").strip()
    if not serial:
        raise ValueError("receiver_serial ontbreekt")
    frequency = int(frequency_hz)
    sample_rate = int(sample_rate_hz)
    duration = int(duration_seconds)
    if frequency <= 0:
        raise ValueError("frequency_hz moet positief zijn")
    if sample_rate < 100000 or sample_rate > 3200000:
        raise ValueError("sample_rate_hz buiten veilige RTL-SDR grenzen")
    if duration < 1 or duration > MAX_CAPTURE_SECONDS:
        raise ValueError(f"duration_seconds moet 1..{MAX_CAPTURE_SECONDS} zijn")
    directory = Path(output_directory).expanduser() if output_directory else RECORDINGS_ROOT / mission
    directory = directory.resolve()
    root = (PROJECT_ROOT / "data" / "recordings").resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise ValueError("output_directory moet binnen data/recordings liggen") from exc
    return CaptureSpec(mission, serial, frequency, sample_rate, duration, directory, gain_db, int(ppm))


def build_command(spec: CaptureSpec) -> list[str]:
    command = [
        "rtl_sdr", "-d", spec.receiver_serial,
        "-f", str(spec.frequency_hz),
        "-s", str(spec.sample_rate_hz),
        "-p", str(spec.ppm),
        "-n", str(spec.sample_count),
    ]
    if spec.gain_db is not None:
        command.extend(["-g", str(float(spec.gain_db))])
    command.append(str(spec.iq_path))
    return command


def describe_capture(spec: CaptureSpec) -> dict[str, Any]:
    expected_bytes = spec.sample_count * 2  # rtl_sdr CU8: unsigned I + Q bytes
    return {
        "version": "0.46.0b",
        "mission_id": spec.mission_id,
        "receiver_serial": spec.receiver_serial,
        "center_frequency_hz": spec.frequency_hz,
        "sample_rate_hz": spec.sample_rate_hz,
        "duration_seconds": spec.duration_seconds,
        "sample_count": spec.sample_count,
        "sample_format": "cu8",
        "expected_bytes": expected_bytes,
        "gain_db": spec.gain_db,
        "ppm": spec.ppm,
        "output_directory": str(spec.output_directory),
        "iq_path": str(spec.iq_path),
        "metadata_path": str(spec.metadata_path),
        "command": build_command(spec),
        "mission_integration_enabled": False,
        "doppler_processing_enabled": False,
        "audio_demodulation_enabled": False,
    }


def validate_runtime() -> dict[str, Any]:
    executable = shutil.which("rtl_sdr")
    return {
        "ok": executable is not None,
        "version": "0.46.0b",
        "backend": "rtl_sdr",
        "executable": executable,
        "bounded": True,
        "mission_integration_enabled": False,
    }


def execute_capture(spec: CaptureSpec, *, services_confirmed_stopped: bool,
                    timeout_margin_seconds: int = 30) -> dict[str, Any]:
    if not services_confirmed_stopped:
        raise RuntimeError("Conflicterende services zijn niet bevestigd als gestopt")
    runtime = validate_runtime()
    if not runtime["ok"]:
        raise RuntimeError("rtl_sdr ontbreekt")
    spec.output_directory.mkdir(parents=True, exist_ok=False)
    started_at = datetime.now().astimezone()
    metadata = describe_capture(spec)
    metadata["started_at"] = started_at.isoformat(timespec="seconds")
    spec.metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result = subprocess.run(build_command(spec), capture_output=True, text=True,
                            timeout=spec.duration_seconds + int(timeout_margin_seconds), check=False)
    ended_at = datetime.now().astimezone()
    actual_bytes = spec.iq_path.stat().st_size if spec.iq_path.exists() else 0
    metadata.update({
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "elapsed_seconds": round((ended_at - started_at).total_seconds(), 3),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "actual_bytes": actual_bytes,
        "complete": result.returncode == 0 and actual_bytes == metadata["expected_bytes"],
    })
    spec.metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return metadata
