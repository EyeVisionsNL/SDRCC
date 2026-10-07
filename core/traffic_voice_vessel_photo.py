#!/usr/bin/env python3
"""Optional, on-demand vessel photo lookup for Traffic Voice.

Nothing runs in the background. Calls happen only when the browser has vessel
photos enabled and SDRCC has a validated live ATIS/AIS match.
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "traffic_voice_vessel_photos.json"
CACHE_SECONDS = 7 * 24 * 3600
NEGATIVE_CACHE_SECONDS = 6 * 3600
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
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    return " ".join(text.split())[:limit]


def _commons_search(query: str) -> list[dict]:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrnamespace": "6", "gsrlimit": "8", "gsrsearch": query,
        "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "640",
    }
    request = Request(
        "https://commons.wikimedia.org/w/api.php?" + urlencode(params),
        headers={"User-Agent": "SDRCC-Flexible-Ground-Station/0.64 (vessel-photo lookup)"},
    )
    with urlopen(request, timeout=4.0) as response:
        payload = json.load(response)
    return list((payload.get("query") or {}).get("pages", {}).values())


def _score(page: dict, *, mmsi: str, shipname: str, imo: str) -> int:
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    haystack = " ".join([
        str(page.get("title") or ""),
        _clean_text((meta.get("ImageDescription") or {}).get("value"), 1000),
        _clean_text((meta.get("ObjectName") or {}).get("value"), 300),
        _clean_text((meta.get("Categories") or {}).get("value"), 1000),
    ]).upper()
    score = 0
    if mmsi and mmsi in haystack:
        score += 100
    if imo and imo in haystack:
        score += 90
    words = [word for word in re.findall(r"[A-Z0-9]+", shipname.upper()) if len(word) >= 3]
    if words and all(word in haystack for word in words):
        score += 60
    elif words and any(word in haystack for word in words):
        score += 25
    return score


def _result_from_page(page: dict, *, mmsi: str, shipname: str, imo: str, query: str, now: float) -> dict | None:
    info = (page.get("imageinfo") or [{}])[0]
    thumb = str(info.get("thumburl") or "")
    if not thumb.startswith("https://"):
        return None
    meta = info.get("extmetadata") or {}
    return {
        "ok": True, "status": "found", "mmsi": mmsi, "imo": imo or None,
        "shipname": shipname, "image_url": thumb,
        "page_url": str(info.get("descriptionurl") or ""),
        "title": str(page.get("title") or "").removeprefix("File:"),
        "artist": _clean_text((meta.get("Artist") or {}).get("value"), 160),
        "license": _clean_text((meta.get("LicenseShortName") or {}).get("value"), 80),
        "source": "Wikimedia Commons", "matched_query": query, "cached_at": now,
    }


def lookup(mmsi: str, shipname: str = "", imo: str = "") -> dict:
    mmsi = _clean_text(mmsi, 9)
    shipname = _clean_text(shipname)
    imo = re.sub(r"\D", "", _clean_text(imo, 12))
    if not (len(mmsi) == 9 and mmsi.isdigit()):
        raise ValueError("A valid nine-digit MMSI is required")

    key = "|".join((mmsi, shipname.upper(), imo))
    now = time.time()
    with _lock:
        cached = _load().get(key)
        if cached:
            ttl = CACHE_SECONDS if cached.get("ok") else NEGATIVE_CACHE_SECONDS
            if now - float(cached.get("cached_at") or 0) < ttl:
                return {**cached, "cached": True}

    # Ordered fallbacks: exact identifiers first, then vessel name. Each query
    # is small and sequential; once a trustworthy candidate is found we stop.
    queries: list[str] = []
    if imo:
        queries.extend([f'"IMO {imo}"', f'"{imo}" ship'])
    queries.append(f'"{mmsi}"')
    if shipname:
        queries.extend([
            f'intitle:"{shipname}" ship',
            f'"{shipname}" vessel',
            f'"{shipname}" ship',
        ])

    best: tuple[int, dict, str] | None = None
    error: str | None = None
    for query in queries:
        try:
            pages = _commons_search(query)
        except (OSError, ValueError, TimeoutError) as exc:
            error = str(exc)
            continue
        for page in pages:
            score = _score(page, mmsi=mmsi, shipname=shipname, imo=imo)
            if best is None or score > best[0]:
                best = (score, page, query)
        # Identifier hit or a full-name hit is strong enough to stop.
        if best and best[0] >= 60:
            break

    result: dict
    if best and best[0] >= 60:
        candidate = _result_from_page(
            best[1], mmsi=mmsi, shipname=shipname, imo=imo, query=best[2], now=now,
        )
        result = candidate or {"ok": False, "status": "not_found", "mmsi": mmsi, "cached_at": now}
    else:
        result = {
            "ok": False, "status": "unavailable" if error and best is None else "not_found",
            "mmsi": mmsi, "shipname": shipname, "imo": imo or None,
            "searched": queries, "cached_at": now,
        }
        if error and best is None:
            result["error"] = error

    with _lock:
        cache = _load()
        cache[key] = result
        try:
            _save(cache)
        except OSError:
            pass
    return {**result, "cached": False}
