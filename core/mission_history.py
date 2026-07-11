from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import json

try:
    import fcntl
except ImportError:  # pragma: no cover - SDRCC draait op Linux
    fcntl = None


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
HISTORY_FILE = STATE_DIR / "mission_history.json"
LOCK_FILE = STATE_DIR / "mission_history.lock"
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


def _normalise_limit(limit: Any) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _read_history_unlocked() -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []

    try:
        payload = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def load_history() -> list[dict[str, Any]]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_SH)
        try:
            return _read_history_unlocked()
        finally:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _matches_text(mission: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(
        str(mission.get(key) or "")
        for key in (
            "mission_id",
            "satellite",
            "receiver",
            "receiver_serial",
            "pipeline",
            "result",
            "detail",
            "output_path",
        )
    ).lower()
    return query.lower() in haystack


def get_missions(
    *,
    limit: int = DEFAULT_LIMIT,
    result: Optional[str] = None,
    satellite: Optional[str] = None,
    query: Optional[str] = None,
) -> list[dict[str, Any]]:
    missions = load_history()
    result_filter = str(result or "").strip().upper()
    satellite_filter = str(satellite or "").strip().lower()
    text_filter = str(query or "").strip()

    filtered = []
    for mission in missions:
        if result_filter and str(mission.get("result") or "").upper() != result_filter:
            continue
        if satellite_filter and satellite_filter not in str(mission.get("satellite") or "").lower():
            continue
        if not _matches_text(mission, text_filter):
            continue
        filtered.append(mission)

    return filtered[:_normalise_limit(limit)]


def get_mission(mission_id: str) -> Optional[dict[str, Any]]:
    wanted = str(mission_id or "").strip()
    if not wanted:
        return None
    for mission in load_history():
        if str(mission.get("mission_id") or "") == wanted:
            return mission
    return None


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_statistics(missions: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    rows = load_history() if missions is None else missions
    total = len(rows)
    result_counts = {
        "SUCCESS": 0,
        "NO SYNC": 0,
        "NO SIGNAL": 0,
        "FAILED": 0,
        "CANCELLED": 0,
        "OTHER": 0,
    }

    total_images = 0
    total_frames = 0
    total_cadu_bytes = 0
    durations: list[float] = []
    snr_values: list[float] = []

    for mission in rows:
        result = str(mission.get("result") or "OTHER").upper()
        if result not in result_counts:
            result = "OTHER"
        result_counts[result] += 1

        total_images += int(_as_number(mission.get("image_count"), 0))
        total_frames += int(_as_number(mission.get("frames"), 0))
        total_cadu_bytes += int(_as_number(mission.get("cadu_bytes"), 0))

        if mission.get("duration_seconds") is not None:
            durations.append(_as_number(mission.get("duration_seconds")))
        if mission.get("peak_snr_db") is not None:
            snr_values.append(_as_number(mission.get("peak_snr_db")))

    completed = total - result_counts["CANCELLED"]
    success_rate = (
        round((result_counts["SUCCESS"] / completed) * 100, 1)
        if completed > 0
        else 0.0
    )

    return {
        "total": total,
        "completed": completed,
        "success": result_counts["SUCCESS"],
        "success_rate": success_rate,
        "result_counts": result_counts,
        "total_images": total_images,
        "total_frames": total_frames,
        "total_cadu_bytes": total_cadu_bytes,
        "average_duration_seconds": (
            round(sum(durations) / len(durations), 1) if durations else None
        ),
        "best_peak_snr_db": max(snr_values) if snr_values else None,
        "latest_mission_at": (
            rows[0].get("ended_at") or rows[0].get("created_at") if rows else None
        ),
    }


def get_history_payload(
    *,
    limit: int = DEFAULT_LIMIT,
    result: Optional[str] = None,
    satellite: Optional[str] = None,
    query: Optional[str] = None,
) -> dict[str, Any]:
    all_missions = load_history()
    missions = get_missions(
        limit=limit,
        result=result,
        satellite=satellite,
        query=query,
    )
    return {
        "ok": True,
        "count": len(missions),
        "total": len(all_missions),
        "missions": missions,
        "statistics": get_statistics(all_missions),
        "filters": {
            "result": str(result or ""),
            "satellite": str(satellite or ""),
            "query": str(query or ""),
            "limit": _normalise_limit(limit),
        },
    }
