#!/usr/bin/env python3
"""Optional, on-demand vessel photo lookup for Traffic Voice.

No worker or poller runs in the background. The module is called only when the
browser explicitly enables vessel photos and a validated ATIS/AIS match exists.
Photos are not proxied or stored; only small lookup metadata is cached.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "traffic_voice_vessel_photos.json"
CACHE_SECONDS = 7 * 24 * 3600
_lock = threading.RLock()
_cache: dict[str, dict] | None = None


def _load() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        _cache = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        _cache = {}
    return _cache


def _save(cache: dict[str, dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CACHE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CACHE_FILE)


def _clean_text(value: object, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def lookup(mmsi: str, shipname: str = "") -> dict:
    mmsi = _clean_text(mmsi, 9)
    shipname = _clean_text(shipname)
    if not (len(mmsi) == 9 and mmsi.isdigit()):
        raise ValueError("A valid nine-digit MMSI is required")

    key = mmsi
    now = time.time()
    with _lock:
        cached = _load().get(key)
        if cached and now - float(cached.get("cached_at") or 0) < CACHE_SECONDS:
            return {**cached, "cached": True}

    # Commons is deliberately queried only here. No request is made while the
    # Vessel photos switch is off in the browser.
    query = f'"{mmsi}"'
    if shipname:
        query = f'"{shipname}" {mmsi}'
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": "6", "gsrlimit": "5", "gsrsearch": query,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "640",
    }
    request = Request(
        "https://commons.wikimedia.org/w/api.php?" + urlencode(params),
        headers={"User-Agent": "SDRCC-Flexible-Ground-Station/1.0 (vessel-photo lookup)"},
    )
    try:
        with urlopen(request, timeout=3.5) as response:
            payload = json.load(response)
    except (OSError, ValueError, TimeoutError) as error:
        return {"ok": False, "mmsi": mmsi, "status": "unavailable", "error": str(error)}

    pages = list((payload.get("query") or {}).get("pages", {}).values())
    result = {"ok": False, "mmsi": mmsi, "status": "not_found", "cached_at": now}
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        thumb = str(info.get("thumburl") or "")
        if not thumb.startswith("https://"):
            continue
        meta = info.get("extmetadata") or {}
        result = {
            "ok": True, "status": "found", "mmsi": mmsi,
            "shipname": shipname,
            "image_url": thumb,
            "page_url": str(info.get("descriptionurl") or ""),
            "title": str(page.get("title") or "").removeprefix("File:"),
            "artist": _clean_text((meta.get("Artist") or {}).get("value"), 160),
            "license": _clean_text((meta.get("LicenseShortName") or {}).get("value"), 80),
            "source": "Wikimedia Commons",
            "cached_at": now,
        }
        break

    with _lock:
        cache = _load()
        cache[key] = result
        try:
            _save(cache)
        except OSError:
            pass
    return {**result, "cached": False}
