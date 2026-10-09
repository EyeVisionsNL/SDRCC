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
from core.traffic_voice_debinnenvaart import lookup as _binnenvaart_lookup
from core.traffic_voice_binnenvaartspotter import lookup as _spotter_lookup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_FILE = PROJECT_ROOT / "data" / "cache" / "traffic_voice_vessel_photos.json"
CACHE_SECONDS = 7 * 24 * 3600
PHOTO_POLICY_VERSION = 8
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



MARITIME_TERMS = re.compile(
    r"\b(?:ships?|vessels?|tankers?|barges?|coasters?|freighters?|cargo\s+ships?|"
    r"container\s+ships?|cruise\s+ships?|passenger\s+(?:ships?|vessels?)|"
    r"ferries|ferry|tugs?|towboats?|pushboats?|workboats?|"
    r"motortankers?|motorschepen|motorschip|motortankschepen|motortankschip|"
    r"binnenvaartschepen|binnenschip|binnenvaart|schepen|schip|scheepvaart|"
    r"vrachtschepen|vrachtschip|tankerschepen|tankerschip|"
    r"schiffe|schiff|frachtschiff|tankschiff|"
    r"m\s*/\s*v|m\s*/\s*s|ss|mts|mv|ms|"
    r"shipping|maritime|navire|bateau|schipspotter)\b", re.I)
NON_VESSEL_TERMS = re.compile(
    r"\b(?:minerals?|gemstones?|crystals?|quartz|rubellite|indicolite|"
    r"pegmatite|tourmaline\s+sample|rocks?|sculptures?|paintings?|"
    r"drawings?|sketches?|illustrations?|watercolou?rs?|postcards?|"
    r"album\s+covers?|film\s+posters?|scale\s+models?|model\s+ships?)\b", re.I)
MILITARY_PREFIX = re.compile(r"\b(?:USS|HMS|USCGC|HMCS|USNS)\b", re.I)
VESSEL_LABEL = (
    r"(?:motor\s*tankers?|motortankers?|motortankschip|tankers?|ships?|"
    r"vessels?|cargo\s+ships?|coasters?|barges?|ferries|ferry|tugs?|"
    r"binnenschip|binnenvaartschip|schepen|schip|vrachtschip|schiff|"
    r"frachtschiff|m\s*/\s*v|m\s*/\s*s|mv|ms|mts)"
)


def _identifier_values(text: str, field: str, length: int) -> set[str]:
    expression = (
        rf"\b{re.escape(field)}\s*(?:n[ou](?:mber|mmer)?\.?\s*)?"
        rf"(?:[:#=\-/]\s*)?(\d{{{length}}})\b"
    )
    return set(re.findall(expression, text, flags=re.I))


def _name_pattern(shipname: str) -> re.Pattern | None:
    words = re.findall(r"[A-Z0-9]+", shipname.upper())
    if not words:
        return None
    return re.compile(r"(?<![A-Z0-9])" + r"[\s._-]+".join(map(re.escape, words)) + r"(?![A-Z0-9])", re.I)


def _named_vessel_context(text: str, name: re.Pattern | None) -> bool:
    if name is None:
        return False
    forward = rf"\b{VESSEL_LABEL}(?:\s+(?:named|called|genaamd))?\s+{name.pattern}"
    backward = rf"{name.pattern}\s*(?:[,(:;\-]\s*)?(?:(?:is|was|a|an|the|een)\s+)?{VESSEL_LABEL}\b"
    return bool(re.search(forward, text, re.I) or re.search(backward, text, re.I))


