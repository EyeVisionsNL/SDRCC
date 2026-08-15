#!/usr/bin/env python3
"""Transactional Marine Voice topology orchestration for SDRCC v0.55.0b.

This module never opens SDR hardware and has no service-control authority of
its own. The dashboard injects its existing systemctl adapter. Receiver
Manager remains reservation/handover authority and station assignments remain
the only persistent role authority.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import json
import os
import threading
from typing import Any, Callable

from core import config, mission_engine, receiver_manager, receiver_registry, traffic_voice


VOICE_SERVICE = "sdrcc-traffic-voice.service"
AIS_SERVICE = "ais-catcher.service"
ADSB_SERVICE = "readsb.service"
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
SESSION_FILE = STATE_DIR / "traffic_voice_session.json"
SESSION_VERSION = 1
_LOCK = threading.RLock()

ServiceState = Callable[[str], dict[str, Any]]
ServiceAction = Callable[[str, str], Any]
ServiceWait = Callable[[str, str, float], bool]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _session_service_states(
    states: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        service: {
            "active": bool((states.get(service) or {}).get("active")),
            "state": str((states.get(service) or {}).get("state") or "unknown"),
        }
        for service in (VOICE_SERVICE, AIS_SERVICE, ADSB_SERVICE)
    }


def _load_session() -> dict[str, Any] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        document = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Traffic Voice sessiestatus is onleesbaar: {SESSION_FILE}: {error}"
        ) from error
    if not isinstance(document, dict) or document.get("version") != SESSION_VERSION:
        raise RuntimeError("Traffic Voice sessiestatus heeft een onbekende versie")
    if document.get("mode") != "marine_ais":
        raise RuntimeError("Traffic Voice sessiestatus bevat een onbekende modus")
    previous = document.get("previous_services")
    assignments = document.get("previous_assignments")
    if not isinstance(previous, dict) or not isinstance(assignments, dict):
        raise RuntimeError("Traffic Voice sessiestatus mist herstelgegevens")
    for service in (VOICE_SERVICE, AIS_SERVICE, ADSB_SERVICE):
        item = previous.get(service)
        if not isinstance(item, dict) or not isinstance(item.get("active"), bool):
            raise RuntimeError(
                f"Traffic Voice sessiestatus mist een geldige toestand voor {service}"
            )
    return deepcopy(document)


def _write_session(
    previous: dict[str, dict[str, Any]],
    previous_assignments: dict[str, str | None],
    *,
    voice_receiver: str,
) -> dict[str, Any]:
    payload = {
        "version": SESSION_VERSION,
        "mode": "marine_ais",
        "created_at": _now(),
        "voice_receiver": voice_receiver,
        "previous_services": _session_service_states(previous),
        "previous_assignments": {
            "traffic_voice": previous_assignments.get("traffic_voice"),
        },
    }
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_FILE.with_suffix(".json.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, SESSION_FILE)
        directory_fd = os.open(SESSION_FILE.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return deepcopy(payload)


def _clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)
    if SESSION_FILE.parent.exists():
        directory_fd = os.open(SESSION_FILE.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def _result_ok(result: Any) -> bool:
    return int(getattr(result, "returncode", 1)) == 0


def _result_error(result: Any) -> str:
    return str(
        getattr(result, "stderr", "")
        or getattr(result, "stdout", "")
        or f"returncode {getattr(result, 'returncode', '?')}"
    ).strip()


def _other_receiver(context_receiver: str | None) -> str:
    canonical = receiver_registry.resolve_id(context_receiver)
    receivers = receiver_registry.get_receivers()
    if len(receivers) != 2:
        raise RuntimeError("Traffic Voice vereist exact twee ingeschakelde receivers")
    candidates = [item for item in receivers if item["id"] != canonical]
    if canonical is None or len(candidates) != 1:
        raise RuntimeError("De andere receiver kon niet eenduidig worden afgeleid")
    return str(candidates[0]["runtime_id"])


def _observe(service_state: ServiceState) -> dict[str, dict[str, Any]]:
    return {
        service: deepcopy(service_state(service))
        for service in (VOICE_SERVICE, AIS_SERVICE, ADSB_SERVICE)
    }


def _apply_service(
    operation: str,
    service: str,
    *,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    result = service_action(operation, service)
    expected = "active" if operation == "start" else "inactive"
    reached = _result_ok(result) and bool(wait_for_service(service, expected, 15))
    record = {
        "operation": operation,
        "service": service,
        "returncode": int(getattr(result, "returncode", 1)),
        "state_reached": reached,
        "error": "" if reached else _result_error(result),
    }
    if not reached:
        raise RuntimeError(
            f"{operation} {service} mislukt: {record['error'] or expected + ' niet bereikt'}"
        )
    return record


def _restore(
    previous: dict[str, dict[str, Any]],
    previous_assignments: dict[str, str | None],
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> tuple[list[dict[str, Any]], list[str]]:
    actions: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        config.set_plugin_assignments({
            "traffic_voice": previous_assignments.get("traffic_voice"),
        })
    except Exception as error:  # noqa: BLE001 - rollback must continue
        errors.append(f"assignment: {error}")

    for service in (VOICE_SERVICE, AIS_SERVICE, ADSB_SERVICE):
        wanted = bool((previous.get(service) or {}).get("active"))
        current = bool((service_state(service) or {}).get("active"))
        if current and not wanted:
            try:
                actions.append(_apply_service(
                    "stop", service,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
            except Exception as error:  # noqa: BLE001
                errors.append(str(error))

    for service in (ADSB_SERVICE, AIS_SERVICE, VOICE_SERVICE):
        wanted = bool((previous.get(service) or {}).get("active"))
        current = bool((service_state(service) or {}).get("active"))
        if wanted and not current:
            try:
                actions.append(_apply_service(
                    "start", service,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
            except Exception as error:  # noqa: BLE001
                errors.append(str(error))
    return actions, errors


def start_marine(
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    """Select Marine + AIS and start voice using the opposite receiver."""
    with _LOCK:
        mission = mission_engine.get_mission_status()
        manager = receiver_manager.get_status()
        reservations = manager.get("canonical_reservations") or {}
        if mission.get("active_job") is not None or str(mission.get("phase") or "").upper() != "READY":
            raise RuntimeError("Traffic Voice kan niet starten tijdens een actieve missie")
        if reservations:
            raise RuntimeError("Traffic Voice kan niet starten terwijl een receiver is gereserveerd")

        existing_session = _load_session()
        if existing_session is not None:
            if bool((service_state(VOICE_SERVICE) or {}).get("active")):
                return {
                    "ok": True,
                    "mode": "marine_ais",
                    "message": "Marine Voice + AIS is al actief.",
                    "voice_receiver": existing_session.get("voice_receiver"),
                    "context_receiver": config.get_receiver_assignments().get("ais"),
                    "assignment_changed": False,
                    "before": _observe(service_state),
                    "after": _observe(service_state),
                    "service_actions": [],
                    "session_reused": True,
                    "receiver_authority": "receiver_manager",
                    "assignment_authority": "config/station.yaml:assignments",
                    "service_authority": "existing_dashboard_systemctl_path",
                }
            restore_actions, restore_errors = _restore(
                existing_session["previous_services"],
                existing_session["previous_assignments"],
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
            )
            if restore_errors:
                raise RuntimeError(
                    "Een eerdere Traffic Voice-sessie kon niet worden hersteld: "
                    + "; ".join(restore_errors)
                )
            _clear_session()

        if traffic_voice.get_receiver_settings()["open_squelch"]:
            traffic_voice.save_receiver_settings({"open_squelch": False})

        previous_assignments = config.get_receiver_assignments()
        voice_receiver = _other_receiver(previous_assignments.get("ais"))
        before = _observe(service_state)
        actions: list[dict[str, Any]] = []
        assignment_changed = previous_assignments.get("traffic_voice") != voice_receiver
        _write_session(
            before,
            previous_assignments,
            voice_receiver=voice_receiver,
        )

        try:
            if before[ADSB_SERVICE].get("active"):
                actions.append(_apply_service(
                    "stop", ADSB_SERVICE,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
            if not before[AIS_SERVICE].get("active"):
                actions.append(_apply_service(
                    "start", AIS_SERVICE,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
            if assignment_changed:
                if before[VOICE_SERVICE].get("active"):
                    actions.append(_apply_service(
                        "stop", VOICE_SERVICE,
                        service_action=service_action,
                        wait_for_service=wait_for_service,
                    ))
                config.set_plugin_assignments({"traffic_voice": voice_receiver})
            current_voice = service_state(VOICE_SERVICE)
            if not current_voice.get("active"):
                block = receiver_manager.service_action_block("traffic_voice", "start")
                if block is not None:
                    raise RuntimeError(block.get("message") or "Voice receiver is gereserveerd")
                actions.append(_apply_service(
                    "start", VOICE_SERVICE,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
        except Exception as error:  # noqa: BLE001 - transaction rollback
            restore_actions, restore_errors = _restore(
                before,
                previous_assignments,
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
            )
            if not restore_errors:
                _clear_session()
            raise RuntimeError(
                f"Marine Voice transactie mislukt: {error}; "
                + ("vorige toestand hersteld" if not restore_errors else "rollback: " + "; ".join(restore_errors))
            ) from error

        return {
            "ok": True,
            "mode": "marine_ais",
            "message": "Marine Voice + AIS is actief.",
            "voice_receiver": voice_receiver,
            "context_receiver": previous_assignments.get("ais"),
            "assignment_changed": assignment_changed,
            "before": before,
            "after": _observe(service_state),
            "service_actions": actions,
            "receiver_authority": "receiver_manager",
            "assignment_authority": "config/station.yaml:assignments",
            "service_authority": "existing_dashboard_systemctl_path",
        }


def stop(
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    """Stop voice and restore the exact topology captured by Start Marine."""
    with _LOCK:
        assignments = config.get_receiver_assignments()
        voice_receiver = receiver_registry.resolve_id(
            assignments.get("traffic_voice")
        )
        reservations = (
            receiver_manager.get_status().get("canonical_reservations") or {}
        )
        reservation = reservations.get(voice_receiver)
        if isinstance(reservation, dict):
            raise RuntimeError(
                "Traffic Voice wordt door een actieve receiver-handover beheerd; "
                "stop voice na afloop van de missie"
            )
        session = _load_session()
        before = _observe(service_state)
        actions: list[dict[str, Any]] = []
        if traffic_voice.get_receiver_settings()["open_squelch"]:
            traffic_voice.save_receiver_settings({"open_squelch": False})
        if before[VOICE_SERVICE].get("active"):
            actions.append(_apply_service(
                "stop", VOICE_SERVICE,
                service_action=service_action,
                wait_for_service=wait_for_service,
            ))
        restored = False
        if session is not None:
            restore_actions, restore_errors = _restore(
                session["previous_services"],
                session["previous_assignments"],
                service_state=service_state,
                service_action=service_action,
                wait_for_service=wait_for_service,
            )
            actions.extend(restore_actions)
            if restore_errors:
                raise RuntimeError(
                    "Marine Voice is gestopt, maar de eerdere servicestatus kon niet "
                    "volledig worden hersteld: " + "; ".join(restore_errors)
                )
            _clear_session()
            restored = True
        return {
            "ok": True,
            "mode": "marine_ais",
            "message": (
                "Marine Voice is gestopt; de eerdere AIS/ADS-B-status is hersteld."
                if restored else
                "Marine Voice is gestopt; er was geen eerdere sessiestatus om te herstellen."
            ),
            "before": before,
            "after": _observe(service_state),
            "service_actions": actions,
            "previous_state_restored": restored,
            "service_authority": "existing_dashboard_systemctl_path",
        }


def apply_receiver_settings(
    changes: dict[str, Any],
    *,
    service_state: ServiceState,
    service_action: ServiceAction,
    wait_for_service: ServiceWait,
) -> dict[str, Any]:
    """Apply receiver controls and restart only the existing voice service."""
    with _LOCK:
        assignments = config.get_receiver_assignments()
        voice_receiver = receiver_registry.resolve_id(assignments.get("traffic_voice"))
        reservations = receiver_manager.get_status().get("canonical_reservations") or {}
        if isinstance(reservations.get(voice_receiver), dict):
            raise RuntimeError(
                "Traffic Voice-instellingen kunnen niet wijzigen tijdens een actieve receiver-handover"
            )

        previous_document = config.load_traffic_voice()
        previous_settings = traffic_voice.get_receiver_settings(previous_document)
        normalized = traffic_voice.normalize_receiver_settings(
            changes,
            payload=previous_document,
        )
        before = _observe(service_state)
        was_running = bool(before[VOICE_SERVICE].get("active"))
        actions: list[dict[str, Any]] = []
        try:
            if was_running:
                actions.append(_apply_service(
                    "stop", VOICE_SERVICE,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
            applied = traffic_voice.save_receiver_settings(normalized)
            if was_running:
                actions.append(_apply_service(
                    "start", VOICE_SERVICE,
                    service_action=service_action,
                    wait_for_service=wait_for_service,
                ))
        except Exception as error:  # noqa: BLE001 - settings transaction rollback
            rollback_errors: list[str] = []
            try:
                config.save_traffic_voice(previous_document)
            except Exception as rollback_error:  # noqa: BLE001
                rollback_errors.append(f"config: {rollback_error}")
            if was_running and not bool((service_state(VOICE_SERVICE) or {}).get("active")):
                try:
                    actions.append(_apply_service(
                        "start", VOICE_SERVICE,
                        service_action=service_action,
                        wait_for_service=wait_for_service,
                    ))
                except Exception as rollback_error:  # noqa: BLE001
                    rollback_errors.append(f"service: {rollback_error}")
            detail = (
                "vorige instellingen hersteld"
                if not rollback_errors
                else "rollback onvolledig: " + "; ".join(rollback_errors)
            )
            raise RuntimeError(
                f"Traffic Voice-instellingen konden niet worden toegepast: {error}; {detail}"
            ) from error

        return {
            "ok": True,
            "mode": "marine_ais",
            "message": (
                "Traffic Voice-instellingen toegepast; Voice is opnieuw gestart."
                if was_running else
                "Traffic Voice-instellingen opgeslagen voor de volgende start."
            ),
            "before_settings": previous_settings,
            "settings": applied,
            "before": before,
            "after": _observe(service_state),
            "service_actions": actions,
            "configuration_authority": "config/traffic_voice.yaml",
            "service_authority": "existing_dashboard_systemctl_path",
        }
