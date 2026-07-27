"""Safe startup recovery for stale ISS Voice observer state.

This module owns no mission, receiver, process, or service authority.  It only
repairs the persisted ISS Voice observer snapshot when all existing authorities
agree that no ISS Voice execution is active.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "state" / "iss_voice_runtime.json"
VERSION = "0.51.0b"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _process_command_lines() -> Iterable[str]:
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []

    commands: list[str] = []
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        command = raw.replace(b"\0", b" ").decode("utf-8", errors="ignore").strip()
        if command:
            commands.append(command)
    return commands


def _matching_recorder_process(state: dict[str, Any]) -> str | None:
    mission_id = str(state.get("mission_id") or "").strip()
    iq_path = str(state.get("iq_path") or "").strip()
    output_directory = str(state.get("output_directory") or "").strip()

    identifiers = [value for value in (mission_id, iq_path, output_directory) if value]
    recorder_tokens = ("rtl_sdr", "rtl_fm", "ffmpeg", "sox", "wideband_iq", "iss_voice")

    for command in _process_command_lines():
        lowered = command.lower()
        if not any(token in lowered for token in recorder_tokens):
            continue
        if identifiers and not any(identifier in command for identifier in identifiers):
            continue
        return command
    return None


def _has_iss_reservation(receiver_status: dict[str, Any], state: dict[str, Any]) -> bool:
    mission_id = str(state.get("mission_id") or "").strip()
    receiver_ids = {
        str(state.get("receiver_id") or "").strip(),
        str(state.get("receiver_serial") or "").strip(),
    }

    reservations = receiver_status.get("canonical_reservations")
    if not isinstance(reservations, dict):
        reservations = receiver_status.get("reservations")
    if not isinstance(reservations, dict):
        return False

    for reservation in reservations.values():
        if not isinstance(reservation, dict):
            continue
        if str(reservation.get("status") or "").upper() not in {"ACTIVE", "RESERVED"}:
            continue
        if mission_id and str(reservation.get("mission_id") or "") == mission_id:
            return True
        values = {
            str(reservation.get("receiver_id") or "").strip(),
            str(reservation.get("runtime_id") or "").strip(),
            str(reservation.get("registry_id") or "").strip(),
            str((reservation.get("device") or {}).get("serial") or "").strip(),
        }
        if any(value and value in receiver_ids for value in values):
            return True
    return False


def recover_if_stale(
    *,
    mission_status: dict[str, Any],
    receiver_status: dict[str, Any],
    iss_execution_active: bool,
    path: Path = STATE_PATH,
) -> dict[str, Any]:
    """Reset an impossible persisted RECORDING state without taking authority."""
    state = _read_state(path)
    if not state or not bool(state.get("active")):
        return {"ok": True, "changed": False, "reason": "observer already idle"}

    phase = str(mission_status.get("phase") or mission_status.get("state") or "").upper()
    mission_idle = mission_status.get("active_job") is None and phase in {
        "READY",
        "WAIT FOR PASS",
    }
    has_reservation = _has_iss_reservation(receiver_status, state)
    process_command = _matching_recorder_process(state)

    if not mission_idle:
        return {"ok": True, "changed": False, "reason": "mission authority active"}
    if iss_execution_active:
        return {"ok": True, "changed": False, "reason": "ISS executor active"}
    if has_reservation:
        return {"ok": True, "changed": False, "reason": "receiver reservation active"}
    if process_command:
        return {
            "ok": True,
            "changed": False,
            "reason": "recorder process active",
            "process": process_command,
        }

    recovered_at = _now_iso()
    repaired = dict(state)
    repaired.update({
        "ok": True,
        "version": VERSION,
        "active": False,
        "phase": "READY",
        "detail": "Stale ISS Voice observer state recovered during startup",
        "updated_at": recovered_at,
        "ended_at": repaired.get("ended_at") or recovered_at,
        "recovered": True,
        "recovered_at": recovered_at,
        "recovery_reason": "No active mission, reservation, executor, or recorder process",
    })
    _atomic_write(path, repaired)
    return {
        "ok": True,
        "changed": True,
        "reason": repaired["recovery_reason"],
        "mission_id": repaired.get("mission_id"),
        "path": str(path),
    }
