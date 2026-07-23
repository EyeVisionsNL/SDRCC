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


_JOURNAL_VERSION = "0.43.0c4"
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
        "updated_at": None,
        "duration_ms": 0,
        "events": [{
            "event": "PLAN_CREATED",
            "timestamp": _now(),
            "source": str(source),
            "details": {},
        }],
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



_ALLOWED_EVENTS = {
    "PLAN_CREATED",
    "VALIDATED",
    "CONSUMED",
    "DELEGATED",
    "ACCEPTED",
    "STARTED",
    "FINISHED",
    "FAILED",
    "CANCELLED",
}


def append_event(
    execution_id: str,
    event: str,
    *,
    source: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append one observer event without controlling operational lifecycle."""
    wanted = str(execution_id).strip()
    normalized_event = str(event).strip().upper()
    if normalized_event not in _ALLOWED_EVENTS:
        raise ExecutionJournalError(f"onbekend journal-event: {event!r}")

    timestamp = _now()
    detail_snapshot = _normalize_mapping(details)

    with _lock:
        for index, current in enumerate(_entries):
            if current["execution_id"] != wanted:
                continue

            updated = deepcopy(current)
            updated["status"] = normalized_event
            updated["updated_at"] = timestamp
            updated.setdefault("events", []).append({
                "event": normalized_event,
                "timestamp": timestamp,
                "source": str(source),
                "details": detail_snapshot,
            })
            created = datetime.fromisoformat(updated["created_at"])
            changed = datetime.fromisoformat(timestamp)
            updated["duration_ms"] = max(
                0, int((changed - created).total_seconds() * 1000)
            )
            _entries[index] = updated
            return deepcopy(updated)

    return None



def append_event_once(
    execution_id: str,
    event: str,
    *,
    source: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Append an observer event only when it is not already present."""
    wanted = str(execution_id).strip()
    normalized_event = str(event).strip().upper()
    if normalized_event not in _ALLOWED_EVENTS:
        raise ExecutionJournalError(f"onbekend journal-event: {event!r}")

    with _lock:
        for current in _entries:
            if current["execution_id"] != wanted:
                continue
            if any(
                str(item.get("event") or "").upper() == normalized_event
                for item in current.get("events", [])
            ):
                return deepcopy(current)
            break

    return append_event(
        wanted,
        normalized_event,
        source=source,
        details=details,
    )

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
    offset: int = 0,
    plugin_id: str | None = None,
    status: str | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Return a filtered, paginated and API-safe journal snapshot."""
    safe_limit = max(1, min(int(limit), _HISTORY_LIMIT))
    safe_offset = max(0, int(offset))
    plugin_filter = str(plugin_id).strip().lower() if plugin_id else None
    status_filter = str(status).strip().upper() if status else None
    execution_filter = str(execution_id).strip() if execution_id else None

    with _lock:
        entries = deepcopy(_entries)

    if execution_filter:
        entries = [
            item for item in entries
            if str(item.get("execution_id") or "") == execution_filter
        ]
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

    terminal_statuses = {"FINISHED", "FAILED", "CANCELLED"}
    active_statuses = {"ACCEPTED", "STARTED"}
    filtered_count = len(entries)
    summary = {
        "total": filtered_count,
        "active": sum(
            1 for item in entries
            if str(item.get("status") or "").upper() in active_statuses
        ),
        "finished": sum(
            1 for item in entries
            if str(item.get("status") or "").upper() == "FINISHED"
        ),
        "failed": sum(
            1 for item in entries
            if str(item.get("status") or "").upper() == "FAILED"
        ),
        "cancelled": sum(
            1 for item in entries
            if str(item.get("status") or "").upper() == "CANCELLED"
        ),
        "pending": sum(
            1 for item in entries
            if str(item.get("status") or "").upper() not in terminal_statuses | active_statuses
        ),
    }

    page_entries = entries[safe_offset:safe_offset + safe_limit]
    return {
        "ok": True,
        "journal_version": _JOURNAL_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "read_only": True,
        "authority": "observer_only",
        "behavior_changed": False,
        "persistence": "memory_only",
        "history_limit": _HISTORY_LIMIT,
        "count": len(page_entries),
        "filtered_count": filtered_count,
        "limit": safe_limit,
        "offset": safe_offset,
        "has_more": safe_offset + len(page_entries) < filtered_count,
        "filters": {
            "execution_id": execution_filter,
            "plugin": plugin_filter,
            "status": status_filter,
        },
        "summary": summary,
        "latest": page_entries[0] if page_entries else None,
        "entries": page_entries,
        "generated_at": _now(),
    }


def reset_journal() -> None:
    """Testing helper that never touches operational SDRCC state."""
    with _lock:
        _entries.clear()
