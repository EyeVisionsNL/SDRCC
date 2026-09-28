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
CHANNEL_FILE = ROOT / "data/state/update_channel.json"
REMOTE_VERSION_TEMPLATE = "https://raw.githubusercontent.com/EyeVisionsNL/SDRCC/{channel}/VERSION"
UPDATE_UNIT = "sdrcc-update.service"
_ALLOWED_CHANNELS = {"main", "develop"}
_ACTIVE_WORKER_STATES = {
    "queued", "starting", "downloading", "validating",
    "backing_up", "installing", "restarting",
}
_VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<suffix>[A-Za-z]*)(?:-r(?P<revision>\d+))?$"
)
_LOCK = RLock()
_CHECK = {
    "latest_version": None,
    "last_checked_at": None,
    "check_error": None,
    "channel": None,
}


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


def _read_channel_state() -> dict:
    state = {"selected": "main", "installed": "main"}
    try:
        payload = json.loads(CHANNEL_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return state
    if not isinstance(payload, dict):
        return state
    selected = str(payload.get("selected") or "main").strip().lower()
    installed = str(payload.get("installed") or "main").strip().lower()
    state["selected"] = selected if selected in _ALLOWED_CHANNELS else "main"
    state["installed"] = installed if installed in _ALLOWED_CHANNELS else "main"
    return state


def _write_channel_state(state: dict) -> None:
    CHANNEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = CHANNEL_FILE.with_name(CHANNEL_FILE.name + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CHANNEL_FILE)


def set_beta_program(enabled: bool) -> dict:
    state = _read_channel_state()
    state["selected"] = "develop" if bool(enabled) else "main"
    _write_channel_state(state)
    with _LOCK:
        _CHECK.update({
            "latest_version": None,
            "last_checked_at": None,
            "check_error": None,
            "channel": None,
        })
    return check_remote_version()


def update_channel() -> str:
    return _read_channel_state()["selected"]


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
    channel = update_channel()
    latest = None
    error = None
    try:
        request = Request(
            REMOTE_VERSION_TEMPLATE.format(channel=channel),
            headers={"User-Agent": "SDRCC-update-check"},
        )
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
            "channel": channel,
        })
    return get_status()


def audio_setup_required() -> bool:
    try:
        from core.traffic_voice_denoise import capabilities
        engines = capabilities()
        return any(not engines.get(name, {}).get("available") for name in ("speex", "rnnoise"))
    except (ImportError, OSError, RuntimeError):
        return True


def get_status() -> dict:
    local = installed_version()
    state = _read_channel_state()
    selected_channel = state["selected"]
    installed_channel = state["installed"]
    with _LOCK:
        check = dict(_CHECK)

    if check.get("channel") != selected_channel:
        latest = None
        check_error = None
        last_checked_at = None
    else:
        latest = check.get("latest_version")
        check_error = check.get("check_error")
        last_checked_at = check.get("last_checked_at")

    comparison = compare_versions(local, latest) if latest else None
    channel_change_pending = selected_channel != installed_channel
    worker = _read_worker_status()
    setup_required = audio_setup_required()
    update_available = comparison == -1 or (
        comparison == 0 and channel_change_pending
    )
    return {
        "ok": check_error is None,
        "installed_version": local,
        "latest_version": latest,
        "update_available": update_available,
        "local_ahead": comparison == 1,
        "same_version": comparison == 0,
        "last_checked_at": last_checked_at,
        "check_error": check_error,
        "worker": worker,
        "audio_setup_required": setup_required,
        "can_complete_audio_setup": (
            comparison == 0 and not channel_change_pending and setup_required
        ),
        "source_channel": selected_channel,
        "installed_channel": installed_channel,
        "beta_program": selected_channel == "develop",
        "channel_change_pending": channel_change_pending,
    }
