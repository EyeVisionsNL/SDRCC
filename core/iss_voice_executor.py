#!/usr/bin/env python3
"""Flexible ISS Voice mission executor for SDRCC v0.48.0e.

Receiver ownership is resolved from configuration at runtime. The executor only
stops active services mapped to the selected receiver, records wideband IQ,
demodulates WAV, records lifecycle events, then restores exactly what it stopped.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable
import json
import os

from core import device_manager, execution_factory, execution_journal, event_bus
from core import iss_voice, iss_voice_audio, iss_voice_runtime, receiver_manager, wideband_iq_recorder

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = PROJECT_ROOT / "data" / "state" / "mission_history.json"

ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, int], bool]


def _result_ok(result: Any) -> bool:
    return int(getattr(result, "returncode", 1)) == 0


def _append_history(item: dict[str, Any]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []
    except Exception:
        history = []
    if not isinstance(history, list):
        history = []
    history.insert(0, item)
    temp = HISTORY_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(history[:100], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temp, HISTORY_FILE)


def execute_pass(*, target: dict[str, Any], service_state: ServiceState,
                 service_action: ServiceAction, wait_for_service: ServiceWait,
                 mission_key: str | None = None) -> dict[str, Any]:
    validation = iss_voice.validate_config()
    if not validation["ok"]:
        raise RuntimeError("ISS Voice-config ongeldig: " + "; ".join(validation["errors"]))
    cfg = validation["config"]
    if not bool(cfg.get("execution_enabled")) or not bool(cfg.get("receiver_claim_enabled")):
        raise RuntimeError("ISS Voice automatic execution is disabled")

    device = device_manager.get_assigned_device("iss_voice")
    if device is None:
        raise RuntimeError("Geen receiver toegewezen aan ISS Voice")

    mission_id = "iss_voice_" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    mission_key = str(mission_key or f"iss_voice:{mission_id}")
    duration = max(1, min(int(target.get("duration_seconds") or 1), 1200))
    stopped_services: list[str] = []
    execution_id = None
    reserved = False
    started = datetime.now().astimezone()
    output_dir: Path | None = None
    failure: Exception | None = None
    capture: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None

    plan = execution_factory.build_plan_with_journal("iss_voice", {
        "mode": "automatic_pass", "target": target.get("name") or cfg.get("satellite_name"),
        "receiver_role": "iss_voice", "receiver_id": device["id"],
        "duration_seconds": duration, "frequency": int(cfg["downlink_frequency_hz"]),
    })
    execution_id = plan["execution_id"]
    execution_journal.append_event_once(execution_id, "ACCEPTED", source="iss_voice_executor",
        details={"mission_id": mission_id, "receiver_id": device["id"], "queue_key": target.get("queue_key")})

    try:
        receiver_manager.reserve(device["id"], mission_key=mission_key, mission_id=mission_id,
                                 reason="ISS Voice automatic mission")
        reserved = True
        iss_voice_runtime.begin(
            mission_id=mission_id, execution_id=execution_id, receiver_id=device["id"],
            receiver_serial=device.get("serial"), satellite=target.get("name") or cfg.get("satellite_name"),
            frequency_hz=int(cfg["downlink_frequency_hz"]), sample_rate_hz=int(cfg["rf_sample_rate_hz"]),
            duration_seconds=duration, mode=cfg.get("modulation", "NFM"), phase="PREPARING",
            detail="Preparing receiver for ISS Voice capture",
        )
        for service in device_manager.get_conflicting_services(device["id"], exclude_role="iss_voice"):
            state = service_state(service)
            if not bool(state.get("active")):
                continue
            result = service_action("stop", service)
            if not _result_ok(result) or not wait_for_service(service, "inactive", 15):
                raise RuntimeError(f"{service} kon niet veilig worden gestopt")
            stopped_services.append(service)
            event_bus.publish_receiver(
                "INFO", "Conflicting receiver service stopped", service,
                data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device["id"], "service": service},
            )

        receiver_manager.activate(mission_key=mission_key, mission_id=mission_id)
        execution_journal.append_event_once(execution_id, "STARTED", source="iss_voice_executor",
            details={"mission_id": mission_id, "receiver_id": device["id"], "stopped_services": stopped_services})

        spec = wideband_iq_recorder.build_spec(
            mission_id=mission_id, receiver_serial=device["serial"],
            frequency_hz=int(cfg["downlink_frequency_hz"]), sample_rate_hz=int(cfg["rf_sample_rate_hz"]),
            duration_seconds=duration, gain_db=cfg.get("gain_db"), ppm=int(cfg.get("ppm") or 0),
        )
        output_dir = spec.output_directory
        iss_voice_runtime.update(
            phase="RECORDING", output_directory=str(spec.output_directory), iq_path=str(spec.iq_path),
            metadata_path=str(spec.metadata_path), detail="Wideband IQ recording active",
        )
        event_bus.publish_receiver(
            "SUCCESS", "ISS Voice IQ recording started",
            f"{int(cfg['downlink_frequency_hz']) / 1_000_000:.4f} MHz at {int(cfg['rf_sample_rate_hz']) / 1000:.0f} kS/s",
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device["id"],
                  "frequency_hz": int(cfg["downlink_frequency_hz"]), "sample_rate_hz": int(cfg["rf_sample_rate_hz"]),
                  "iq_path": str(spec.iq_path), "duration_seconds": duration},
        )
        capture = wideband_iq_recorder.execute_capture(spec, services_confirmed_stopped=True)
        if not capture.get("complete"):
            raise RuntimeError(f"IQ-opname onvolledig (returncode {capture.get('returncode')})")
        iss_voice_runtime.update(
            phase="DEMODULATING", iq_bytes=capture.get("actual_bytes"),
            detail="IQ capture complete; creating audio",
        )
        event_bus.publish_receiver(
            "SUCCESS", "ISS Voice IQ recording completed",
            f"{int(capture.get('actual_bytes') or 0):,} bytes written",
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device["id"],
                  "iq_path": capture.get("iq_path"), "size_bytes": capture.get("actual_bytes")},
        )
        event_bus.publish_mission(
            "INFO", "ISS Voice audio processing started", mission_id,
            data={"plugin_id": "iss_voice", "mission_id": mission_id},
        )
        audio = iss_voice_audio.demodulate_mission(mission_id, cfg)
        iss_voice_runtime.update(
            phase="FINALIZING", wav_path=audio.get("wav_path"), detail="Audio created; restoring receiver context",
        )
        event_bus.publish_mission(
            "SUCCESS", "ISS Voice audio created", str(audio.get("wav_path") or "audio.wav"),
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "wav_path": audio.get("wav_path")},
        )
        execution_journal.append_event_once(execution_id, "FINISHED", source="iss_voice_executor",
            details={"mission_id": mission_id, "wav_path": audio.get("wav_path"), "iq_path": capture.get("iq_path")})
    except Exception as exc:
        failure = exc
        iss_voice_runtime.update(phase="FAILED", detail=str(exc), error=str(exc))
        event_bus.publish_mission(
            "ERROR", "ISS Voice capture failed", str(exc),
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device.get("id")},
        )
        execution_journal.append_event_once(execution_id, "FAILED", source="iss_voice_executor",
            details={"mission_id": mission_id, "error": str(exc)})
    finally:
        restore_errors = []
        for service in reversed(stopped_services):
            result = service_action("start", service)
            if not _result_ok(result) or not wait_for_service(service, "active", 15):
                restore_errors.append(service)
            else:
                event_bus.publish_receiver(
                    "SUCCESS", "Receiver service restored", service,
                    data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device["id"], "service": service},
                )
        if reserved:
            try:
                receiver_manager.release(mission_key=mission_key, detail="ISS Voice context restored")
            except Exception as exc:
                restore_errors.append(f"receiver:{exc}")
        if restore_errors:
            extra = "Herstel onvolledig: " + ", ".join(restore_errors)
            failure = RuntimeError(f"{failure}; {extra}" if failure else extra)

    ended = datetime.now().astimezone()
    wav_path = (audio or {}).get("wav_path")
    wav_size = Path(wav_path).stat().st_size if wav_path and Path(wav_path).exists() else 0
    history = {
        "mission_id": mission_id, "satellite": target.get("name") or cfg.get("satellite_name"),
        "mission_type": "iss_voice", "plugin_id": "iss_voice", "frequency": int(cfg["downlink_frequency_hz"]),
        "sample_rate": int(cfg["rf_sample_rate_hz"]), "audio_sample_rate": int(cfg["audio_sample_rate_hz"]),
        "mode": cfg.get("modulation", "NFM"), "pipeline": "wideband_iq_offline_fm",
        "receiver": device.get("number"), "receiver_id": device.get("id"), "receiver_serial": device.get("serial"),
        "output_path": str(output_dir) if output_dir else "", "created_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"), "ended_at": ended.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": int((ended-started).total_seconds()), "success": failure is None,
        "result": "SUCCESS" if failure is None else "FAILED", "detail": "ISS Voice WAV recording created" if failure is None else str(failure),
        "error": str(failure) if failure else None, "image_count": 0, "recording_count": 1 if wav_size else 0,
        "recordings": ([{"type": "audio", "format": "wav", "name": Path(wav_path).name,
                         "path": wav_path, "size_bytes": wav_size}] if wav_size else []),
        "execution_id": execution_id,
    }
    _append_history(history)
    iss_voice_runtime.finish(
        success=failure is None, detail=history["detail"], mission_id=mission_id, execution_id=execution_id,
        receiver_id=device.get("id"), iq_path=(capture or {}).get("iq_path"),
        iq_bytes=(capture or {}).get("actual_bytes"), wav_path=(audio or {}).get("wav_path"),
    )
    event_bus.publish_mission(
        "SUCCESS" if failure is None else "ERROR",
        "ISS Voice mission completed" if failure is None else "ISS Voice mission failed",
        history["detail"],
        data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device.get("id"),
              "execution_id": execution_id, "success": failure is None},
    )
    if failure:
        raise failure
    return {"ok": True, "version": "0.48.0e", "mission": history,
            "capture": capture, "audio": audio, "stopped_and_restored_services": stopped_services}
