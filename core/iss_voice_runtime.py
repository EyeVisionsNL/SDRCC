#!/usr/bin/env python3
"""Read-only ISS Voice runtime visibility state.

This module owns no receiver, scheduler, capture, or service-control authority.
The ISS Voice executor publishes bounded observation updates here so existing UI
providers can report what the executor is doing while a mission is active.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import fcntl
import json
import os
import threading

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
STATE_FILE = STATE_DIR / "iss_voice_runtime.json"
LOCK_FILE = STATE_DIR / "iss_voice_runtime.lock"

_lock = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _empty() -> dict[str, Any]:
    return {
        "ok": True,
        "version": "0.48.0d",
        "active": False,
        "phase": "IDLE",
        "updated_at": _now(),
    }


def _read_unlocked() -> dict[str, Any]:
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return _empty()
    return payload if isinstance(payload, dict) else _empty()


def _write_unlocked(payload: dict[str, Any]) -> dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    normalized = dict(payload)
    normalized["ok"] = True
    normalized["version"] = "0.48.0d"
    normalized["updated_at"] = _now()
    temporary = STATE_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, STATE_FILE)
    return normalized


def _with_file_lock(callback):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return callback()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def get_status() -> dict[str, Any]:
    """Return the latest executor observation without changing runtime state."""
    with _lock:
        return _with_file_lock(lambda: dict(_read_unlocked()))


def begin(**fields: Any) -> dict[str, Any]:
    """Publish the start of one ISS Voice executor lifecycle."""
    started_at = fields.pop("started_at", None) or _now()
    payload = _empty()
    payload.update(fields)
    payload.update({"active": True, "phase": fields.get("phase") or "PREPARING", "started_at": started_at})
    with _lock:
        return _with_file_lock(lambda: _write_unlocked(payload))


def update(*, phase: str | None = None, **fields: Any) -> dict[str, Any]:
    """Update observation fields while preserving the active lifecycle."""
    def operation() -> dict[str, Any]:
        payload = _read_unlocked()
        payload.update(fields)
        if phase:
            payload["phase"] = str(phase).upper()
        return _write_unlocked(payload)

    with _lock:
        return _with_file_lock(operation)


def finish(*, success: bool, detail: str | None = None, **fields: Any) -> dict[str, Any]:
    """Close the visible lifecycle while retaining the last result for diagnostics."""
    def operation() -> dict[str, Any]:
        payload = _read_unlocked()
        payload.update(fields)
        payload.update({
            "active": False,
            "phase": "FINISHED" if success else "FAILED",
            "success": bool(success),
            "detail": detail or payload.get("detail"),
            "ended_at": _now(),
        })
        return _write_unlocked(payload)

    with _lock:
        return _with_file_lock(operation)