def _score(page: dict, *, mmsi: str, shipname: str, imo: str, eni: str = "") -> int:
    """Only rank photographs with verified vessel identity or explicit ship context.

    Matching a name such as TOURMALINE without vessel evidence is not enough.
    Reject unrelated historical naval ships and pages with conflicting identifiers.
    """
    info = (page.get("imageinfo") or [{}])[0]
    if not str(info.get("thumburl") or "").startswith("https://"):
        return -1000
    if not str(page.get("title") or "").lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
        return -1000
    meta = info.get("extmetadata") or {}
    title = _clean_text(page.get("title"), 300)
    description = _clean_text((meta.get("ImageDescription") or {}).get("value"), 1500)
    object_name = _clean_text((meta.get("ObjectName") or {}).get("value"), 300)
    categories = _clean_text((meta.get("Categories") or {}).get("value"), 1500)
    all_text = " ".join((title, description, object_name, categories))
    if REJECT_TERMS.search(all_text):
        return -1000

    others_imo = _identifier_values(all_text, "IMO", 7)
    others_mmsi = _identifier_values(all_text, "MMSI", 9)
    if imo and others_imo and imo not in others_imo:
        return -1000
    if others_mmsi and mmsi not in others_mmsi:
        return -1000

    others_eni = _identifier_values(all_text, "ENI", 8)
    if eni and others_eni and eni not in others_eni:
        return -1000
    has_eni = bool(eni and eni in others_eni)
    has_imo = bool(imo and imo in others_imo)
    has_mmsi = bool(mmsi and mmsi in others_mmsi)
    name = _name_pattern(shipname)
    if not (has_imo or has_mmsi):
        # Crystal, Mineral etc. can also be real ship names: keep them only
        # where the full name is explicitly described as a vessel.
        if NON_VESSEL_TERMS.search(title) and not _named_vessel_context(title, name):
            return -1000
        if NON_VESSEL_TERMS.search(description) and not _named_vessel_context(description + " " + object_name, name):
            return -1000
    if has_imo or has_mmsi or has_eni:
        return 200 + (20 if has_mmsi else 0) + (10 if has_imo else 0) + (10 if has_eni else 0)

    # Common vessel names cannot establish the identity of a photograph.
    return -1000



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
MARK_IMO_RE = re.compile(r"\bIMO\s*(?:[- ]\s*(?:number|nummer|no\.?))?[\s:|]{0,30}(\d{7})\b", re.I)
MARK_MMSI_RE = re.compile(r"\bMMSI\s*(?:[- ]\s*(?:number|nummer|no\.?))?[\s:|]{0,30}(\d{9})\b", re.I)


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


