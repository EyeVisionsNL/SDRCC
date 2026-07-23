#!/usr/bin/env python3
"""Observer-only in-memory journal for SDRCC Execution Plans.

The journal records defensive snapshots of descriptive plans. It never starts
services, launches decoders, changes receiver state or owns mission lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock
from typing import Any, Mapping
from uuid import uuid4


_JOURNAL_VERSION = "0.43.0c1"
_SCHEMA_VERSION = 1
_HISTORY_LIMIT = 250
_lock = Lock()
_entries: list[dict[str, Any]] = []


class ExecutionJournalError(RuntimeError):
    """Raised when journal input violates the observer-only contract."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _normalize_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    return deepcopy(dict(value))


def _validate_plan(plan: Mapping[str, Any]) -> None:
    if not str(plan.get("plugin_id") or "").strip():
        raise ExecutionJournalError("plugin_id ontbreekt")
    if plan.get("read_only") is not True:
        raise ExecutionJournalError("alleen read-only Execution Plans zijn toegestaan")
    if plan.get("executable") is not False:
        raise ExecutionJournalError("executable plan kan niet observer-only worden gejournaled")


def create_entry(
    plan: Mapping[str, Any],
    *,
    request: Mapping[str, Any] | None = None,
    source: str = "execution_factory",
) -> dict[str, Any]:
    """Record one immutable defensive plan snapshot and return its entry."""
    plan_snapshot = _normalize_mapping(plan)
    request_snapshot = _normalize_mapping(request)
    _validate_plan(plan_snapshot)

    entry = {
        "execution_id": str(uuid4()),
        "journal_version": _JOURNAL_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "created_at": _now(),
        "status": "PLAN_CREATED",
        "source": str(source),
        "authority": "observer_only",
        "read_only": True,
        "behavior_changed": False,
        "plugin_id": str(plan_snapshot["plugin_id"]),
        "adapter_type": plan_snapshot.get("adapter_type"),
        "executor_type": plan_snapshot.get("executor_type"),
        "request": request_snapshot,
        "plan": plan_snapshot,
    }

    with _lock:
        _entries.insert(0, deepcopy(entry))
        del _entries[_HISTORY_LIMIT:]

    return deepcopy(entry)


def get_entry(execution_id: str) -> dict[str, Any] | None:
    """Return one defensive entry copy by execution ID."""
    wanted = str(execution_id).strip()
    with _lock:
        for entry in _entries:
            if entry["execution_id"] == wanted:
                return deepcopy(entry)
    return None


def get_snapshot(
    *,
    limit: int = 100,
    plugin_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Return a filtered API-safe journal snapshot."""
    safe_limit = max(1, min(int(limit), _HISTORY_LIMIT))
    plugin_filter = str(plugin_id).strip().lower() if plugin_id else None
    status_filter = str(status).strip().upper() if status else None

    with _lock:
        entries = deepcopy(_entries)

    if plugin_filter:
        entries = [
            item for item in entries
            if str(item.get("plugin_id") or "").lower() == plugin_filter
        ]
    if status_filter:
        entries = [
            item for item in entries
            if str(item.get("status") or "").upper() == status_filter
        ]

    entries = entries[:safe_limit]
    return {
        "ok": True,
        "journal_version": _JOURNAL_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "read_only": True,
        "authority": "observer_only",
        "behavior_changed": False,
        "persistence": "memory_only",
        "history_limit": _HISTORY_LIMIT,
        "count": len(entries),
        "latest": entries[0] if entries else None,
        "entries": entries,
        "generated_at": _now(),
    }


def reset_journal() -> None:
    """Testing helper that never touches operational SDRCC state."""
    with _lock:
        _entries.clear()
