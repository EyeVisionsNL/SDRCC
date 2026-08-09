"""Read-only log source projection for the SDRCC dashboard.

This module does not control services and never accepts a systemd unit name
from the caller.  Public source IDs are resolved through the fixed allowlist
below before a local file or journal is read.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SDRCC_LOG_FILE = PROJECT_ROOT / "logs" / "sdrcc.log"

DEFAULT_LIMIT = 240
MIN_LIMIT = 20
MAX_LIMIT = 500

SOURCE_DEFINITIONS = {
    "sdrcc": {
        "label": "SDRCC",
        "kind": "file",
        "path": SDRCC_LOG_FILE,
    },
    "ais": {
        "label": "AIS",
        "kind": "journal",
        "unit": "ais-catcher.service",
    },
    "adsb": {
        "label": "ADS-B",
        "kind": "journal",
        "unit": "readsb.service",
    },
}


def available_sources() -> list[dict[str, str]]:
    """Return public source metadata without paths or systemd unit details."""

    return [
        {"id": source_id, "label": str(definition["label"])}
        for source_id, definition in SOURCE_DEFINITIONS.items()
    ]


def _normalize_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    return max(MIN_LIMIT, min(MAX_LIMIT, limit))


def _result(source_id: str, limit: int, lines: list[str], error: str | None = None) -> dict[str, Any]:
    return {
        "ok": error is None,
        "authority": "observer_only",
        "source": source_id,
        "label": str(SOURCE_DEFINITIONS[source_id]["label"]),
        "limit": limit,
        "count": len(lines),
        "lines": lines,
        "error": error,
        "sources": available_sources(),
    }


def _read_file(source_id: str, definition: dict[str, Any], limit: int) -> dict[str, Any]:
    path = Path(definition["path"])
    if not path.exists():
        return _result(source_id, limit, [], "Log file does not exist yet.")

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return _result(source_id, limit, [], f"Unable to read log file: {error}")
    return _result(source_id, limit, lines[-limit:])


def _read_journal(source_id: str, definition: dict[str, Any], limit: int) -> dict[str, Any]:
    command = [
        "journalctl",
        "-u",
        str(definition["unit"]),
        "-n",
        str(limit),
        "--no-pager",
        "-o",
        "short-iso",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=4.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return _result(source_id, limit, [], f"Unable to read service journal: {error}")

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "journalctl failed").strip()
        return _result(source_id, limit, [], detail)

    return _result(source_id, limit, (completed.stdout or "").splitlines()[-limit:])


def read_source(source_id: Any, limit: Any = DEFAULT_LIMIT) -> dict[str, Any]:
    """Read one allowlisted source and return a stable observer-only payload."""

    normalized_source = str(source_id or "sdrcc").strip().lower()
    if normalized_source not in SOURCE_DEFINITIONS:
        return {
            "ok": False,
            "authority": "observer_only",
            "source": normalized_source,
            "label": "Unknown",
            "limit": _normalize_limit(limit),
            "count": 0,
            "lines": [],
            "error": "Unknown log source.",
            "sources": available_sources(),
        }

    normalized_limit = _normalize_limit(limit)
    definition = SOURCE_DEFINITIONS[normalized_source]
    if definition["kind"] == "file":
        return _read_file(normalized_source, definition, normalized_limit)
    return _read_journal(normalized_source, definition, normalized_limit)