def _mark_page(url: str, max_bytes: int = 1_200_000) -> tuple[str, str]:
    """Small, bounded on-demand requests; never follow off-site redirects."""
    if urlparse(url).hostname != "markprummel.nl" or urlparse(url).scheme != "https":
        raise ValueError("Unexpected Mark Prummel URL")
    request = Request(url, headers={"User-Agent": MARK_USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=8.0) as response:
        final_url = response.geturl()
        if urlparse(final_url).scheme != "https" or urlparse(final_url).hostname != "markprummel.nl":
            raise ValueError("Unexpected photo-source redirect")
        document = response.read(max_bytes + 1)
    if len(document) > max_bytes:
        raise ValueError("Photo-source page too large")
    return document.decode("utf-8", "replace"), final_url


def _mark_ship_url(url: str) -> str:
    full = urljoin(MARK_BASE, html.unescape(url))
    parsed = urlparse(full)
    if parsed.scheme != "https" or parsed.hostname != "markprummel.nl":
        return ""
    return full.split("?", 1)[0].split("#", 1)[0] if MARK_SHIP_LINK_RE.fullmatch(parsed.path) else ""



MARK_REGISTER_URL = MARK_BASE + "/ships-register/"
MARK_REGISTER_TTL = 12 * 3600
_mark_register_rows: list[tuple[str, str]] | None = None
_mark_register_checked: float = 0.0


class _MarkRegisterParser(HTMLParser):
    """Only index actual ship profile links and their visible vessel names."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str]] = []
        self._link: str = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs = dict(attributes)
            self._link = _mark_ship_url(str(attrs.get("href") or ""))
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._link:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._link:
            name = " ".join(" ".join(self._text).split())
            if name:
                self.rows.append((name, self._link))
            self._link = ""
            self._text = []


def _mark_register() -> list[tuple[str, str]]:
    """At most one bounded register request per 12h, shared by photo lookups."""
    global _mark_register_rows, _mark_register_checked
    now = time.time()
    with _lock:
        if _mark_register_rows is not None and now - _mark_register_checked < MARK_REGISTER_TTL:
            return _mark_register_rows
        # The public register lists the ship names alongside their IMO numbers.
        # Unlike WordPress free-text search, this URL is stable and browseable.
        try:
            document, _ = _mark_page(MARK_REGISTER_URL, max_bytes=3_000_000)
            parser = _MarkRegisterParser()
            parser.feed(document)
            _mark_register_rows = parser.rows[:4000]
        except (OSError, ValueError, TimeoutError):
            _mark_register_rows = []
        _mark_register_checked = now
        return _mark_register_rows


def _mark_candidate_urls(imo: str, shipname: str) -> list[str]:
    rows = _mark_register()
    if imo:
        # IMO is stable across renames and changes of flag/MMSI.
        pattern = re.compile(rf"(?<!\d){re.escape(imo)}/?$")
        return [url for _, url in rows if pattern.search(urlparse(url).path)][:3]
    # For inland vessels with no IMO, use an exact name and validate MMSI
    # against the detail page before ever returning its image.
    name = re.sub(r"[^A-Z0-9]+", " ", shipname.upper()).strip()
    if not name:
        return []
    return [
        url for candidate_name, url in rows
        if re.sub(r"[^A-Z0-9]+", " ", candidate_name.upper()).strip() == name
    ][:3]

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


def lookup(mmsi: str, shipname: str = "", imo: str = "", eni: str = "") -> dict:
    mmsi = _clean_text(mmsi, 9)
    shipname = _clean_text(shipname)
    imo = re.sub(r"\D", "", _clean_text(imo, 12))
    if not (len(mmsi) == 9 and mmsi.isdigit()):
        raise ValueError("A valid nine-digit MMSI is required")

    eni = re.sub(r"\D", "", _clean_text(eni, 12))
    key = "|".join((str(PHOTO_POLICY_VERSION), mmsi, shipname.upper(), imo, eni))
    now = time.time()
    with _lock:
        cached = _load().get(key)
        if cached:
            ttl = CACHE_SECONDS if cached.get("ok") else NEGATIVE_CACHE_SECONDS
            if now - float(cached.get("cached_at") or 0) < ttl:
                return {**cached, "cached": True}

    # Priority 1 (beta): Peter's Binnenvaartspotter.nl, thumbnails only.
    # Missing, ambiguous or unreachable ship pages fall through unchanged.
    spotter_result = _spotter_lookup(mmsi, shipname, imo, eni, now)
    if spotter_result:
        with _lock:
            cache = _load()
            cache[key] = spotter_result
            try:
                _save(cache)
            except OSError:
                pass
        return {**spotter_result, "cached": False}

    # Priority 2: De Binnenvaart, matching the alphabetic vessel register and ENI.
    # The photographer's original image and watermark are never modified.
    binnenvaart_result = _binnenvaart_lookup(mmsi, shipname, imo, eni, now)
    if binnenvaart_result:
        with _lock:
            cache = _load()
            cache[key] = binnenvaart_result
            try:
                _save(cache)
            except OSError:
                pass
        return {**binnenvaart_result, "cached": False}

    # Priority 3: Mark Prummel.
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

    # Priority 4: Wikimedia Commons. Ordered fallbacks: exact identifiers first.
    # Ordered fallbacks: exact identifiers first, then vessel name. Each query
    # is small and sequential; once a trustworthy candidate is found we stop.
    queries: list[str] = []
    if eni:
        queries.append(f'"ENI {eni}"')
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
            score = _score(page, mmsi=mmsi, shipname=shipname, imo=imo, eni=eni)
            if best is None or score > best[0]:
                best = (score, page, query)
        # Identifier hit or a full-name hit is strong enough to stop.
        if best and best[0] >= 200:
            break

    result: dict
    if best and best[0] >= 100:
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
