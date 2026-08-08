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
import time

from core import device_manager, execution_factory, execution_journal, event_bus
from core import iss_voice, iss_voice_audio, iss_voice_runtime, mission_history, receiver_manager, wideband_iq_recorder

ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, int], bool]

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
    planned_duration = max(1, min(int(target.get("duration_seconds") or 1), 1200))
    duration = planned_duration
    stopped_services: list[str] = []
    execution_id = None
    handover_started = False
    started = datetime.now().astimezone()
    output_dir: Path | None = None
    failure: Exception | None = None
    capture: dict[str, Any] | None = None
    audio: dict[str, Any] | None = None

    plan = execution_factory.build_plan_with_journal("iss_voice", {
        "mode": "automatic_pass", "target": target.get("name") or cfg.get("satellite_name"),
        "receiver_role": "iss_voice", "receiver_id": device["id"],
        "duration_seconds": planned_duration, "frequency": int(cfg["downlink_frequency_hz"]),
        "pass_contract": {
            key: target.get(key)
            for key in (
                "queue_key", "start_epoch", "maximum_epoch", "end_epoch",
                "minimum_peak_elevation", "begin_elevation", "close_elevation",
                "norad_id", "tle_source", "tle_epoch", "tle_sha256",
            )
        },
    })
    execution_id = plan["execution_id"]
    execution_journal.append_event_once(execution_id, "ACCEPTED", source="iss_voice_executor",
        details={"mission_id": mission_id, "receiver_id": device["id"], "queue_key": target.get("queue_key")})

    try:
        iss_voice_runtime.begin(
            mission_id=mission_id, execution_id=execution_id, receiver_id=device["id"],
            receiver_serial=device.get("serial"), satellite=target.get("name") or cfg.get("satellite_name"),
            frequency_hz=int(cfg["downlink_frequency_hz"]), sample_rate_hz=int(cfg["rf_sample_rate_hz"]),
            duration_seconds=planned_duration, mode=cfg.get("modulation", "NFM"), phase="PREPARING",
            queue_key=target.get("queue_key"), start_epoch=target.get("start_epoch"),
            maximum_epoch=target.get("maximum_epoch"), end_epoch=target.get("end_epoch"),
            detail="Preparing receiver for ISS Voice capture",
        )
        conflicts = device_manager.get_conflicting_services(device["id"], exclude_role="iss_voice")
        iss_voice_runtime.update(
            phase="STOPPING_CONFLICTS",
            conflicting_services=conflicts,
            detail="Stopping conflicting receiver services",
        )
        manager_status = receiver_manager.begin_handover(
            device["id"],
            mission_key=mission_key,
            mission_id=mission_id,
            reason="ISS Voice automatic mission",
            services=conflicts,
            service_state=service_state,
            service_action=service_action,
            wait_for_service=wait_for_service,
        )
        handover_started = True
        reservation = (manager_status.get("reservations") or {}).get(device["id"]) or {}
        handover = reservation.get("handover") or {}
        stopped_services = [
            item.get("service")
            for item in handover.get("services") or []
            if item.get("stopped_by_sdrcc")
        ]

        iss_voice_runtime.update(
            phase="WAITING_FOR_RECEIVER",
            stopped_services=stopped_services,
            detail="Conflicting services stopped; waiting for receiver release",
        )
        receiver_manager.activate(mission_key=mission_key, mission_id=mission_id)
        execution_journal.append_event_once(execution_id, "STARTED", source="iss_voice_executor",
            details={"mission_id": mission_id, "receiver_id": device["id"], "stopped_services": stopped_services})

        end_epoch = int(target.get("end_epoch") or 0)
        if end_epoch:
            remaining = end_epoch - int(time.time())
            if remaining <= 0:
                raise RuntimeError("ISS Voice pass window ended before capture could start")
            duration = max(1, min(planned_duration, remaining, 1200))
            iss_voice_runtime.update(
                duration_seconds=duration,
                detail="Receiver ready; capture bounded by the planned falling edge",
            )

        spec = wideband_iq_recorder.build_spec(
            mission_id=mission_id, receiver_serial=device["serial"],
            frequency_hz=int(cfg["downlink_frequency_hz"]), sample_rate_hz=int(cfg["rf_sample_rate_hz"]),
            duration_seconds=duration, gain_db=iss_voice.capture_gain_db(cfg), ppm=int(cfg.get("ppm") or 0),
        )
        output_dir = spec.output_directory
        iss_voice_runtime.update(
            phase="STARTING_CAPTURE", output_directory=str(spec.output_directory), iq_path=str(spec.iq_path),
            metadata_path=str(spec.metadata_path), stopped_services=stopped_services,
            detail="Starting and verifying RTL-SDR capture",
        )

        def capture_started(start_metadata: dict[str, Any]) -> None:
            iss_voice_runtime.update(
                phase="RECORDING",
                capture_pid=start_metadata.get("capture_pid"),
                capture_started_at=start_metadata.get("capture_started_at"),
                startup_bytes=start_metadata.get("startup_bytes"),
                capture_attempt=start_metadata.get("active_attempt"),
                detail="Wideband IQ recording verified active",
            )
            event_bus.publish_receiver(
                "SUCCESS", "ISS Voice IQ recording verified",
                f"{int(cfg['downlink_frequency_hz']) / 1_000_000:.4f} MHz at {int(cfg['rf_sample_rate_hz']) / 1000:.0f} kS/s",
                data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device["id"],
                      "frequency_hz": int(cfg["downlink_frequency_hz"]), "sample_rate_hz": int(cfg["rf_sample_rate_hz"]),
                      "iq_path": str(spec.iq_path), "duration_seconds": duration,
                      "pid": start_metadata.get("capture_pid"), "attempt": start_metadata.get("active_attempt")},
            )

        capture = wideband_iq_recorder.execute_capture(
            spec,
            services_confirmed_stopped=True,
            retry_count=2,
            retry_delay_seconds=2.0,
            startup_timeout_seconds=5.0,
            on_started=capture_started,
        )
        if not capture.get("complete"):
            stderr = str(capture.get("stderr") or "").strip()
            detail = f"IQ-opname onvolledig (returncode {capture.get('returncode')}, {capture.get('actual_bytes')} bytes)"
            if stderr:
                detail += f": {stderr[-1000:]}"
            raise RuntimeError(detail)
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
        wav_path_value = audio.get("wav_path")
        wav_bytes = int(audio.get("wav_bytes") or 0)
        wav_duration = float(audio.get("audio_duration_seconds") or 0.0)
        minimum_duration = max(0.5, duration * 0.90)
        if not audio.get("ok") or not wav_path_value or wav_bytes <= 44 or wav_duration < minimum_duration:
            raise RuntimeError(
                "WAV-validatie mislukt "
                f"(bytes={wav_bytes}, duur={wav_duration:.3f}s, minimum={minimum_duration:.3f}s)"
            )
        iss_voice_runtime.update(
            phase="FINALIZING", wav_path=wav_path_value, wav_bytes=wav_bytes,
            audio_duration_seconds=wav_duration,
            detail="Audio validated; restoring receiver context",
        )
        event_bus.publish_mission(
            "SUCCESS", "ISS Voice audio created", str(audio.get("wav_path") or "audio.wav"),
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "wav_path": audio.get("wav_path")},
        )
    except Exception as exc:
        failure = exc
        iss_voice_runtime.update(phase="FAILED", detail=str(exc), error=str(exc))
        event_bus.publish_mission(
            "ERROR", "ISS Voice capture failed", str(exc),
            data={"plugin_id": "iss_voice", "mission_id": mission_id, "receiver_id": device.get("id")},
        )
    finally:
        restore_errors = []
        if handover_started:
            restored = receiver_manager.restore_handover(
                mission_key=mission_key,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
                detail="ISS Voice context restored",
            )
            restore_errors.extend(restored.get("errors") or [])
        else:
            try:
                receiver_manager.release(
                    mission_key=mission_key,
                    detail="ISS Voice reservation released before handover",
                )
            except RuntimeError as exc:
                if "Geen receiver-reservering" not in str(exc):
                    restore_errors.append(f"receiver release: {exc}")
        if restore_errors:
            extra = "Herstel onvolledig: " + ", ".join(restore_errors)
            failure = RuntimeError(f"{failure}; {extra}" if failure else extra)

    if failure is None:
        execution_journal.append_event_once(
            execution_id,
            "FINISHED",
            source="iss_voice_executor",
            details={
                "mission_id": mission_id,
                "wav_path": (audio or {}).get("wav_path"),
                "iq_path": (capture or {}).get("iq_path"),
                "restored_services": stopped_services,
            },
        )
    else:
        execution_journal.append_event_once(
            execution_id,
            "FAILED",
            source="iss_voice_executor",
            details={
                "mission_id": mission_id,
                "error": str(failure),
                "capture_returncode": (capture or {}).get("returncode"),
                "capture_bytes": (capture or {}).get("actual_bytes"),
                "capture_stderr": str((capture or {}).get("stderr") or "")[-2000:],
                "stopped_services": stopped_services,
            },
        )

    ended = datetime.now().astimezone()
    wav_path = (audio or {}).get("wav_path")
    wav_size = Path(wav_path).stat().st_size if wav_path and Path(wav_path).exists() else 0
    history = {
        "mission_id": mission_id, "satellite": target.get("name") or cfg.get("satellite_name"),
        "mission_type": "iss_voice", "plugin_id": "iss_voice", "frequency": int(cfg["downlink_frequency_hz"]),
        "sample_rate": int(cfg["rf_sample_rate_hz"]), "audio_sample_rate": int(cfg["audio_sample_rate_hz"]),
        "gain_mode": cfg.get("gain_mode", "auto"), "gain_db": iss_voice.capture_gain_db(cfg),
        "squelch_enabled": bool(cfg.get("squelch_enabled", False)),
        "squelch_threshold_dbfs": float(cfg.get("squelch_threshold_dbfs", -42.0)),
        "mode": cfg.get("modulation", "NFM"), "pipeline": "wideband_iq_offline_fm",
        "receiver": device.get("number"), "receiver_id": device.get("id"), "receiver_serial": device.get("serial"),
        "output_path": str(output_dir) if output_dir else "", "created_at": started.strftime("%Y-%m-%d %H:%M:%S"),
        "started_at": started.strftime("%Y-%m-%d %H:%M:%S"), "ended_at": ended.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_seconds": int((ended-started).total_seconds()), "success": failure is None,
        "result": "SUCCESS" if failure is None else "FAILED", "detail": "ISS Voice WAV recording created" if failure is None else str(failure),
        "error": str(failure) if failure else None, "image_count": 0, "recording_count": 1 if wav_size else 0,
        "audio_content_assessment": "UNASSESSED",
        "recordings": ([{"type": "audio", "format": "wav", "name": Path(wav_path).name,
                         "path": wav_path, "size_bytes": wav_size}] if wav_size else []),
        "execution_id": execution_id,
        "planning_profile_id": target.get("planning_profile_id"),
        "minimum_peak_elevation": target.get("minimum_peak_elevation"),
        "begin_elevation": target.get("begin_elevation"),
        "close_elevation": target.get("close_elevation"),
        "norad_id": target.get("norad_id"),
        "tle_source": target.get("tle_source"),
        "tle_epoch": target.get("tle_epoch"),
        "tle_sha256": target.get("tle_sha256"),
    }
    mission_history.record_mission(history)
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
    return {"ok": True, "version": "0.54.0h", "mission": history,
            "capture": capture, "audio": audio, "stopped_and_restored_services": stopped_services}
