#!/usr/bin/env python3
"""Bounded and verified RTL-SDR IQ recorder for ISS Voice missions.

This backend owns no scheduling or service-control authority. The caller must
resolve the receiver, stop conflicting services and reserve the receiver.
A capture is only reported as started after rtl_sdr stays alive and the IQ file
has begun to grow.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import json
import os
import shutil
import subprocess
import time

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_ROOT = PROJECT_ROOT / "data" / "recordings" / "iss_voice"
MAX_CAPTURE_SECONDS = 1200
DEFAULT_STARTUP_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRY_COUNT = 2
DEFAULT_RETRY_DELAY_SECONDS = 2.0

CaptureStarted = Callable[[dict[str, Any]], None]


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

    @property
    def stdout_path(self) -> Path:
        return self.output_directory / "rtl_sdr.stdout.log"

    @property
    def stderr_path(self) -> Path:
        return self.output_directory / "rtl_sdr.stderr.log"


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
    expected_bytes = spec.sample_count * 2
    return {
        "version": "0.53.1d-r2",
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
        "stdout_path": str(spec.stdout_path),
        "stderr_path": str(spec.stderr_path),
        "command": build_command(spec),
        "mission_integration_enabled": True,
        "controlled_capture_enabled": True,
        "verified_start_required": True,
        "doppler_processing_enabled": False,
        "audio_demodulation_enabled": True,
    }


def validate_runtime() -> dict[str, Any]:
    executable = shutil.which("rtl_sdr")
    return {
        "ok": executable is not None,
        "version": "0.53.1d-r2",
        "backend": "rtl_sdr",
        "executable": executable,
        "bounded": True,
        "mission_integration_enabled": True,
        "controlled_capture_enabled": True,
        "verified_start_required": True,
    }


def _write_metadata(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _wait_for_verified_start(
    process: subprocess.Popen[Any],
    iq_path: Path,
    *,
    timeout_seconds: float,
) -> tuple[bool, int]:
    deadline = time.monotonic() + max(0.5, float(timeout_seconds))
    largest_size = 0
    while time.monotonic() < deadline:
        returncode = process.poll()
        try:
            largest_size = max(largest_size, iq_path.stat().st_size)
        except OSError:
            pass
        # File growth is sufficient proof that rtl_sdr entered capture, even
        # when a very short capture completes before the next process poll.
        # Checking the bytes first avoids classifying a complete fast capture
        # as "never started" merely because poll() already returns 0.
        if largest_size > 0:
            return True, largest_size
        if returncode is not None:
            return False, largest_size
        time.sleep(0.1)
    return process.poll() is None and largest_size > 0, largest_size


def execute_capture(
    spec: CaptureSpec,
    *,
    services_confirmed_stopped: bool,
    timeout_margin_seconds: int = 30,
    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    retry_count: int = DEFAULT_RETRY_COUNT,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
    on_started: CaptureStarted | None = None,
) -> dict[str, Any]:
    if not services_confirmed_stopped:
        raise RuntimeError("Conflicterende services zijn niet bevestigd als gestopt")
    runtime = validate_runtime()
    if not runtime["ok"]:
        raise RuntimeError("rtl_sdr ontbreekt")

    spec.output_directory.mkdir(parents=True, exist_ok=False)
    metadata = describe_capture(spec)
    metadata.update({
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "retry_count": max(0, int(retry_count)),
        "attempts": [],
        "capture_started": False,
        "complete": False,
    })
    _write_metadata(spec.metadata_path, metadata)

    max_attempts = 1 + max(0, int(retry_count))
    final_returncode: int | None = None
    timed_out = False

    for attempt_number in range(1, max_attempts + 1):
        for path in (spec.iq_path, spec.stdout_path, spec.stderr_path):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

        attempt_started = datetime.now().astimezone()
        attempt: dict[str, Any] = {
            "attempt": attempt_number,
            "started_at": attempt_started.isoformat(timespec="seconds"),
            "command": build_command(spec),
            "verified_started": False,
        }
        metadata["attempts"].append(attempt)
        _write_metadata(spec.metadata_path, metadata)

        with spec.stdout_path.open("wb") as stdout_handle, spec.stderr_path.open("wb") as stderr_handle:
            process = subprocess.Popen(
                build_command(spec),
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            attempt["pid"] = process.pid
            verified, startup_bytes = _wait_for_verified_start(
                process,
                spec.iq_path,
                timeout_seconds=startup_timeout_seconds,
            )
            attempt["startup_bytes"] = startup_bytes
            attempt["verified_started"] = verified
            attempt["startup_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

            if not verified:
                final_returncode = process.poll()
                if final_returncode is None:
                    _terminate_process(process)
                    final_returncode = process.returncode
                attempt["returncode"] = final_returncode
                attempt["stderr"] = _read_text(spec.stderr_path)
                attempt["stdout"] = _read_text(spec.stdout_path)
                attempt["actual_bytes"] = spec.iq_path.stat().st_size if spec.iq_path.exists() else 0
                attempt["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                _write_metadata(spec.metadata_path, metadata)
                if attempt_number < max_attempts:
                    time.sleep(max(0.0, float(retry_delay_seconds)))
                    continue
                break

            metadata.update({
                "capture_started": True,
                "capture_pid": process.pid,
                "capture_started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "startup_bytes": startup_bytes,
                "active_attempt": attempt_number,
            })
            _write_metadata(spec.metadata_path, metadata)
            if on_started is not None:
                on_started(dict(metadata))

            try:
                final_returncode = process.wait(
                    timeout=spec.duration_seconds + int(timeout_margin_seconds),
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                _terminate_process(process)
                final_returncode = process.returncode

            attempt["returncode"] = final_returncode
            attempt["stderr"] = _read_text(spec.stderr_path)
            attempt["stdout"] = _read_text(spec.stdout_path)
            attempt["actual_bytes"] = spec.iq_path.stat().st_size if spec.iq_path.exists() else 0
            attempt["ended_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            break

    ended_at = datetime.now().astimezone()
    actual_bytes = spec.iq_path.stat().st_size if spec.iq_path.exists() else 0
    expected_bytes = int(metadata["expected_bytes"])
    last_attempt = metadata["attempts"][-1] if metadata["attempts"] else {}
    metadata.update({
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "elapsed_seconds": round(
            (ended_at - datetime.fromisoformat(metadata["started_at"])).total_seconds(),
            3,
        ),
        "returncode": final_returncode,
        "stdout": last_attempt.get("stdout", ""),
        "stderr": last_attempt.get("stderr", ""),
        "actual_bytes": actual_bytes,
        "timed_out": timed_out,
        "attempt_count": len(metadata["attempts"]),
        "complete": (
            bool(metadata.get("capture_started"))
            and final_returncode == 0
            and actual_bytes == expected_bytes
        ),
    })
    _write_metadata(spec.metadata_path, metadata)
    return metadata
