#!/usr/bin/env python3

"""Manual live FM voice receiver runtime for ISS passes.

v0.29.0c deliberately keeps execution operator-triggered. It does perform the
full safe runtime sequence once started: choose receiver, reserve it, hand over
conflicting services, start rtl_fm + aplay, stop at LOS, restore services and
release the receiver.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from time import sleep
from typing import Any
import json
import os
import shutil
import signal
import subprocess

from core import receiver_manager, service_handover
from core.config import get_receiver_assignments
from core.device_manager import get_device, get_devices, get_weather_device

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
LOG_DIR = PROJECT_ROOT / "logs"
STATE_FILE = STATE_DIR / "voice_receiver.json"
STDERR_FILE = LOG_DIR / "voice_receiver.stderr.log"
_LOCK = RLock()
_WATCHERS: dict[str, Thread] = {}

DEFAULT_STATE: dict[str, Any] = {
    "status": "IDLE",
    "running": False,
    "mission_key": None,
    "receiver_id": None,
    "rtl_fm_pid": None,
    "aplay_pid": None,
    "started_at": None,
    "stopped_at": None,
    "stop_reason": None,
    "error": None,
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return deepcopy(DEFAULT_STATE)
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state = deepcopy(DEFAULT_STATE)
        if isinstance(data, dict):
            state.update(data)
        return state
    except Exception:
        return deepcopy(DEFAULT_STATE)


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_FILE)


def _pid_alive(pid: Any) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, ProcessLookupError, PermissionError):
        return False


def _terminate_pid(pid: Any, timeout: float = 3.0) -> None:
    try:
        numeric = int(pid)
    except (TypeError, ValueError):
        return
    if not _pid_alive(numeric):
        return
    try:
        os.kill(numeric, signal.SIGTERM)
    except ProcessLookupError:
        return
    waited = 0.0
    while waited < timeout and _pid_alive(numeric):
        sleep(0.1)
        waited += 0.1
    if _pid_alive(numeric):
        try:
            os.kill(numeric, signal.SIGKILL)
        except ProcessLookupError:
            pass


def resolve_receiver(preference: str | None = None) -> dict[str, Any]:
    assignments = get_receiver_assignments()
    selected = str(preference or assignments.get("voice") or "auto").strip().lower()
    if selected == "manual":
        raise RuntimeError("ISS Voice assignment staat op MANUAL ONLY")
    if selected in {"sdr1", "sdr2"}:
        device = get_device(selected)
        if device is None:
            raise RuntimeError(f"Geconfigureerde Voice receiver ontbreekt: {selected.upper()}")
        if not receiver_manager.is_available(selected):
            raise RuntimeError(f"{selected.upper()} is already reserved")
        return device

    candidates = get_devices()
    weather = get_weather_device()
    ordered: list[dict[str, Any]] = []
    if weather:
        ordered.append(weather)
    ordered.extend(item for item in candidates if not weather or item["id"] != weather["id"])
    for device in ordered:
        if receiver_manager.is_available(device["id"]):
            return device
    raise RuntimeError("No free receiver is available for ISS Voice")


def build_commands(device: dict[str, Any], mission: dict[str, Any]) -> dict[str, list[str]]:
    frequency = int(mission.get("frequency") or 145_800_000)
    serial = str(device.get("serial") or "").strip()
    if not serial:
        raise RuntimeError("Receiver has no serial number")
    rtl_command = [
        "rtl_fm",
        "-d", serial,
        "-f", str(frequency),
        "-M", "fm",
        "-s", "48000",
        "-r", "48000",
        "-E", "deemp",
        "-F", "9",
    ]
    audio_command = [
        "aplay",
        "-q",
        "-r", "48000",
        "-f", "S16_LE",
        "-c", "1",
    ]
    return {"rtl_fm": rtl_command, "aplay": audio_command}


def _watch_until_los(mission_key: str, los_epoch: int) -> None:
    while int(datetime.now(timezone.utc).timestamp()) < los_epoch:
        with _LOCK:
            state = _load_state()
        if not state.get("running") or state.get("mission_key") != mission_key:
            return
        sleep(1.0)
    try:
        stop(reason="LOS reached", mission_key=mission_key)
    except Exception:
        pass


def start(mission: dict[str, Any]) -> dict[str, Any]:
    if not mission:
        raise RuntimeError("No ISS Voice pass is available")
    mission_key = str(mission.get("mission_key") or "").strip()
    if not mission_key:
        raise RuntimeError("VOICE mission_key ontbreekt")
    with _LOCK:
        current = _load_state()
        if current.get("running"):
            if current.get("mission_key") == mission_key:
                return get_status()
            raise RuntimeError("Er draait al een Voice receiver")

    missing = [name for name in ("rtl_fm", "aplay") if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"Ontbrekend programma: {', '.join(missing)}")

    device = resolve_receiver()
    commands = build_commands(device, mission)
    reservation_created = False
    handover_stopped = False
    rtl_process: subprocess.Popen[bytes] | None = None
    audio_process: subprocess.Popen[bytes] | None = None
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        receiver_manager.reserve(
            device["id"],
            mission_key=mission_key,
            reason="ISS Voice live listening",
            mission_type="VOICE",
            target=str(mission.get("target") or "ISS"),
        )
        reservation_created = True
        service_handover.stop_reserved_handover(mission_key=mission_key)
        handover_stopped = True

        stderr_handle = STDERR_FILE.open("ab", buffering=0)
        rtl_process = subprocess.Popen(
            commands["rtl_fm"],
            stdout=subprocess.PIPE,
            stderr=stderr_handle,
            start_new_session=True,
        )
        if rtl_process.stdout is None:
            raise RuntimeError("rtl_fm audio-output kon niet worden geopend")
        audio_process = subprocess.Popen(
            commands["aplay"],
            stdin=rtl_process.stdout,
            stdout=subprocess.DEVNULL,
            stderr=stderr_handle,
            start_new_session=True,
        )
        rtl_process.stdout.close()
        sleep(0.6)
        if rtl_process.poll() is not None:
            raise RuntimeError("rtl_fm stopte direct; controleer voice_receiver.stderr.log")
        if audio_process.poll() is not None:
            raise RuntimeError("aplay stopte direct; controleer audio-output en voice_receiver.stderr.log")

        receiver_manager.activate(mission_key=mission_key)
        state = deepcopy(DEFAULT_STATE)
        state.update({
            "status": "LISTENING",
            "running": True,
            "mission_key": mission_key,
            "target": mission.get("target") or "ISS",
            "frequency": int(mission.get("frequency") or 145_800_000),
            "frequency_mhz": mission.get("frequency_mhz") or 145.8,
            "receiver_id": device["id"],
            "receiver_number": device.get("number"),
            "receiver_serial": device.get("serial"),
            "rtl_fm_pid": rtl_process.pid,
            "aplay_pid": audio_process.pid,
            "rtl_fm_command": commands["rtl_fm"],
            "audio_command": commands["aplay"],
            "started_at": _now(),
            "los_epoch": int(mission.get("los_epoch") or 0),
            "error": None,
        })
        with _LOCK:
            _save_state(state)

        los_epoch = int(state.get("los_epoch") or 0)
        if los_epoch > int(datetime.now(timezone.utc).timestamp()):
            watcher = Thread(target=_watch_until_los, args=(mission_key, los_epoch), daemon=True)
            _WATCHERS[mission_key] = watcher
            watcher.start()
        return get_status()
    except Exception as exc:
        if audio_process is not None:
            _terminate_pid(audio_process.pid)
        if rtl_process is not None:
            _terminate_pid(rtl_process.pid)
        if reservation_created:
            try:
                if handover_stopped:
                    service_handover.restore_reserved_handover(mission_key=mission_key)
                receiver_manager.release(mission_key=mission_key, detail="Voice start rollback")
            except Exception:
                pass
        state = deepcopy(DEFAULT_STATE)
        state.update({"status": "ERROR", "error": str(exc), "stopped_at": _now()})
        with _LOCK:
            _save_state(state)
        raise


def stop(*, reason: str = "Operator stop", mission_key: str | None = None) -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
    active_key = str(state.get("mission_key") or "").strip()
    if mission_key and active_key and mission_key != active_key:
        raise RuntimeError("Voice receiver hoort bij een andere missie")
    if not active_key:
        return get_status()

    errors: list[str] = []
    _terminate_pid(state.get("aplay_pid"))
    _terminate_pid(state.get("rtl_fm_pid"))
    try:
        service_handover.restore_reserved_handover(mission_key=active_key)
    except Exception as exc:
        errors.append(f"service restore: {exc}")
    try:
        receiver_manager.release(mission_key=active_key, detail=reason)
    except Exception as exc:
        errors.append(f"receiver release: {exc}")

    stopped = deepcopy(state)
    stopped.update({
        "status": "ERROR" if errors else "IDLE",
        "running": False,
        "rtl_fm_pid": None,
        "aplay_pid": None,
        "stopped_at": _now(),
        "stop_reason": reason,
        "error": "; ".join(errors) if errors else None,
    })
    with _LOCK:
        _save_state(stopped)
    if errors:
        raise RuntimeError(stopped["error"])
    return get_status()


def get_status() -> dict[str, Any]:
    with _LOCK:
        state = _load_state()
    rtl_alive = _pid_alive(state.get("rtl_fm_pid"))
    audio_alive = _pid_alive(state.get("aplay_pid"))
    running = bool(state.get("running") and rtl_alive and audio_alive)
    payload = deepcopy(state)
    payload["running"] = running
    payload["rtl_fm_alive"] = rtl_alive
    payload["audio_alive"] = audio_alive
    payload["available_programs"] = {
        "rtl_fm": shutil.which("rtl_fm") is not None,
        "aplay": shutil.which("aplay") is not None,
    }
    if state.get("running") and not running:
        payload["status"] = "PROCESS_LOST"
        payload["error"] = payload.get("error") or "rtl_fm of aplay draait niet meer"
    return {"ok": True, "runtime": payload}
