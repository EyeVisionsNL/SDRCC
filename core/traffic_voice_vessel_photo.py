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
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse, unquote
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "traffic_voice_vessel_photos.json"
CACHE_SECONDS = 7 * 24 * 3600
PHOTO_POLICY_VERSION = 3
REJECT_TERMS = re.compile(r"\b(painting|artwork|illustration|drawing|sketch|model ship|scale model|watercolour|watercolor|oil on canvas|postcard|painting of)\b", re.I)
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
    if REJECT_TERMS.search(haystack):
        return -1000
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
    # Names alone are ambiguous: require an exact name phrase, not scattered words.
    if shipname and shipname.upper() in haystack:
        score += 20
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



MARK_BASE = "https://markprummel.nl"
MARK_USER_AGENT = "SDRCC-AIS-ATIS-vessel-photo/1.0 (non-commercial attribution lookup)"
MARK_SHIP_LINK_RE = re.compile(r"^/(?:nl/)?ship/[^?#]+/?$", re.I)
MARK_IMO_RE = re.compile(r"\bIMO\s*(?:number|nummer|no\.?)?[\s:|]{0,30}(\d{7})\b", re.I)
MARK_MMSI_RE = re.compile(r"\bMMSI\s*(?:number|nummer|no\.?)?[\s:|]{0,30}(\d{9})\b", re.I)


