#!/usr/bin/env python3
"""Validated and fail-safe CelesTrak updates for the required SDRCC TLEs."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

import requests

from core import tle

TLE_DIR = tle.TLE_DIR
TLE_FILE = tle.TLE_FILE
ISS_TLE_FILE = tle.ISS_TLE_FILE
TLE_DIR.mkdir(parents=True, exist_ok=True)

CATALOG_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={catalog}&FORMAT=TLE"
TLE_URL = CATALOG_URL.format(catalog=57166)
ISS_TLE_URL = CATALOG_URL.format(catalog=25544)


def _download_catalog(catalog: int, canonical_name: str) -> dict[str, Any]:
    response = requests.get(CATALOG_URL.format(catalog=int(catalog)), timeout=20)
    response.raise_for_status()
    blocks = tle.parse_text(
        response.text,
        expected_catalogs={int(catalog): canonical_name},
    )
    block = blocks[int(catalog)]
    now = datetime.now(timezone.utc)
    epoch_age_days = (now - block["epoch"]).total_seconds() / 86400.0
    if epoch_age_days > tle.SOURCE_MAX_EPOCH_AGE_DAYS:
        raise ValueError(
            f"CelesTrak returned catalog {catalog} with an epoch "
            f"{epoch_age_days:.1f} days old"
        )
    if epoch_age_days < -1.0:
        raise ValueError(f"CelesTrak returned catalog {catalog} with a future epoch")
    return block


def _write_temp(path: Path, content: str) -> Path:
    temp = path.with_suffix(path.suffix + ".v0540d.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists():
        os.chmod(temp, path.stat().st_mode & 0o777)
    return temp


def _restore_bytes(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    temp = path.with_suffix(path.suffix + ".restore.tmp")
    temp.write_bytes(previous)
    temp.replace(path)


def _replace_transaction(weather_text: str, iss_text: str) -> None:
    """Replace both validated inventories as one recoverable transaction."""
    TLE_DIR.mkdir(parents=True, exist_ok=True)
    previous_weather = TLE_FILE.read_bytes() if TLE_FILE.exists() else None
    previous_iss = ISS_TLE_FILE.read_bytes() if ISS_TLE_FILE.exists() else None
    weather_temp = _write_temp(TLE_FILE, weather_text)
    iss_temp = _write_temp(ISS_TLE_FILE, iss_text)
    try:
        weather_temp.replace(TLE_FILE)
        iss_temp.replace(ISS_TLE_FILE)
        directory_fd = os.open(TLE_DIR, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        _restore_bytes(TLE_FILE, previous_weather)
        _restore_bytes(ISS_TLE_FILE, previous_iss)
        raise
    finally:
        weather_temp.unlink(missing_ok=True)
        iss_temp.unlink(missing_ok=True)


def refresh_required_tles(
    *,
    force: bool = False,
    max_age_hours: float = tle.CACHE_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """Refresh the three required catalogs, preserving valid files on failure."""
    before = tle.get_status()
    cache_current = bool(
        before["valid"]
        and not before["stale"]
        and all(
            float(before[key].get("age_hours") or 0.0) <= float(max_age_hours)
            for key in ("weather", "iss_voice")
        )
    )
    if cache_current and not force:
        return {
            "ok": True,
            "updated": False,
            "preserved": True,
            "reason": "cache_current",
            "message": "TLE cache is current; planning recalculated from the validated cache.",
            "status": before,
        }

    try:
        downloaded = {
            catalog: _download_catalog(catalog, name)
            for catalog, name in tle.REQUIRED_CATALOGS.items()
        }
        weather_text = tle.serialize_blocks(
            downloaded[catalog] for catalog in tle.REQUIRED_WEATHER
        )
        iss_text = tle.serialize_blocks(
            downloaded[catalog] for catalog in tle.REQUIRED_ISS
        )
        # Validate complete payloads before either live file is replaced.
        tle.parse_text(weather_text, expected_catalogs=tle.REQUIRED_WEATHER)
        tle.parse_text(iss_text, expected_catalogs=tle.REQUIRED_ISS)
        _replace_transaction(weather_text, iss_text)
        after = tle.get_status()
        if not after["valid"]:
            raise RuntimeError("TLE transaction completed but post-write validation failed")
        return {
            "ok": True,
            "updated": True,
            "preserved": False,
            "reason": "downloaded",
            "message": "ISS and METEOR TLEs updated from CelesTrak and validated.",
            "status": after,
        }
    except Exception as error:
        after = tle.get_status()
        return {
            "ok": False,
            "updated": False,
            "preserved": bool(after["valid"]),
            "reason": "download_failed",
            "message": (
                "TLE update failed; the last valid TLEs were preserved."
                if after["valid"]
                else "TLE update failed and no complete valid fallback is available."
            ),
            "error": str(error),
            "status": after,
        }


def download_tle() -> Path:
    """Backward-compatible CLI entry point; refreshes all required catalogs."""
    result = refresh_required_tles(force=True)
    if not result["ok"]:
        raise RuntimeError(result.get("error") or result["message"])
    return TLE_FILE


def download_iss_tle() -> Path:
    """Backward-compatible ISS entry point using the same atomic transaction."""
    result = refresh_required_tles(force=True)
    if not result["ok"]:
        raise RuntimeError(result.get("error") or result["message"])
    return ISS_TLE_FILE
