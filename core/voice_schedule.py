#!/usr/bin/env python3
"""Persistent ISS Voice recording schedule and automatic executor."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from threading import RLock, Thread
from time import sleep
from typing import Any

from core import config as config_core
from core import mission_queue
from core import weather_planning

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = PROJECT_ROOT / "data" / "state" / "voice_schedule.json"
_LOCK = RLock()
_EXECUTOR: Thread | None = None


def _load() -> dict[str, dict[str, Any]]:
    with _LOCK:
        if not STATE_FILE.exists(): return {}
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception: return {}


def _save(items: dict[str, dict[str, Any]]) -> None:
    with _LOCK:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATE_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(STATE_FILE)


def _voice_passes(hours_ahead: int = 48) -> list[dict[str, Any]]:
    minimum = float(weather_planning.get_config().get("minimum_elevation", 40.0))
    queue = mission_queue.get_payload(limit=100, hours_ahead=hours_ahead).get("queue", [])
    return [item for item in queue if str(item.get("mission_type") or "").upper() == "VOICE"
            and not item.get("skipped") and float(item.get("max_elevation") or 0.0) >= minimum]


def _find_pass(queue_key: str, hours_ahead: int = 168) -> dict[str, Any]:
    for item in _voice_passes(hours_ahead):
        if str(item.get("queue_key") or "") == queue_key: return item
    raise ValueError("The selected ISS pass no longer exists or is below the minimum elevation.")


def _parse_local(value: str) -> datetime:
    try: return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc: raise ValueError("Invalid start or stop time.") from exc


def set_item(payload: dict[str, Any]) -> dict[str, Any]:
    queue_key = str(payload.get("queue_key") or "").strip()
    if not queue_key: raise ValueError("queue_key is required.")
    item = _find_pass(queue_key)
    use_custom_window = bool(payload.get("use_custom_window", False))
    start_value = str(payload.get("start") or item.get("start") or "")
    stop_value = str(payload.get("stop") or item.get("end") or "")
    start_dt, stop_dt = _parse_local(start_value), _parse_local(stop_value)
    if stop_dt <= start_dt: raise ValueError("The stop time must be after the start time.")
    pass_start, pass_end = _parse_local(str(item.get("start"))), _parse_local(str(item.get("end")))
    if stop_dt < pass_start or start_dt > pass_end: raise ValueError("The recording window must overlap the ISS pass.")
    receiver = str(payload.get("receiver") or "auto").lower()
    if receiver not in {"auto", "sdr1", "sdr2"}: raise ValueError("Invalid receiver selection.")
    planned = {
        "queue_key": queue_key, "target": item.get("name") or "ISS (ZARYA)",
        "frequency": item.get("frequency") or 145_800_000, "frequency_mhz": item.get("frequency_mhz") or 145.8,
        "max_elevation": item.get("max_elevation"), "pass_start": item.get("start"), "pass_end": item.get("end"),
        "start": start_value, "stop": stop_value, "use_custom_window": use_custom_window,
        "receiver": receiver, "record_audio": True, "live_monitor": bool(payload.get("live_monitor", False)),
        "status": "SCHEDULED", "error": None, "recording_path": None,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    items = _load(); items[queue_key] = planned; _save(items); return planned


def remove_item(queue_key: str) -> None:
    items = _load(); item = items.get(str(queue_key or ""))
    if item and str(item.get("status") or "").upper() == "RECORDING":
        raise ValueError("An active Voice recording cannot be removed.")
    items.pop(str(queue_key or ""), None); _save(items)


def _mission_from_schedule(item: dict[str, Any]) -> dict[str, Any]:
    stop_dt = _parse_local(str(item["stop"])).astimezone()
    return {"mission_key": item["queue_key"], "target": item.get("target") or "ISS",
            "frequency": int(item.get("frequency") or 145_800_000),
            "frequency_mhz": item.get("frequency_mhz") or 145.8,
            "los_epoch": int(stop_dt.timestamp())}


def _executor_tick() -> None:
    from core import voice_receiver
    items = _load(); changed = False; now = datetime.now()
    runtime = voice_receiver.get_status().get("runtime") or {}
    for key, item in items.items():
        status = str(item.get("status") or "SCHEDULED").upper()
        start_dt, stop_dt = _parse_local(str(item["start"])), _parse_local(str(item["stop"]))
        if status == "SCHEDULED" and start_dt <= now < stop_dt:
            try:
                result = voice_receiver.start(_mission_from_schedule(item), receiver_preference=item.get("receiver"),
                    live_monitor=bool(item.get("live_monitor")), stop_epoch=int(stop_dt.astimezone().timestamp()))
                active = result.get("runtime") or {}
                item.update({"status":"RECORDING","started_at":active.get("started_at"),
                    "recording_path":active.get("recording_path"),"error":None})
            except Exception as exc:
                item.update({"status":"FAILED","error":str(exc),"ended_at":datetime.now().astimezone().isoformat(timespec="seconds")})
            changed = True
        elif status == "SCHEDULED" and now >= stop_dt:
            item.update({"status":"MISSED","error":"Recording window passed before execution.",
                "ended_at":datetime.now().astimezone().isoformat(timespec="seconds")}); changed = True
        elif status == "RECORDING":
            same = str(runtime.get("mission_key") or "") == key
            if not same or not runtime.get("running"):
                path = Path(str(item.get("recording_path") or ""))
                ok = path.is_file() and path.stat().st_size > 44
                item.update({"status":"COMPLETE" if ok else "FAILED",
                    "ended_at":datetime.now().astimezone().isoformat(timespec="seconds"),
                    "error":None if ok else (runtime.get("error") or "No usable WAV recording was created.")})
                changed = True
        item["updated_at"] = item.get("updated_at") or datetime.now().astimezone().isoformat(timespec="seconds")
    if changed: _save(items)


def _executor_loop() -> None:
    while True:
        try: _executor_tick()
        except Exception: pass
        sleep(2.0)


def start_executor() -> None:
    global _EXECUTOR
    if _EXECUTOR and _EXECUTOR.is_alive(): return
    _EXECUTOR = Thread(target=_executor_loop, name="voice-schedule-executor", daemon=True)
    _EXECUTOR.start()


def get_payload(hours_ahead: int = 48) -> dict[str, Any]:
    minimum = float(weather_planning.get_config().get("minimum_elevation", 40.0))
    passes = _voice_passes(hours_ahead); schedules = _load()
    valid_keys = {str(item.get("queue_key") or "") for item in passes}
    visible = {key: value for key, value in schedules.items() if key in valid_keys or str(value.get("status")) in {"RECORDING","COMPLETE","FAILED","MISSED"}}
    assignments = config_core.get_receiver_assignments(); default_receiver = str(assignments.get("voice") or "auto").lower()
    if default_receiver not in {"auto","sdr1","sdr2"}: default_receiver = "auto"
    return {"ok":True,"minimum_elevation":minimum,"default_receiver":default_receiver,"passes":passes,
            "schedules":visible,"recording_execution_enabled":True,
            "message":"Voice recordings are scheduled and executed automatically during the selected window."}
