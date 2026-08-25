#!/usr/bin/env python3
"""Transactional HF Monitor lifecycle.

Receiver Manager owns receiver reservation and exact service restoration.  The
dashboard injects its existing service read/action/wait functions.  This
controller only orders the bounded handover around the single-owner HF backend
and persists enough session intent for restart recovery.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from core import device_manager, hf_monitor, hf_monitor_backend, receiver_manager


VERSION = "0.56.0d"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
SESSION_FILE = STATE_DIR / "hf_monitor_session.json"
MISSION_PREFIX = "hf_monitor"

ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, int], bool]

_lock = threading.RLock()


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _write_session(document: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, SESSION_FILE)


def _read_session() -> dict[str, Any] | None:
    if not SESSION_FILE.is_file():
        return None
    try:
        document = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception as error:
        raise RuntimeError(f"HF Monitor session is onleesbaar: {error}") from error
    if not isinstance(document, dict):
        raise RuntimeError("HF Monitor session moet een JSON-object zijn")
    if document.get("version") not in {"0.56.0c", VERSION}:
        raise RuntimeError("HF Monitor session heeft een onbekende versie")
    mission_key = str(document.get("mission_key") or "")
    if not mission_key.startswith(f"{MISSION_PREFIX}:"):
        raise RuntimeError("HF Monitor session heeft geen geldige mission_key")
    return document


def _clear_session() -> None:
    try:
        SESSION_FILE.unlink()
    except FileNotFoundError:
        pass


def _session_id() -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid4().hex[:8]}"


def get_session() -> dict[str, Any] | None:
    with _lock:
        session = _read_session()
        return deepcopy(session) if session else None


def _conflicting_services(receiver_id: str) -> list[str]:
    return device_manager.get_conflicting_services(
        receiver_id,
        exclude_role="hf_monitor",
    )


def _start_watchdog(
    mission_key: str,
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> None:
    """Restore the receiver automatically if live IQ stops unexpectedly."""
    def watch() -> None:
        while True:
            time.sleep(0.5)
            try:
                session = get_session()
            except RuntimeError:
                return
            if not session or session.get("mission_key") != mission_key:
                return
            if session.get("status") != "LISTENING":
                return
            runtime = hf_monitor_backend.get_status()
            if runtime.get("state") in {"STARTING", "LISTENING"}:
                continue
            try:
                stop(
                    service_state=service_state,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                    recovery=True,
                )
            except Exception:
                pass
            return

    threading.Thread(
        target=watch,
        daemon=True,
        name=f"sdrcc-hf-watchdog-{mission_key.rsplit(':', 1)[-1]}",
    ).start()


def start(
    selection: dict[str, Any],
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    """Start one HF session and roll back every failed intermediate step."""
    normalized = hf_monitor.validate_selection(selection)
    rf_controls = hf_monitor.validate_rf_controls(selection.get("rf_controls"))
    device = device_manager.get_device(normalized["receiver_id"])
    if device is None:
        raise ValueError(f"Onbekende receiver: {normalized['receiver_id']}")

    with _lock:
        existing = _read_session()
        if existing is not None:
            raise RuntimeError(
                "Er bestaat al een HF Monitor sessie; stop of herstel die eerst."
            )
        backend_state = hf_monitor_backend.get_status()
        if backend_state.get("state") not in {"STOPPED"}:
            raise RuntimeError("HF backend is niet vrij")

        session_id = _session_id()
        mission_key = f"{MISSION_PREFIX}:{session_id}"
        services = _conflicting_services(device["id"])
        session = {
            "version": VERSION,
            "session_id": session_id,
            "mission_key": mission_key,
            "status": "PREPARING",
            "created_at": _now(),
            "updated_at": _now(),
            "receiver": {
                "id": device["id"],
                "runtime_id": device["runtime_id"],
                "registry_id": device["registry_id"],
                "serial": device["serial"],
                "name": device["name"],
            },
            "selection": normalized,
            "rf_controls": {key: value for key, value in rf_controls.items() if key != "valid_gains"},
            "handover_services": list(services),
            "backend": hf_monitor_backend.BACKEND_ID,
            "restore_contract": "exact_pre_start_service_state",
        }
        _write_session(session)

        handover_started = False
        try:
            receiver_manager.begin_handover(
                device["id"],
                mission_key=mission_key,
                mission_id=session_id,
                reason="HF Amateur Monitor operator session",
                services=services,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
                release_delay_seconds=2.0,
            )
            handover_started = True
            session["status"] = "STARTING_BACKEND"
            session["handover_ready_at"] = _now()
            session["updated_at"] = _now()
            _write_session(session)

            runtime = hf_monitor_backend.start(
                serial=device["serial"],
                receiver_id=device["runtime_id"],
                center_frequency_hz=normalized["frequency_hz"],
                band=normalized["band"],
                mode=normalized["mode"],
                gain_mode=rf_controls["gain_mode"],
                gain_db=rf_controls["gain_db"],
                squelch_enabled=rf_controls["squelch_enabled"],
                squelch_threshold_dbfs=rf_controls["squelch_threshold_dbfs"],
            )
            receiver_manager.activate(
                mission_key=mission_key,
                mission_id=session_id,
            )
            session["status"] = "LISTENING"
            session["started_at"] = _now()
            session["updated_at"] = _now()
            session["sampling_mode"] = runtime.get("settings", {}).get("sampling_mode")
            _write_session(session)
            _start_watchdog(
                mission_key,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
            )
            return {
                "ok": True,
                "action": "start",
                "message": (
                    f"HF luistert op {normalized['frequency_hz'] / 1_000_000:.6f} MHz "
                    f"{normalized['mode']} via {device['name']}."
                ),
                "session": deepcopy(session),
                "backend": runtime,
                "receiver_authority": "receiver_manager",
            }
        except Exception as error:
            restore_errors: list[str] = []
            try:
                hf_monitor_backend.stop()
            except Exception as stop_error:
                restore_errors.append(f"HF backend: {stop_error}")
            if handover_started:
                restored = receiver_manager.restore_handover(
                    mission_key=mission_key,
                    service_state=service_state,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                    detail="HF Monitor start failed; receiver context restored",
                )
                restore_errors.extend(restored.get("errors") or [])
            else:
                try:
                    receiver_manager.release(
                        mission_key=mission_key,
                        detail="HF Monitor start failed before handover",
                    )
                except RuntimeError as release_error:
                    if "Geen receiver-reservering" not in str(release_error):
                        restore_errors.append(f"receiver release: {release_error}")
            if restore_errors:
                session["status"] = "ATTENTION"
                session["error"] = str(error)
                session["restore_errors"] = restore_errors
                session["updated_at"] = _now()
                _write_session(session)
                raise RuntimeError(
                    f"{error}; herstel vereist aandacht: " + "; ".join(restore_errors)
                ) from error
            _clear_session()
            raise RuntimeError(str(error)) from error


def retune(selection: dict[str, Any]) -> dict[str, Any]:
    """Retune only the live HF backend; keep the handover/session intact."""
    normalized = hf_monitor.validate_selection(selection)
    with _lock:
        session = _read_session()
        if session is None or session.get("status") != "LISTENING":
            raise RuntimeError("Er is geen actieve HF-sessie om live af te stemmen")
        active = session.get("selection")
        if not isinstance(active, dict):
            raise RuntimeError("De actieve HF-selectie ontbreekt")
        for field, label in (
            ("receiver_id", "ontvanger"),
            ("band", "amateurband"),
            ("mode", "demodulatiemodus"),
        ):
            if normalized[field] != active.get(field):
                raise ValueError(f"Live afstemmen mag de actieve {label} niet wijzigen")
        runtime = hf_monitor_backend.retune(
            center_frequency_hz=normalized["frequency_hz"],
        )
        session["selection"] = normalized
        session["retuned_at"] = _now()
        session["updated_at"] = _now()
        _write_session(session)
        return {
            "ok": True,
            "action": "retune",
            "message": (
                f"HF live afgestemd op {normalized['frequency_hz'] / 1_000_000:.6f} MHz "
                f"{normalized['mode']}; de receiver-overdracht bleef actief."
            ),
            "session": deepcopy(session),
            "backend": runtime,
            "receiver_handover_changed": False,
        }


def update_rf_controls(controls: dict[str, Any]) -> dict[str, Any]:
    """Apply live gain/squelch without changing receiver handover authority."""
    normalized = hf_monitor.validate_rf_controls(controls)
    with _lock:
        session = _read_session()
        if session is None or session.get("status") != "LISTENING":
            raise RuntimeError("Er is geen actieve HF-sessie voor live RF-instellingen")
        runtime = hf_monitor_backend.update_rf_controls(
            gain_mode=normalized["gain_mode"],
            gain_db=normalized["gain_db"],
            squelch_enabled=normalized["squelch_enabled"],
            squelch_threshold_dbfs=normalized["squelch_threshold_dbfs"],
        )
        session["rf_controls"] = {
            key: value for key, value in normalized.items() if key != "valid_gains"
        }
        session["rf_controls_updated_at"] = _now()
        session["updated_at"] = _now()
        _write_session(session)
        return {
            "ok": True,
            "action": "rf_settings",
            "message": "HF gain en squelch zijn live toegepast binnen dezelfde IQ-owner.",
            "session": deepcopy(session),
            "backend": runtime,
            "receiver_handover_changed": False,
        }


def stop(
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
    recovery: bool = False,
) -> dict[str, Any]:
    """Stop the HF backend before restoring only previously active services."""
    with _lock:
        session = _read_session()
        backend = hf_monitor_backend.get_status()
        if session is None:
            if backend.get("state") != "STOPPED":
                hf_monitor_backend.stop()
            return {
                "ok": True,
                "action": "stop",
                "already_stopped": True,
                "message": "HF Monitor was al gestopt.",
            }

        session["status"] = "STOPPING"
        session["updated_at"] = _now()
        _write_session(session)
        errors: list[str] = []
        try:
            hf_monitor_backend.stop()
        except Exception as error:
            errors.append(f"HF backend: {error}")

        restored = receiver_manager.restore_handover(
            mission_key=str(session["mission_key"]),
            service_state=service_state,
            service_action=service_action,
            wait_for_service=wait_for_service,
            detail=(
                "HF Monitor context restored after dashboard recovery"
                if recovery else "HF Monitor stopped; receiver context restored"
            ),
        )
        errors.extend(restored.get("errors") or [])
        if errors or not restored.get("ok"):
            session["status"] = "ATTENTION"
            session["restore_errors"] = errors or ["receiver handover restore failed"]
            session["updated_at"] = _now()
            _write_session(session)
            raise RuntimeError("HF Monitor herstel vereist aandacht: " + "; ".join(session["restore_errors"]))

        _clear_session()
        return {
            "ok": True,
            "action": "stop",
            "message": "HF Monitor gestopt; de exacte eerdere receiverstatus is hersteld.",
            "restored": restored,
            "recovery": bool(recovery),
        }


def recover_stale_session(
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    """Fail closed after a dashboard restart instead of resuming stale RF."""
    with _lock:
        session = _read_session()
    if session is None:
        return {"ok": True, "changed": False}
    result = stop(
        service_state=service_state,
        service_action=service_action,
        wait_for_service=wait_for_service,
        recovery=True,
    )
    return {
        "ok": bool(result.get("ok")),
        "changed": True,
        "session_id": session.get("session_id"),
        "result": result,
    }
