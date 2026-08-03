#!/usr/bin/env python3
"""Validated TLE inventory for the SDRCC mission-planning layer.

This module owns TLE parsing and status only. Network retrieval remains in
``core.downloader`` and orbital prediction remains in ``core.passes``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

TLE_DIR = Path(__file__).resolve().parent.parent / "data" / "tle"
TLE_FILE = TLE_DIR / "weather.tle"
ISS_TLE_FILE = TLE_DIR / "iss.tle"

SOURCE_NAME = "CelesTrak"
SOURCE_URL = "https://celestrak.org/NORAD/elements/gp.php"
CACHE_MAX_AGE_HOURS = 2.0
SOURCE_MAX_EPOCH_AGE_DAYS = 14.0

REQUIRED_WEATHER = {
    57166: "METEOR-M2 3",
    59051: "METEOR-M2 4",
}
REQUIRED_ISS = {25544: "ISS (ZARYA)"}
REQUIRED_CATALOGS = {**REQUIRED_WEATHER, **REQUIRED_ISS}


def _normalized_lines(text: str) -> list[str]:
    return [line.rstrip() for line in str(text or "").splitlines() if line.strip()]


def checksum_valid(line: str) -> bool:
    """Return whether one TLE element line has a valid NORAD checksum."""
    value = str(line).rstrip("\r\n")
    if len(value) < 69 or not value[68].isdigit():
        return False
    checksum = sum(int(char) for char in value[:68] if char.isdigit())
    checksum += value[:68].count("-")
    return checksum % 10 == int(value[68])


def _catalog_number(line: str) -> int:
    value = str(line)
    if len(value) < 7 or value[0] not in {"1", "2"}:
        raise ValueError("TLE element line has no valid line number")
    try:
        return int(value[2:7])
    except ValueError as exc:
        raise ValueError("TLE element line has no valid catalog number") from exc


def epoch_datetime(line1: str) -> datetime:
    """Parse the UTC element epoch from a validated line 1."""
    token = str(line1)[18:32].strip()
    if len(token) < 5:
        raise ValueError("TLE epoch is missing")
    try:
        short_year = int(token[:2])
        day_of_year = float(token[2:])
    except ValueError as exc:
        raise ValueError("TLE epoch is invalid") from exc
    year = 2000 + short_year if short_year < 57 else 1900 + short_year
    return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1.0)


def validate_block(
    name: str,
    line1: str,
    line2: str,
    *,
    expected_catalog: int | None = None,
) -> dict[str, Any]:
    """Validate and describe one three-line TLE block."""
    clean_name = str(name or "").strip()
    clean_line1 = str(line1 or "").rstrip()
    clean_line2 = str(line2 or "").rstrip()
    if not clean_name:
        raise ValueError("TLE satellite name is missing")
    if not clean_line1.startswith("1 ") or not clean_line2.startswith("2 "):
        raise ValueError(f"TLE block for {clean_name} has invalid line numbers")
    catalog1 = _catalog_number(clean_line1)
    catalog2 = _catalog_number(clean_line2)
    if catalog1 != catalog2:
        raise ValueError(f"TLE block for {clean_name} mixes catalog numbers")
    if expected_catalog is not None and catalog1 != int(expected_catalog):
        raise ValueError(
            f"TLE block for {clean_name} contains catalog {catalog1}, "
            f"expected {int(expected_catalog)}"
        )
    if not checksum_valid(clean_line1) or not checksum_valid(clean_line2):
        raise ValueError(f"TLE checksum failed for catalog {catalog1}")
    epoch = epoch_datetime(clean_line1)
    canonical = f"{clean_name}\n{clean_line1}\n{clean_line2}\n"
    return {
        "name": clean_name,
        "catalog_number": catalog1,
        "line1": clean_line1,
        "line2": clean_line2,
        "epoch": epoch,
        "epoch_iso": epoch.isoformat(),
        "sha256": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def parse_text(
    text: str,
    *,
    expected_catalogs: dict[int, str] | Iterable[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """Parse TLE text and require every requested catalog exactly once."""
    expected_names = (
        {int(key): str(value) for key, value in expected_catalogs.items()}
        if isinstance(expected_catalogs, dict)
        else {int(key): "" for key in (expected_catalogs or [])}
    )
    lines = _normalized_lines(text)
    blocks: dict[int, dict[str, Any]] = {}
    index = 0
    while index < len(lines):
        name = lines[index].strip()
        if index + 2 >= len(lines):
            raise ValueError("TLE response ends with an incomplete block")
        line1, line2 = lines[index + 1], lines[index + 2]
        block = validate_block(name, line1, line2)
        catalog = int(block["catalog_number"])
        if catalog in blocks:
            raise ValueError(f"TLE catalog {catalog} occurs more than once")
        if not expected_names or catalog in expected_names:
            canonical_name = expected_names.get(catalog) or block["name"]
            if canonical_name != block["name"]:
                block = validate_block(canonical_name, line1, line2, expected_catalog=catalog)
            blocks[catalog] = block
        index += 3

    missing = sorted(set(expected_names) - set(blocks))
    if missing:
        raise ValueError("Missing required TLE catalogs: " + ", ".join(map(str, missing)))
    if not blocks:
        raise ValueError("No valid TLE blocks found")
    return blocks


def load_file(
    path: Path,
    *,
    expected_catalogs: dict[int, str] | Iterable[int] | None = None,
) -> dict[int, dict[str, Any]]:
    if not Path(path).exists():
        raise FileNotFoundError(f"TLE file is missing: {path}")
    return parse_text(
        Path(path).read_text(encoding="utf-8"),
        expected_catalogs=expected_catalogs,
    )


def serialize_blocks(blocks: Iterable[dict[str, Any]]) -> str:
    values = []
    for block in blocks:
        validated = validate_block(
            block["name"],
            block["line1"],
            block["line2"],
            expected_catalog=int(block["catalog_number"]),
        )
        values.extend((validated["name"], validated["line1"], validated["line2"]))
    return "\n".join(values) + "\n"


def file_status(
    path: Path,
    *,
    expected_catalogs: dict[int, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    target = Path(path)
    base = {
        "file": str(target),
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "cache_max_age_hours": CACHE_MAX_AGE_HOURS,
        "required_catalogs": sorted(int(value) for value in expected_catalogs),
    }
    if not target.exists():
        return {
            **base,
            "present": False,
            "valid": False,
            "stale": True,
            "age_hours": None,
            "error": "TLE file is missing",
            "catalogs": [],
        }
    modified = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
    age_hours = max(0.0, (current - modified).total_seconds() / 3600.0)
    try:
        blocks = load_file(target, expected_catalogs=expected_catalogs)
        catalogs = []
        for catalog in sorted(blocks):
            block = blocks[catalog]
            epoch_age_hours = (current - block["epoch"]).total_seconds() / 3600.0
            catalogs.append({
                "catalog_number": catalog,
                "name": block["name"],
                "epoch": block["epoch_iso"],
                "epoch_age_hours": round(epoch_age_hours, 1),
                "sha256": block["sha256"],
            })
        epoch_stale = any(
            item["epoch_age_hours"] > SOURCE_MAX_EPOCH_AGE_DAYS * 24.0
            for item in catalogs
        )
        return {
            **base,
            "present": True,
            "valid": True,
            "stale": age_hours > CACHE_MAX_AGE_HOURS or epoch_stale,
            "age_hours": round(age_hours, 1),
            "updated_at": modified.isoformat(),
            "error": None,
            "catalogs": catalogs,
            "sha256": sha256(target.read_bytes()).hexdigest(),
        }
    except (OSError, ValueError) as error:
        return {
            **base,
            "present": True,
            "valid": False,
            "stale": True,
            "age_hours": round(age_hours, 1),
            "updated_at": modified.isoformat(),
            "error": str(error),
            "catalogs": [],
        }


def get_status() -> dict[str, Any]:
    weather = file_status(TLE_FILE, expected_catalogs=REQUIRED_WEATHER)
    iss = file_status(ISS_TLE_FILE, expected_catalogs=REQUIRED_ISS)
    valid = bool(weather["valid"] and iss["valid"])
    stale = bool(weather["stale"] or iss["stale"])
    return {
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "cache_max_age_hours": CACHE_MAX_AGE_HOURS,
        "valid": valid,
        "stale": stale,
        "state": "INVALID" if not valid else ("STALE" if stale else "CURRENT"),
        "weather": weather,
        "iss_voice": iss,
    }


def exists() -> bool:
    """Backward-compatible Weather TLE presence check used by preflight."""
    return bool(file_status(TLE_FILE, expected_catalogs=REQUIRED_WEATHER)["valid"])


def last_update() -> datetime | None:
    if not TLE_FILE.exists():
        return None
    return datetime.fromtimestamp(TLE_FILE.stat().st_mtime)


def age_hours() -> float | None:
    value = file_status(TLE_FILE, expected_catalogs=REQUIRED_WEATHER)["age_hours"]
    return float(value) if value is not None else None


def status() -> None:
    inventory = get_status()
    print("TLE Database")
    print("----------------")
    print("Source :", inventory["source"])
    print("State  :", inventory["state"])
    for label, key in (("Weather", "weather"), ("ISS", "iss_voice")):
        item = inventory[key]
        print(
            f"{label:<7}: "
            + (f"valid, age {item['age_hours']} hours" if item["valid"] else item["error"])
        )
