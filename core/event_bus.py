#!/usr/bin/env python3

"""Thread-safe persistent event bus for SDRCC operator events."""

from __future__ import annotations

import fcntl
import json
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
EVENTS_FILE = STATE_DIR / "events.json"
LOCK_FILE = STATE_DIR / "events.lock"
MAX_EVENTS = 100
VALID_LEVELS = {"SYSTEM", "INFO", "SUCCESS", "WARNING", "ERROR"}

_lock = threading.RLock()
_events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_loaded = False
_recent_signatures: dict[str, tuple[float, str]] = {}


def _now_string() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_level(level: str | None) -> str:
    normalized = str(level or "INFO").strip().upper()
    return normalized if normalized in VALID_LEVELS else "INFO"


def _normalize_text(value: Any, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip()


@contextmanager
def _process_lock():
    """Serialize event-file access across SDRCC processes."""

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _reload_locked() -> None:
    global _loaded
    _events.clear()
    _loaded = False
    _load_locked()


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
        with _process_lock():
            _reload_locked()
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



def _domain_publish(
    category: str,
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
    dedup_key: str | None = None,
    cooldown_seconds: float = 0,
) -> dict[str, Any] | None:
    """Publish a normalized domain event with optional short-term deduplication."""

    normalized_data = dict(data or {})
    signature = json.dumps(
        {
            "level": _normalize_level(level),
            "title": _normalize_text(title),
            "detail": _normalize_text(detail),
            "data": normalized_data,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )

    if dedup_key and cooldown_seconds > 0:
        now = time.monotonic()
        with _lock:
            previous = _recent_signatures.get(dedup_key)
            if previous is not None:
                previous_time, previous_signature = previous
                if (
                    previous_signature == signature
                    and now - previous_time < float(cooldown_seconds)
                ):
                    return None
            _recent_signatures[dedup_key] = (now, signature)

    return publish_event(
        level,
        category,
        title,
        detail,
        data=normalized_data,
    )


def publish_scheduler(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _domain_publish(
        "SCHEDULER", level, title, detail, data=data
    )


def publish_mission(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _domain_publish(
        "MISSION", level, title, detail, data=data
    )


def publish_receiver(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _domain_publish(
        "RECEIVER", level, title, detail, data=data
    )


def publish_preflight(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
    dedup_key: str = "preflight-result",
    cooldown_seconds: float = 60,
) -> dict[str, Any] | None:
    return _domain_publish(
        "PREFLIGHT",
        level,
        title,
        detail,
        data=data,
        dedup_key=dedup_key,
        cooldown_seconds=cooldown_seconds,
    )


def publish_satdump(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _domain_publish(
        "SATDUMP", level, title, detail, data=data
    )


def publish_automation(
    level: str,
    title: str,
    detail: str | None = None,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _domain_publish(
        "AUTOMATION", level, title, detail, data=data
    )

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
        with _process_lock():
            _reload_locked()
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
        with _process_lock():
            _reload_locked()
            _events.clear()
            _save_locked()


def get_status() -> dict[str, Any]:
    with _lock:
        with _process_lock():
            _reload_locked()
            count = len(_events)
            latest = dict(_events[-1]) if _events else None

    return {
        "count": count,
        "limit": MAX_EVENTS,
        "latest": latest,
        "storage": str(EVENTS_FILE),
    }