class _MarkPageParser(HTMLParser):
    """Collect first-party ship links and image attributes without executing HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.images: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = {str(key).lower(): str(value or "") for key, value in attributes}
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        elif tag == "img":
            self.images.append(attrs)
        elif tag == "meta":
            key = attrs.get("property", attrs.get("name", "")).lower()
            if key and attrs.get("content"):
                self.meta.setdefault(key, attrs["content"])


def _mark_page(url: str) -> tuple[str, str]:
    """Small, bounded on-demand requests; never follow off-site redirects."""
    if urlparse(url).hostname != "markprummel.nl" or urlparse(url).scheme != "https":
        raise ValueError("Unexpected Mark Prummel URL")
    request = Request(url, headers={"User-Agent": MARK_USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=3.5) as response:
        final_url = response.geturl()
        if urlparse(final_url).scheme != "https" or urlparse(final_url).hostname != "markprummel.nl":
            raise ValueError("Unexpected photo-source redirect")
        document = response.read(600_001)
    if len(document) > 600_000:
        raise ValueError("Photo-source page too large")
    return document.decode("utf-8", "replace"), final_url


def _mark_ship_url(url: str) -> str:
    full = urljoin(MARK_BASE, html.unescape(url))
    parsed = urlparse(full)
    if parsed.scheme != "https" or parsed.hostname != "markprummel.nl":
        return ""
    return full.split("?", 1)[0].split("#", 1)[0] if MARK_SHIP_LINK_RE.fullmatch(parsed.path) else ""


def _mark_candidate_urls(imo: str, shipname: str) -> list[str]:
    # WordPress search targets a unique IMO first; never crawl photo archives.
    # A ship name is used only when no usable IMO candidate was returned.
    terms = ([imo] if imo else [])
    if shipname and len(shipname.strip()) >= 4:
        terms.append(shipname)
    seen: set[str] = set()
    candidates: list[str] = []
    for term in terms[:2]:
        try:
            document, final_url = _mark_page(MARK_BASE + "/?" + urlencode({"s": term}))
        except (OSError, ValueError, TimeoutError):
            continue
        parser = _MarkPageParser()
        parser.feed(document)
        links = [final_url, *parser.links]
        for link in links:
            candidate = _mark_ship_url(link)
            if not candidate or candidate in seen:
                continue
            # When an IMO is known, a ship article's slug must identify it.
            # Avoid photos of a different ship with the same or a similar name.
            if imo and not re.search(rf"(?:^|[-/]){re.escape(imo)}/?$", urlparse(candidate).path):
                continue
            seen.add(candidate)
            candidates.append(candidate)
            if len(candidates) >= 3:
                return candidates
        if candidates:
            break
    return candidates


def _mark_image_url(document: str, parser: _MarkPageParser, shipname: str) -> str:
    """Pick only a vessel-specific uploaded image, never a site logo or flag."""
    normalized_name = re.sub(r"[^a-z0-9]+", " ", shipname.lower()).strip()
    if not normalized_name or len(normalized_name) < 4:
        return ""
    images = [*parser.images]
    if parser.meta.get("og:image"):
        images.insert(0, {
            "src": parser.meta["og:image"],
            "alt": parser.meta.get("og:image:alt", ""),
        })
    best: tuple[int, str] | None = None
    for item in images[:80]:
        candidate = urljoin(MARK_BASE, html.unescape(
            item.get("data-src") or item.get("data-large_image") or item.get("src") or ""
        ))
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or parsed.hostname != "markprummel.nl":
            continue
        path = parsed.path.lower()
        if "/wp-content/uploads/" not in path or not path.endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        label = re.sub(r"[^a-z0-9]+", " ", html.unescape(item.get("alt", "")).lower()).strip()
        filename = re.sub(r"[^a-z0-9]+", " ", unquote(parsed.path).lower()).strip()
        if any(word in filename for word in (" flag ", " logo ", " icon ", " avatar ", " placeholder ", " banner ")):
            continue
        # A precise name in image alt or filename is mandatory.
        if normalized_name not in label and normalized_name not in filename:
            continue
        score = (120 if normalized_name in label else 0) + (70 if normalized_name in filename else 0)
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else ""


def _mark_lookup(mmsi: str, shipname: str, imo: str, now: float) -> dict | None:
    # Mark Prummel mainly photographs coasters and ferries. Only a verified
    # ship article with a vessel-specific photograph may outrank Commons.
    if not shipname:
        return None
    for url in _mark_candidate_urls(imo, shipname):
        try:
            document, final_url = _mark_page(url)
        except (OSError, ValueError, TimeoutError):
            continue
        plain = _clean_text(document, 200_000)
        page_imo = MARK_IMO_RE.search(plain)
        page_mmsi = MARK_MMSI_RE.search(plain)
        if imo:
            if not page_imo or page_imo.group(1) != imo:
                continue
        elif not page_mmsi or page_mmsi.group(1) != mmsi:
            continue
        parser = _MarkPageParser()
        parser.feed(document)
        photo_url = _mark_image_url(document, parser, shipname)
        if photo_url:
            return {
                "ok": True, "status": "found", "mmsi": mmsi,
                "shipname": shipname, "imo": imo or None,
                "image_url": photo_url, "page_url": final_url,
                "title": shipname, "artist": "© Mark & Chris Prummel",
                "license": "CC BY-NC 4.0 (non-commercial)",
                "source": "Mark Prummel", "matched_query": imo or mmsi,
                "cached_at": now,
            }
    return None


def lookup(mmsi: str, shipname: str = "", imo: str = "") -> dict:
    mmsi = _clean_text(mmsi, 9)
    shipname = _clean_text(shipname)
    imo = re.sub(r"\D", "", _clean_text(imo, 12))
    if not (len(mmsi) == 9 and mmsi.isdigit()):
        raise ValueError("A valid nine-digit MMSI is required")

    key = "|".join((str(PHOTO_POLICY_VERSION), mmsi, shipname.upper(), imo))
    now = time.time()
    with _lock:
        cached = _load().get(key)
        if cached:
            ttl = CACHE_SECONDS if cached.get("ok") else NEGATIVE_CACHE_SECONDS
            if now - float(cached.get("cached_at") or 0) < ttl:
                return {**cached, "cached": True}

    # Priority 1: Mark Prummel; only accept a verified ship and photograph.
    mark_result = _mark_lookup(mmsi, shipname, imo, now)
    if mark_result:
        with _lock:
            cache = _load()
            cache[key] = mark_result
            try:
                _save(cache)
            except OSError:
                pass
        return {**mark_result, "cached": False}

    # Priority 2: Wikimedia Commons. Ordered fallbacks: exact identifiers first.
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
        if best and best[0] >= 80:
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
