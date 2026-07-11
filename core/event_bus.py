#!/usr/bin/env python3

"""Thread-safe persistent event bus for SDRCC operator events."""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
EVENTS_FILE = STATE_DIR / "events.json"
MAX_EVENTS = 100
VALID_LEVELS = {"SYSTEM", "INFO", "SUCCESS", "WARNING", "ERROR"}

_lock = threading.RLock()
_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_loaded = False


def _now_string() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_level(level: str | None) -> str:
    normalized = str(level or "INFO").strip().upper()
    return normalized if normalized in VALID_LEVELS else "INFO"


def _normalize_text(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip()


def _load_locked() -> None:
    global _loaded

    if _loaded:
        return

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        raw = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = []
    except (OSError, json.JSONDecodeError):
        raw = []

    if isinstance(raw, dict):
        raw = raw.get("events", [])

    if isinstance(raw, list):
        for item in raw[-MAX_EVENTS:]:
            if not isinstance(item, dict):
                continue
            event = {
                "id": _normalize_text(item.get("id"), fallback=uuid.uuid4().hex),
                "time": _normalize_text(item.get("time"), fallback=_now_string()),
                "level": _normalize_level(item.get("level")),
                "category": _normalize_text(item.get("category"), fallback="SYSTEM").upper(),
                "title": _normalize_text(item.get("title"), fallback="Gebeurtenis"),
                "detail": _normalize_text(item.get("detail")),
                "data": item.get("data") if isinstance(item.get("data"), dict) else {},
            }
            _events.append(event)

    _loaded = True


def _save_locked() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": _now_string(),
        "events": list(_events),
    }

    temporary = EVENTS_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, EVENTS_FILE)


def publish_event(
    level: str,
    category: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish and persist one operator event."""

    event = {
        "id": uuid.uuid4().hex,
        "time": _now_string(),
        "level": _normalize_level(level),
        "category": _normalize_text(category, fallback="SYSTEM").upper(),
        "title": _normalize_text(title, fallback="Gebeurtenis"),
        "detail": _normalize_text(detail),
        "data": dict(data or {}),
    }

    with _lock:
        _load_locked()
        _events.append(event)
        _save_locked()

    return dict(event)


def publish_system(category: str, title: str, detail: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return publish_event("SYSTEM", category, title, detail, **kwargs)


def publish_info(category: str, title: str, detail: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return publish_event("INFO", category, title, detail, **kwargs)


def publish_success(category: str, title: str, detail: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return publish_event("SUCCESS", category, title, detail, **kwargs)


def publish_warning(category: str, title: str, detail: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return publish_event("WARNING", category, title, detail, **kwargs)


def publish_error(category: str, title: str, detail: str | None = None, **kwargs: Any) -> dict[str, Any]:
    return publish_event("ERROR", category, title, detail, **kwargs)


def get_events(
    *,
    limit: int = 100,
    levels: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
    newest_first: bool = True,
) -> list[dict[str, Any]]:
    """Return filtered copies of the most recent events."""

    try:
        safe_limit = max(1, min(int(limit), MAX_EVENTS))
    except (TypeError, ValueError):
        safe_limit = MAX_EVENTS

    normalized_levels = {
        _normalize_level(item) for item in (levels or []) if str(item).strip()
    }
    normalized_categories = {
        str(item).strip().upper() for item in (categories or []) if str(item).strip()
    }

    with _lock:
        _load_locked()
        items = list(_events)

    if normalized_levels:
        items = [item for item in items if item["level"] in normalized_levels]
    if normalized_categories:
        items = [item for item in items if item["category"] in normalized_categories]

    if newest_first:
        items.reverse()

    return [dict(item) for item in items[:safe_limit]]


def clear_events() -> None:
    """Clear all persisted events."""

    with _lock:
        _load_locked()
        _events.clear()
        _save_locked()


def get_status() -> dict[str, Any]:
    with _lock:
        _load_locked()
        count = len(_events)
        latest = dict(_events[-1]) if _events else None

    return {
        "count": count,
        "limit": MAX_EVENTS,
        "latest": latest,
        "storage": str(EVENTS_FILE),
    }
