#!/usr/bin/env python3
"""ISS Voice recording runtime with safe receiver handover and optional monitor."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from time import sleep
from typing import Any
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import wave

from core import receiver_manager, service_handover
from core.config import get_receiver_assignments
from core.device_manager import get_device, get_devices, get_weather_device

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
LOG_DIR = PROJECT_ROOT / "logs"
RECORDINGS_DIR = PROJECT_ROOT / "data" / "voice_recordings"
STATE_FILE = STATE_DIR / "voice_receiver.json"
STDERR_FILE = LOG_DIR / "voice_receiver.stderr.log"
WRITER_SCRIPT = PROJECT_ROOT / "core" / "voice_audio_writer.py"
_LOCK = RLock()
_WATCHERS: dict[str, Thread] = {}

DEFAULT_STATE: dict[str, Any] = {
    "status": "IDLE", "running": False, "mission_key": None,
    "receiver_id": None, "rtl_fm_pid": None, "writer_pid": None,
    "started_at": None, "stopped_at": None, "stop_reason": None,
    "recording_path": None, "live_monitor": False, "error": None,
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
        sleep(0.1); waited += 0.1
    if _pid_alive(numeric):
        try: os.kill(numeric, signal.SIGKILL)
        except ProcessLookupError: pass


def resolve_receiver(preference: str | None = None) -> dict[str, Any]:
    assignments = get_receiver_assignments()
    selected = str(preference or assignments.get("voice") or "auto").strip().lower()
    if selected == "manual":
        raise RuntimeError("ISS Voice assignment is MANUAL ONLY")
    if selected in {"sdr1", "sdr2"}:
        device = get_device(selected)
        if device is None:
            raise RuntimeError(f"Configured Voice receiver is missing: {selected.upper()}")
        if not receiver_manager.is_available(selected):
            raise RuntimeError(f"{selected.upper()} is already reserved")
        return device
    candidates = get_devices(); weather = get_weather_device(); ordered: list[dict[str, Any]] = []
    if weather: ordered.append(weather)
    ordered.extend(item for item in candidates if not weather or item["id"] != weather["id"])
    for device in ordered:
        if receiver_manager.is_available(device["id"]):
            return device
    raise RuntimeError("No free receiver is available for ISS Voice")


def build_rtl_command(device: dict[str, Any], mission: dict[str, Any]) -> list[str]:
    serial = str(device.get("serial") or "").strip()
    if not serial: raise RuntimeError("Receiver has no serial number")
    return ["rtl_fm", "-d", serial, "-f", str(int(mission.get("frequency") or 145_800_000)),
            "-M", "fm", "-s", "48000", "-r", "48000", "-E", "deemp", "-F", "9"]


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-.")
    return cleaned[:120] or "iss-voice"


def _recording_path(mission: dict[str, Any]) -> Path:
    now = datetime.now().astimezone()
    key = _safe_name(str(mission.get("mission_key") or "iss-voice"))
    return RECORDINGS_DIR / now.strftime("%Y") / now.strftime("%m") / f"{now:%Y%m%d-%H%M%S}-{key}.wav"


def _watch_until_stop(mission_key: str, stop_epoch: int) -> None:
    while int(datetime.now(timezone.utc).timestamp()) < stop_epoch:
        with _LOCK: state = _load_state()
        if not state.get("running") or state.get("mission_key") != mission_key: return
        sleep(1.0)
    try: stop(reason="Recording window ended", mission_key=mission_key)
    except Exception: pass


def start(mission: dict[str, Any], *, receiver_preference: str | None = None,
          live_monitor: bool = False, stop_epoch: int | None = None) -> dict[str, Any]:
    if not mission: raise RuntimeError("No ISS Voice pass is available")
    mission_key = str(mission.get("mission_key") or "").strip()
    if not mission_key: raise RuntimeError("VOICE mission_key is missing")
    with _LOCK:
        current = _load_state()
        if current.get("running"):
            if current.get("mission_key") == mission_key: return get_status()
            raise RuntimeError("Another Voice recording is already running")
    missing = [name for name in ("rtl_fm",) if shutil.which(name) is None]
    if live_monitor and shutil.which("aplay") is None: missing.append("aplay")
    if missing: raise RuntimeError(f"Missing program: {', '.join(missing)}")

    device = resolve_receiver(receiver_preference)
    rtl_command = build_rtl_command(device, mission)
    output = _recording_path(mission); output.parent.mkdir(parents=True, exist_ok=True)
    writer_command = [sys.executable, str(WRITER_SCRIPT), "--output", str(output), "--rate", "48000"]
    if live_monitor: writer_command.append("--monitor")
    reservation_created = handover_stopped = False
    rtl_process = writer_process = None
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stderr_handle = STDERR_FILE.open("ab", buffering=0)
    try:
        receiver_manager.reserve(device["id"], mission_key=mission_key,
            reason="ISS Voice recording", mission_type="VOICE", target=str(mission.get("target") or "ISS"))
        reservation_created = True
        service_handover.stop_reserved_handover(mission_key=mission_key); handover_stopped = True
        rtl_process = subprocess.Popen(rtl_command, stdout=subprocess.PIPE, stderr=stderr_handle, start_new_session=True)
        if rtl_process.stdout is None: raise RuntimeError("rtl_fm audio output could not be opened")
        writer_process = subprocess.Popen(writer_command, stdin=rtl_process.stdout,
            stdout=subprocess.DEVNULL, stderr=stderr_handle, start_new_session=True)
        rtl_process.stdout.close(); sleep(0.8)
        if rtl_process.poll() is not None: raise RuntimeError("rtl_fm stopped immediately; check voice_receiver.stderr.log")
        if writer_process.poll() is not None: raise RuntimeError("WAV writer stopped immediately; check voice_receiver.stderr.log")
        receiver_manager.activate(mission_key=mission_key)
        final_stop = int(stop_epoch or mission.get("los_epoch") or 0)
        state = deepcopy(DEFAULT_STATE); state.update({
            "status": "RECORDING", "running": True, "mission_key": mission_key,
            "target": mission.get("target") or "ISS", "frequency": int(mission.get("frequency") or 145_800_000),
            "frequency_mhz": mission.get("frequency_mhz") or 145.8, "receiver_id": device["id"],
            "receiver_number": device.get("number"), "receiver_serial": device.get("serial"),
            "rtl_fm_pid": rtl_process.pid, "writer_pid": writer_process.pid,
            "rtl_fm_command": rtl_command, "writer_command": writer_command,
            "recording_path": str(output), "live_monitor": bool(live_monitor),
            "started_at": _now(), "stop_epoch": final_stop, "error": None,
        })
        with _LOCK: _save_state(state)
        if final_stop > int(datetime.now(timezone.utc).timestamp()):
            watcher = Thread(target=_watch_until_stop, args=(mission_key, final_stop), daemon=True)
            _WATCHERS[mission_key] = watcher; watcher.start()
        return get_status()
    except Exception as exc:
        if rtl_process is not None: _terminate_pid(rtl_process.pid)
        if writer_process is not None: _terminate_pid(writer_process.pid)
        if reservation_created:
            try:
                if handover_stopped: service_handover.restore_reserved_handover(mission_key=mission_key)
                receiver_manager.release(mission_key=mission_key, detail="Voice start rollback")
            except Exception: pass
        state = deepcopy(DEFAULT_STATE); state.update({"status":"ERROR","error":str(exc),"stopped_at":_now()})
        with _LOCK: _save_state(state)
        raise
    finally:
        stderr_handle.close()


def stop(*, reason: str = "Operator stop", mission_key: str | None = None) -> dict[str, Any]:
    with _LOCK: state = _load_state()
    active_key = str(state.get("mission_key") or "").strip()
    if mission_key and active_key and mission_key != active_key: raise RuntimeError("Voice receiver belongs to another mission")
    if not active_key: return get_status()
    errors: list[str] = []
    _terminate_pid(state.get("rtl_fm_pid")); sleep(0.4)
    _terminate_pid(state.get("writer_pid"))
    try: service_handover.restore_reserved_handover(mission_key=active_key)
    except Exception as exc: errors.append(f"service restore: {exc}")
    try: receiver_manager.release(mission_key=active_key, detail=reason)
    except Exception as exc: errors.append(f"receiver release: {exc}")
    stopped = deepcopy(state); stopped.update({
        "status": "ERROR" if errors else "COMPLETE", "running": False,
        "rtl_fm_pid": None, "writer_pid": None, "stopped_at": _now(),
        "stop_reason": reason, "error": "; ".join(errors) if errors else None,
    })
    with _LOCK: _save_state(stopped)
    if errors: raise RuntimeError(stopped["error"])
    return get_status()


def _wav_duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate(); return round(wav.getnframes() / rate, 1) if rate else None
    except Exception: return None


def list_recordings(limit: int = 50) -> list[dict[str, Any]]:
    if not RECORDINGS_DIR.exists(): return []
    rows = []
    for path in sorted(RECORDINGS_DIR.rglob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)[:max(1, min(limit, 200))]:
        stat = path.stat(); relative = path.relative_to(RECORDINGS_DIR).as_posix()
        rows.append({"filename": path.name, "relative_path": relative, "bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
            "duration_seconds": _wav_duration(path), "url": f"/voice-recording/{relative}"})
    return rows


def recording_file(relative_path: str) -> Path:
    requested = (RECORDINGS_DIR / relative_path).resolve(); root = RECORDINGS_DIR.resolve()
    if not str(requested).startswith(str(root)) or not requested.is_file(): raise FileNotFoundError(relative_path)
    return requested


def get_status() -> dict[str, Any]:
    with _LOCK: state = _load_state()
    rtl_alive = _pid_alive(state.get("rtl_fm_pid")); writer_alive = _pid_alive(state.get("writer_pid"))
    running = bool(state.get("running") and rtl_alive and writer_alive)
    payload = deepcopy(state); payload.update({"running":running,"rtl_fm_alive":rtl_alive,"writer_alive":writer_alive,
        "available_programs":{"rtl_fm":shutil.which("rtl_fm") is not None,"aplay":shutil.which("aplay") is not None}})
    if state.get("running") and not running:
        payload["status"] = "PROCESS_LOST"; payload["error"] = payload.get("error") or "rtl_fm or WAV writer is no longer running"
    return {"ok": True, "runtime": payload}
