#!/usr/bin/env python3
"""Read-only consumers for SDRCC Execution Plans.

This module validates and records plan consumption. It never starts services,
launches SatDump, changes receiver state or controls mission lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock
from typing import Any, Mapping

from core import execution_factory


_CONSUMER_VERSION = "0.43.0b2"
_HISTORY_LIMIT = 100
_lock = Lock()
_history: list[dict[str, Any]] = []


class ExecutionPlanConsumerError(RuntimeError):
    """Raised when a plan cannot be consumed as descriptive metadata."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_context(
    context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if context is None:
        return {}
    return deepcopy(dict(context))


def _validate_plan(plan: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    if not plan.get("plugin_id"):
        errors.append("plugin_id ontbreekt")
    if not plan.get("adapter_type"):
        errors.append("adapter_type ontbreekt")
    if plan.get("read_only") is not True:
        errors.append("plan is niet read-only")
    if plan.get("foundation_only") is not True:
        errors.append("plan is niet foundation-only")
    if plan.get("executable") is not False:
        errors.append("plan is onverwacht executable")
    if plan.get("metadata_valid") is not True:
        errors.append("planmetadata is ongeldig")

    validation_errors = plan.get("validation_errors") or []
    for error in validation_errors:
        errors.append(str(error))

    return errors


def consume_plan(
    plugin_id: str,
    context: Mapping[str, Any] | None = None,
    *,
    consumer: str,
    purpose: str,
) -> dict[str, Any]:
    """Build, validate and record a read-only plan-consumption event."""
    normalized_context = _normalize_context(context)
    plan = execution_factory.build_plan(plugin_id, normalized_context)
    errors = _validate_plan(plan)

    record = {
        "ok": not errors,
        "consumer_version": _CONSUMER_VERSION,
        "consumer": str(consumer),
        "purpose": str(purpose),
        "plugin_id": str(plugin_id),
        "consumed_at": _now(),
        "read_only": True,
        "validation_only": True,
        "behavior_changed": False,
        "errors": errors,
        "context": normalized_context,
        "plan": deepcopy(plan),
    }

    with _lock:
        _history.insert(0, deepcopy(record))
        del _history[_HISTORY_LIMIT:]

    return record


def consume_weather_mission(
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return consume_plan(
        "weather",
        context,
        consumer="mission_engine",
        purpose="mission_creation_validation",
    )



def delegate_service_action(
    plugin_id: str,
    action: str,
) -> dict[str, Any]:
    """Resolve one service target from a read-only Execution Plan.

    This function delegates target selection only. It never invokes systemctl,
    changes service state or assumes lifecycle authority.
    """
    normalized_action = str(action).strip().lower()
    record = consume_plan(
        plugin_id,
        {
            "action": normalized_action,
        },
        consumer="dashboard_service_action",
        purpose="service_target_delegation",
    )

    targets = tuple(str(item).strip() for item in (
        record["plan"].get("targets") or ()
    ) if str(item).strip())

    record.update({
        "delegation_active": True,
        "delegation_scope": "service_target_only",
        "operation_authority": "existing_dashboard_systemctl_path",
        "delegated_target": targets[0] if len(targets) == 1 else None,
        "delegated_action": normalized_action,
        "target_count": len(targets),
    })

    if normalized_action not in {"start", "stop", "restart"}:
        record["ok"] = False
        record["errors"].append(
            f"niet-ondersteunde serviceactie: {normalized_action!r}"
        )

    if len(targets) != 1:
        record["ok"] = False
        record["errors"].append(
            "serviceplan moet exact één target bevatten; "
            f"ontvangen: {list(targets)!r}"
        )

    with _lock:
        if _history:
            _history[0] = deepcopy(record)

    return record

def consume_service_action(
    plugin_id: str,
    service_name: str,
    action: str,
) -> dict[str, Any]:
    record = consume_plan(
        plugin_id,
        {
            "service_name": service_name,
            "action": action,
        },
        consumer="dashboard_service_action",
        purpose="service_action_validation",
    )

    targets = tuple(record["plan"].get("targets") or ())
    target_matches = service_name in targets
    record["target_matches"] = target_matches

    if not target_matches:
        record["ok"] = False
        record["errors"].append(
            f"service {service_name!r} staat niet in plan targets {list(targets)!r}"
        )

    with _lock:
        if _history:
            _history[0] = deepcopy(record)

    return record


def get_snapshot() -> dict[str, Any]:
    with _lock:
        history = deepcopy(_history)

    return {
        "ok": all(item.get("ok", False) for item in history),
        "consumer_version": _CONSUMER_VERSION,
        "read_only": True,
        "validation_only": True,
        "behavior_changed": False,
        "authority": "observer_only",
        "delegation_active": True,
        "delegation_scope": "service_target_only",
        "operation_authority": "existing_dashboard_systemctl_path",
        "history_count": len(history),
        "latest": history[0] if history else None,
        "history": history,
    }


def reset_history() -> None:
    """Testing helper. Does not touch operational SDRCC state."""
    with _lock:
        _history.clear()
