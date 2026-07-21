#!/usr/bin/env python3
"""Deterministic hardware-free mission scenarios for SDRCC.

The simulator deliberately reuses the production Mission Engine, Receiver
Manager and Live RF components. It never opens an SDR, stops a service or
starts SatDump.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any
import time
import uuid

from core import event_bus
from core import live_rf
from core import mission_engine
from core import receiver_manager
from core.device_manager import get_device

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_ROOT = PROJECT_ROOT / "data" / "simulations"

SCENARIOS = {
    "success",
    "no_sync",
    "satdump_returncode_1",
    "receiver_lock_fail",
    "cancel",
}

_RUNTIME: dict[str, Any] = {
    "active": False,
    "scenario": None,
    "receiver_id": None,
    "mission_key": None,
    "mission_id": None,
    "started_at": None,
    "duration_seconds": None,
    "stop_event": None,
    "thread": None,
    "last_result": None,
    "last_error": None,
}
_LOCK = RLock()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _snapshot() -> dict[str, Any]:
    with _LOCK:
        return {
            key: value
            for key, value in _RUNTIME.items()
            if key not in {"stop_event", "thread"}
        }


def get_status() -> dict[str, Any]:
    return {
        "ok": True,
        "simulator": _snapshot(),
        "mission": mission_engine.get_mission_status(),
        "receiver_manager": receiver_manager.get_status(),
        "scenarios": sorted(SCENARIOS),
    }


def _finish_mission(*, success: bool, result: str, detail: str, metrics=None, error=None):
    live_payload = {
        "result": result,
        "detail": detail,
        **(metrics or {}),
    }
    if success:
        live_rf.finish(live_payload)
    else:
        try:
            live_rf.fail(detail)
        except Exception:
            live_rf.finish(live_payload)

    completed = mission_engine.mission_finish_job(
        success=success,
        result=result,
        detail=detail,
        error=error,
        metrics=metrics or {},
    )
    mission_engine.mission_set_state("READY")
    return completed


def _cancel_mission(detail: str):
    try:
        live_rf.finish({"result": "CANCELLED", "detail": detail})
    finally:
        mission_engine.mission_cancel(detail=detail)


def _release(mission_key: str, detail: str):
    status = receiver_manager.get_status()
    reservations = status.get("reservations") or {}
    if any(item.get("mission_key") == mission_key for item in reservations.values()):
        receiver_manager.release(mission_key=mission_key, detail=detail)


def _worker(stop_event: Event, *, scenario: str, duration_seconds: int, mission_key: str):
    result = None
    error_text = None
    try:
        started = time.monotonic()
        peak_snr = 1.0 if scenario == "no_sync" else 4.0

        while True:
            if stop_event.wait(1):
                _cancel_mission("Simulatiemissie gestopt door operator")
                result = "CANCELLED"
                return

            elapsed = int(time.monotonic() - started)
            if scenario == "no_sync":
                peak_snr = min(1.8, peak_snr + 0.05)
                live_rf.update_line(
                    f"SNR : {peak_snr:.2f} dB, Peak SNR : {peak_snr:.2f} dB"
                )
            else:
                peak_snr = min(13.5, peak_snr + 0.55)
                live_rf.update_line(
                    f"SNR : {peak_snr:.2f} dB, Peak SNR : {peak_snr:.2f} dB"
                )
                if elapsed >= 3:
                    live_rf.update_line("Viterbi : SYNCED BER : 0.012, Deframer : SYNCED")

            if scenario == "cancel" and elapsed >= max(2, duration_seconds // 2):
                _cancel_mission("Automatisch cancel-scenario voltooid")
                result = "CANCELLED"
                return

            if elapsed < duration_seconds:
                continue

            mission_engine.mission_set_state("DECODING")
            time.sleep(0.3)

            if scenario == "satdump_returncode_1":
                detail = "Gesimuleerde SatDump-fout: returncode 1"
                _finish_mission(
                    success=False,
                    result="FAILED",
                    detail=detail,
                    error="satdump returncode 1",
                    metrics={
                        "duration_seconds": elapsed,
                        "peak_snr_db": peak_snr,
                        "frames": 0,
                        "cadu_bytes": 0,
                        "image_count": 0,
                    },
                )
                result = "FAILED"
                return

            mission_engine.mission_set_state("PROCESSING")
            time.sleep(0.3)
            mission_engine.mission_set_state("ARCHIVING")

            if scenario == "no_sync":
                _finish_mission(
                    success=False,
                    result="NO SYNC",
                    detail="Gesimuleerd zwak RF-signaal zonder decoder-sync",
                    metrics={
                        "duration_seconds": elapsed,
                        "peak_snr_db": peak_snr,
                        "frames": 0,
                        "cadu_bytes": 0,
                        "image_count": 0,
                    },
                )
                result = "NO SYNC"
            else:
                frames = max(12, elapsed * 4)
                _finish_mission(
                    success=True,
                    result="SUCCESS",
                    detail="Deterministische simulatiemissie voltooid",
                    metrics={
                        "duration_seconds": elapsed,
                        "peak_snr_db": peak_snr,
                        "frames": frames,
                        "cadu_bytes": frames * 8192,
                        "image_count": 3,
                        "quality_score": 92,
                        "quality_grade": "A",
                    },
                )
                result = "SUCCESS"
            return
    except Exception as error:
        error_text = str(error)
        try:
            status = mission_engine.get_mission_status()
            if status.get("active_job") is not None:
                _finish_mission(
                    success=False,
                    result="FAILED",
                    detail=f"Simulatiemissie afgebroken: {error}",
                    error=error_text,
                )
        except Exception:
            pass
        result = "FAILED"
    finally:
        try:
            _release(mission_key, "Simulatiereceiver vrijgegeven")
        finally:
            with _LOCK:
                _RUNTIME.update({
                    "active": False,
                    "stop_event": None,
                    "thread": None,
                    "last_result": result,
                    "last_error": error_text,
                })
            event_bus.publish_mission(
                "SYSTEM",
                "Simulatiemissie afgerond",
                str(result or "UNKNOWN"),
                data=_snapshot(),
            )


def start(*, scenario: str = "success", receiver_id: str = "sdr2", duration_seconds: int = 15):
    scenario = str(scenario or "success").strip().lower()
    receiver_id = str(receiver_id or "sdr2").strip().lower()
    if scenario not in SCENARIOS:
        raise ValueError(f"Onbekend scenario: {scenario}")
    duration_seconds = int(duration_seconds)
    if duration_seconds < 3 or duration_seconds > 300:
        raise ValueError("duration_seconds moet tussen 3 en 300 liggen")

    with _LOCK:
        if _RUNTIME["active"]:
            raise RuntimeError("Er is al een simulatiemissie actief")
        current = mission_engine.get_mission_status()
        if current.get("active_job") is not None or current.get("phase") != "READY":
            raise RuntimeError("Mission Engine is niet READY")

        device = get_device(receiver_id)
        if device is None:
            raise ValueError(f"Onbekende receiver: {receiver_id}")

        token = uuid.uuid4().hex[:10]
        mission_key = f"SIM:{scenario}:{token}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = OUTPUT_ROOT / f"{timestamp}_{scenario}_{receiver_id}"
        output_path.mkdir(parents=True, exist_ok=True)

        receiver_manager.reserve(
            receiver_id,
            mission_key=mission_key,
            reason=f"SDRCC simulatiemissie: {scenario}",
        )

        try:
            mission_engine.mission_create_job(
                satellite=f"SIMULATION {scenario.upper()}",
                frequency=137_900_000,
                mode="SIMULATION",
                pipeline=f"simulation_{scenario}",
                output_path=str(output_path),
                receiver=device.get("number"),
                receiver_id=device.get("id"),
                receiver_serial=device.get("serial"),
                sample_rate=1_000_000,
                gain_mode="manual",
                gain_db=40.2,
                dc_block=False,
                iq_swap=False,
            )
            job = mission_engine.get_mission_status().get("active_job") or {}

            if scenario == "receiver_lock_fail":
                mission_engine.mission_set_state("LOCK RECEIVER")
                _finish_mission(
                    success=False,
                    result="FAILED",
                    detail="Gesimuleerde receiver-lockfout",
                    error="receiver lock failed",
                )
                _release(mission_key, "Receiver vrijgegeven na gesimuleerde lockfout")
                _RUNTIME.update({
                    "active": False,
                    "scenario": scenario,
                    "receiver_id": receiver_id,
                    "mission_key": mission_key,
                    "mission_id": job.get("mission_id"),
                    "started_at": _now_iso(),
                    "duration_seconds": 0,
                    "last_result": "FAILED",
                    "last_error": "receiver lock failed",
                })
                return get_status()

            receiver_manager.activate(
                mission_key=mission_key,
                mission_id=job.get("mission_id"),
            )
            mission_engine.mission_set_state("LOCK RECEIVER")
            mission_engine.mission_set_state("RECORDING")

            live_rf.start({
                "pass": {
                    "name": f"SIMULATION {scenario.upper()}",
                    "frequency": 137_900_000,
                    "sample_rate": 1_000_000,
                },
                "device": device,
                "rf": {
                    "gain_mode": "manual",
                    "gain_db": 40.2,
                    "dc_block": False,
                    "iq_swap": False,
                },
                "output_path": output_path,
                "timeout_seconds": duration_seconds,
            }, pid=0)

            stop_event = Event()
            worker = Thread(
                target=_worker,
                kwargs={
                    "stop_event": stop_event,
                    "scenario": scenario,
                    "duration_seconds": duration_seconds,
                    "mission_key": mission_key,
                },
                name=f"sdrcc-simulator-{scenario}",
                daemon=True,
            )
            _RUNTIME.update({
                "active": True,
                "scenario": scenario,
                "receiver_id": receiver_id,
                "mission_key": mission_key,
                "mission_id": job.get("mission_id"),
                "started_at": _now_iso(),
                "duration_seconds": duration_seconds,
                "stop_event": stop_event,
                "thread": worker,
                "last_result": None,
                "last_error": None,
            })
            worker.start()
        except Exception:
            _release(mission_key, "Simulatiereceiver vrijgegeven na startfout")
            raise

    event_bus.publish_mission(
        "INFO",
        "Simulatiemissie gestart",
        f"{scenario} op {receiver_id.upper()}",
        data=_snapshot(),
    )
    return get_status()


def stop() -> dict[str, Any]:
    with _LOCK:
        if not _RUNTIME.get("active"):
            return {"ok": False, "message": "Er is geen simulatiemissie actief", **get_status()}
        stop_event = _RUNTIME.get("stop_event")
        if stop_event is not None:
            stop_event.set()
    return {"ok": True, "message": "Stop voor simulatiemissie aangevraagd", **get_status()}
