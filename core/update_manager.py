#!/usr/bin/env python3
"""Read-only SDRCC update discovery and worker-status reporting."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from threading import RLock
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
STATUS_FILE = Path("/var/lib/sdrcc/update-status.json")
REMOTE_VERSION_URL = "https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/main/VERSION"
UPDATE_UNIT = "sdrcc-update.service"
_ACTIVE_WORKER_STATES = {
    "queued", "starting", "downloading", "validating",
    "backing_up", "installing", "restarting",
}
_VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<suffix>[A-Za-z]*)(?:-r(?P<revision>\d+))?$"
)
_LOCK = RLock()
_CHECK = {"latest_version": None, "last_checked_at": None, "check_error": None}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def version_key(value: str):
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("suffix").lower(),
        int(match.group("revision") or 0),
    )


def compare_versions(local: str, remote: str):
    left = version_key(local)
    right = version_key(remote)
    if left is None or right is None:
        return None
    return -1 if left < right else (1 if left > right else 0)


def installed_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def _update_unit_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", UPDATE_UNIT],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _read_worker_status() -> dict:
    try:
        payload = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError):
        return {"state": "unknown", "message": "Update status file is unreadable."}
    if not isinstance(payload, dict):
        return {}
    if payload.get("state") in _ACTIVE_WORKER_STATES and not _update_unit_active():
        interrupted = dict(payload)
        interrupted["state"] = "interrupted"
        interrupted["message"] = (
            "A previous SDRCC update was interrupted. It is safe to check and retry."
        )
        return interrupted
    return payload


def check_remote_version(timeout: float = 5.0) -> dict:
    checked_at = _now()
    latest = None
    error = None
    try:
        request = Request(REMOTE_VERSION_URL, headers={"User-Agent": "SDRCC-update-check"})
        with urlopen(request, timeout=timeout) as response:
            latest = response.read(256).decode("utf-8").strip()
        if version_key(latest) is None:
            raise ValueError(f"Unexpected remote VERSION value: {latest!r}")
    except Exception as exc:
        error = str(exc)
        latest = None

    with _LOCK:
        _CHECK.update({
            "latest_version": latest,
            "last_checked_at": checked_at,
            "check_error": error,
        })
    return get_status()


def get_status() -> dict:
    local = installed_version()
    with _LOCK:
        check = dict(_CHECK)
    latest = check.get("latest_version")
    comparison = compare_versions(local, latest) if latest else None
    return {
        "ok": check.get("check_error") is None,
        "installed_version": local,
        "latest_version": latest,
        "update_available": comparison == -1,
        "local_ahead": comparison == 1,
        "same_version": comparison == 0,
        "last_checked_at": check.get("last_checked_at"),
        "check_error": check.get("check_error"),
        "worker": _read_worker_status(),
    }
