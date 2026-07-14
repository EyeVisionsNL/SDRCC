#!/usr/bin/env python3

"""Runtime state and safe operator overrides for SDRCC automation."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import RLock
import time
from typing import Any

from core import event_bus


_lock = RLock()

_state: dict[str, Any] = {
    "status": "MANUAL",
    "detail": "Automation Controller wacht op AUTO-modus",
    "next_action": "Geen automatische actie gepland",
    "dry_run": False,
    "manual_override": False,
    "skip_pass_key": None,
    "skip_pass_name": None,
    "target_pass": None,
    "updated_at": None,
}


def _now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _pass_key(pass_data: dict[str, Any] | None) -> str | None:
    if not pass_data:
        return None
    name = str(pass_data.get("name") or "").strip()
    start_epoch = pass_data.get("start_epoch")
    if not name or start_epoch is None:
        return None
    return f"{name}:{int(start_epoch)}"


def _publish(title: str, detail: str, data: dict[str, Any]) -> None:
    event_bus.publish_automation(
        "INFO",
        title,
        detail,
        data=data,
    )


def update_status(
    status: str,
    detail: str,
    *,
    next_action: str | None = None,
    target_pass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = str(status or "IDLE").upper()
    with _lock:
        changed = (
            _state.get("status") != normalized
            or _state.get("detail") != detail
            or (next_action is not None and _state.get("next_action") != next_action)
        )
        _state["status"] = normalized
        _state["detail"] = str(detail)
        if next_action is not None:
            _state["next_action"] = str(next_action)
        _state["target_pass"] = deepcopy(target_pass) if target_pass else None
        if changed:
            _state["updated_at"] = _now_text()
        return deepcopy(_state)


def set_dry_run(enabled: Any) -> dict[str, Any]:
    value = bool(enabled)
    with _lock:
        previous = bool(_state["dry_run"])
        _state["dry_run"] = value
        _state["updated_at"] = _now_text()
        snapshot = deepcopy(_state)
    if previous != value:
        _publish(
            "Dry Run gewijzigd",
            f"Dry Run staat nu {'AAN' if value else 'UIT'}",
            {"dry_run": value},
        )
    return snapshot


def set_manual_override(enabled: Any) -> dict[str, Any]:
    value = bool(enabled)
    with _lock:
        previous = bool(_state["manual_override"])
        _state["manual_override"] = value
        _state["updated_at"] = _now_text()
        snapshot = deepcopy(_state)
    if previous != value:
        _publish(
            "Manual Override gewijzigd",
            f"Manual Override staat nu {'AAN' if value else 'UIT'}",
            {"manual_override": value},
        )
    return snapshot


def skip_pass(pass_data: dict[str, Any] | None) -> dict[str, Any]:
    key = _pass_key(pass_data)
    if key is None:
        raise ValueError("Geen geldige volgende passage beschikbaar")
    with _lock:
        _state["skip_pass_key"] = key
        _state["skip_pass_name"] = str(pass_data.get("name") or "-")
        _state["updated_at"] = _now_text()
        snapshot = deepcopy(_state)
    _publish(
        "Passage overgeslagen",
        f"{_state['skip_pass_name']} wordt éénmalig overgeslagen",
        {
            "pass_key": key,
            "satellite": _state["skip_pass_name"],
            "start_epoch": pass_data.get("start_epoch"),
        },
    )
    return snapshot


def is_pass_skipped(pass_data: dict[str, Any] | None) -> bool:
    key = _pass_key(pass_data)
    with _lock:
        skipped = _state.get("skip_pass_key")
        if skipped and key and skipped != key:
            _state["skip_pass_key"] = None
            _state["skip_pass_name"] = None
            _state["updated_at"] = _now_text()
            return False
        return bool(key and skipped == key)


def clear_skipped_pass() -> None:
    with _lock:
        _state["skip_pass_key"] = None
        _state["skip_pass_name"] = None
        _state["updated_at"] = _now_text()


def get_status(
    *,
    mode: str = "MANUAL",
    next_pass: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _lock:
        snapshot = deepcopy(_state)

    mode_value = str(mode or "MANUAL").upper()
    snapshot["mode"] = mode_value
    snapshot["next_pass"] = deepcopy(next_pass) if next_pass else None

    target_pass = snapshot.get("target_pass")
    if target_pass:
        target_start = target_pass.get("start_epoch")
        if target_start is not None:
            target_pass["seconds_until_start"] = int(target_start) - int(time.time())

        if next_pass and _pass_key(target_pass) == _pass_key(next_pass):
            if "azimuth" in next_pass:
                target_pass["azimuth"] = next_pass.get("azimuth")

        snapshot["target_pass"] = target_pass

    snapshot["pass_skipped"] = is_pass_skipped(next_pass)
    snapshot["manual_controls_available"] = True
    return snapshot
