from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import json
import os
import re
import shutil

from core import mission_result

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
RECORDINGS_DIR = PROJECT_ROOT / "data" / "recordings"
MISSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


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
    return [
        mission_result.normalize_history_mission(item)
        for item in payload
        if isinstance(item, dict)
    ]


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


def _average(values: list[float], digits: int = 1) -> Optional[float]:
    return round(sum(values) / len(values), digits) if values else None


def _group_key(value: Any, fallback: str = "UNKNOWN") -> str:
    text = str(value or "").strip()
    return text or fallback


def _build_group_statistics(
    rows: list[dict[str, Any]],
    key_name: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for mission in rows:
        key = _group_key(mission.get(key_name))
        grouped.setdefault(key, []).append(mission)

    result: list[dict[str, Any]] = []
    for name, missions in grouped.items():
        completed = [
            mission for mission in missions
            if str(mission.get("result") or "").upper() != "CANCELLED"
        ]
        successes = [
            mission for mission in completed
            if str(mission.get("result") or "").upper() == "SUCCESS"
        ]
        snr_values = [
            _as_number(mission.get("peak_snr_db"))
            for mission in missions
            if mission.get("peak_snr_db") is not None
        ]
        elevation_values = [
            _as_number(mission.get("max_elevation"))
            for mission in missions
            if mission.get("max_elevation") is not None
        ]
        quality_values = [
            _as_number(mission.get("quality_score"))
            for mission in missions
            if mission.get("quality_score") is not None
        ]
        image_values = [
            _as_number(mission.get("image_count"))
            for mission in missions
        ]

        result.append({
            "name": name,
            "missions": len(missions),
            "completed": len(completed),
            "success": len(successes),
            "success_rate": (
                round((len(successes) / len(completed)) * 100, 1)
                if completed else 0.0
            ),
            "average_peak_snr_db": _average(snr_values, 2),
            "best_peak_snr_db": max(snr_values) if snr_values else None,
            "average_max_elevation": _average(elevation_values, 1),
            "average_quality_score": _average(quality_values, 1),
            "average_images": _average(image_values, 1),
            "total_images": int(sum(image_values)),
        })

    return sorted(
        result,
        key=lambda item: (-int(item["missions"]), str(item["name"]).lower()),
    )


def get_statistics(missions: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    rows = load_history() if missions is None else missions
    total = len(rows)
    result_counts = {
        "SUCCESS": 0,
        "NO IMAGES": 0,
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
    elevation_values: list[float] = []
    quality_values: list[float] = []
    quality_grade_counts: dict[str, int] = {}

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
        if mission.get("max_elevation") is not None:
            elevation_values.append(_as_number(mission.get("max_elevation")))
        if mission.get("quality_score") is not None:
            quality_values.append(_as_number(mission.get("quality_score")))

        grade = _group_key(mission.get("quality_grade"), "UNRATED").upper()
        quality_grade_counts[grade] = quality_grade_counts.get(grade, 0) + 1

    completed = total - result_counts["CANCELLED"]
    success_rate = (
        round((result_counts["SUCCESS"] / completed) * 100, 1)
        if completed > 0
        else 0.0
    )

    return {
        "schema_version": 2,
        "total": total,
        "completed": completed,
        "success": result_counts["SUCCESS"],
        "success_rate": success_rate,
        "result_counts": result_counts,
        "quality_grade_counts": dict(sorted(quality_grade_counts.items())),
        "total_images": total_images,
        "total_frames": total_frames,
        "total_cadu_bytes": total_cadu_bytes,
        "average_duration_seconds": _average(durations, 1),
        "average_peak_snr_db": _average(snr_values, 2),
        "best_peak_snr_db": max(snr_values) if snr_values else None,
        "average_max_elevation": _average(elevation_values, 1),
        "average_quality_score": _average(quality_values, 1),
        "receiver_statistics": _build_group_statistics(rows, "receiver"),
        "satellite_statistics": _build_group_statistics(rows, "satellite"),
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


def _write_history_unlocked(missions: list[dict[str, Any]]) -> None:
    """Schrijf Mission History atomair weg terwijl de caller de exclusieve lock bezit."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_FILE.with_suffix(".json.tmp")
    payload = json.dumps(missions, ensure_ascii=False, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, HISTORY_FILE)


def _safe_output_directory(mission: dict[str, Any]) -> tuple[Optional[Path], Optional[str]]:
    """Bepaal of de geregistreerde outputmap veilig verwijderd mag worden.

    Oude, geannuleerde en testmissies kunnen een tijdelijke output_path buiten
    data/recordings bevatten. Zo'n pad mag nooit automatisch worden verwijderd,
    maar de Mission History-entry zelf moet wel handmatig verwijderbaar blijven.
    """
    output_value = str(mission.get("output_path") or "").strip()
    if not output_value:
        return None, None

    root = RECORDINGS_DIR.resolve()
    candidate = Path(output_value).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "Outputmap ligt buiten data/recordings en is veilig behouden"

    if candidate == root:
        return None, "Hoofdmap data/recordings is veilig behouden"
    return candidate, None


def delete_mission(mission_id: str) -> dict[str, Any]:
    """Verwijder één afgesloten missie en de bijbehorende outputmap veilig."""
    wanted = str(mission_id or "").strip()
    if not MISSION_ID_PATTERN.fullmatch(wanted):
        raise ValueError("Ongeldige mission-ID")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+", encoding="utf-8") as lock_handle:
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        try:
            missions = _read_history_unlocked()
            mission = next(
                (item for item in missions if str(item.get("mission_id") or "") == wanted),
                None,
            )
            if mission is None:
                raise LookupError("Missie niet gevonden")

            output_directory, output_warning = _safe_output_directory(mission)
            directory_removed = False
            if output_directory is not None and output_directory.exists():
                if not output_directory.is_dir():
                    raise ValueError("De geregistreerde outputlocatie is geen map")
                shutil.rmtree(output_directory)
                directory_removed = True

            remaining = [
                item for item in missions
                if str(item.get("mission_id") or "") != wanted
            ]
            _write_history_unlocked(remaining)

            return {
                "ok": True,
                "deleted": wanted,
                "satellite": mission.get("satellite"),
                "output_path": str(output_directory) if output_directory else None,
                "directory_removed": directory_removed,
                "output_warning": output_warning,
                "remaining": len(remaining),
            }
        finally:
            if fcntl is not None:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
