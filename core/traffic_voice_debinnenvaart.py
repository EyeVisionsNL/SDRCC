#!/usr/bin/env python3
"""De Binnenvaart: conservative, on-demand vessel thumbnail metadata lookup.

Uses the public A-Z list for exact name and ENI matching, then the linked ship
profile. Images are linked from the publisher; no image is downloaded, altered,
watermarked or saved by SDRCC. A source page and photographer credit are returned.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
import html
import re
import threading
import time
import unicodedata

BASE = "https://www.debinnenvaart.nl"
USER_AGENT = "SDRCC-Flexible-Ground-Station/0.65 (attributed ship thumbnail)"
MAX_INDEX = 4_000_000
MAX_DETAIL = 1_700_000
_index_cache: dict[str, tuple[float, list[tuple[str, str, str]]]] = {}
_lock = threading.RLock()
PHOTO_CREDIT = re.compile(r"\bFoto\s*:\s*([^\n\r]{3,180})", re.I)
ENI_TAG = re.compile(r"\b(?:EU\s*[-/]\s*ENI|ENI|EU)\s*(?:[- ]?nummer|[- ]?nr\.?)?\s*[:#]?\s*(\d{7,8})\b", re.I)
VESSEL_WORD = re.compile(r"\b(?:scheepstype|motor(?:tank|vracht|beun)schip|scheepsnaam|gebouwd\s+met\s+de\s+naam|laatste\s+naam)\b", re.I)


def _norm(s: str) -> str:
    clean = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", clean)


def _eni(s: str) -> str:
    numbers = re.sub(r"\D", "", str(s or ""))
    return numbers.lstrip("0") or ("0" if numbers else "")


def _profile_url(s: str) -> str:
    u = urlparse(urljoin(BASE, html.unescape(s)))
    if u.scheme != "https" or u.hostname not in {"debinnenvaart.nl", "www.debinnenvaart.nl"} or u.query or u.fragment:
        return ""
    if not re.fullmatch(r"/schip_detail/[a-zA-Z0-9_-]+/?", u.path):
        return ""
    return BASE + u.path.rstrip("/") + "/"


def _fetch(url: str, cap: int) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"debinnenvaart.nl", "www.debinnenvaart.nl"}:
        raise ValueError("Unexpected De Binnenvaart URL")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=4.0) as reply:
        final = urlparse(reply.geturl())
        if final.scheme != "https" or final.hostname not in {"debinnenvaart.nl", "www.debinnenvaart.nl"}:
            raise ValueError("Unexpected redirect")
        data = reply.read(cap + 1)
    if len(data) > cap:
        raise ValueError("Source HTML exceeded size limit")
    return data.decode("utf-8", "replace")


class _AlphabetIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[tuple[str, str, str]] = []
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_parts: list[str] = []
        self._url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._url = ""
        elif tag in ("td", "th") and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_row and self._in_cell and not self._url:
            self._url = _profile_url(dict(attrs).get("href") or "")

    def handle_data(self, text: str) -> None:
        if self._in_row and self._in_cell:
            self._cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            self._cells.append(" ".join(" ".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._url and len(self._cells) >= 3:
                self.rows.append((self._cells[0], self._cells[2], self._url))
            self._in_row = False


def _index(letter: str) -> list[tuple[str, str, str]]:
    now = time.monotonic()
    with _lock:
        prior = _index_cache.get(letter)
        if prior and now - prior[0] < (12 * 3600 if prior[1] else 15 * 60):
            return prior[1]
        try:
            text = _fetch(BASE + "/schepen_a_z/?sort=" + letter, MAX_INDEX)
            parser = _AlphabetIndex()
            parser.feed(text)
            rows = parser.rows[:6000]
        except (OSError, ValueError, TimeoutError):
            rows = []
        _index_cache[letter] = (now, rows)
        return rows


def _candidates(name: str, eni: str) -> list[str]:
    value = _norm(name)
    if not value or not value[0].isalpha():
        return []
    rows = _index(value[0])
    named_rows = [(record_eni, url) for record_name, record_eni, url in rows if _norm(record_name) == value]
    names = named_rows
    if eni:
        names = [(record_eni, url) for record_eni, url in names if _eni(record_eni) == _eni(eni)]
        # A same-name record with another ENI is a known identity conflict.
        # Do not bypass that conflict with a guessed first-party slug.
        if named_rows and not names:
            return []
    # Never guess between different vessels with identical names.
    unique = list(dict.fromkeys(url for _, url in names))
    if len(unique) == 1:
        return unique
    if unique:
        return []
    # A vessel may be renamed while retaining its ENI. The same first-letter
    # register may contain its previous name; use a single exact ENI match only.
    if eni:
        by_eni = list(dict.fromkeys(
            url for _, record_eni, url in rows
            if record_eni and _eni(record_eni) == _eni(eni)
        ))
        if len(by_eni) == 1:
            return by_eni
        if len(by_eni) > 1:
            return []

    # The A-Z index can omit existing first-party ship profiles (e.g. DEROVA).
    # Try a single name-based profile URL, but only return an image when its
    # exact page heading/ENI and individually credited photo are verified.
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize(
        "NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-")
    if len(slug) < 3 or len(slug) > 90:
        return []
    fallback = _profile_url(BASE + "/schip_detail/" + slug + "/")
    return [fallback] if fallback else []


def _safe_image(url: str) -> str:
    url = html.unescape(url.strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "debinnenvaart.nl", "www.debinnenvaart.nl", "de-binnenvaart.b-cdn.net"
    }:
        return ""
    path = unquote(parsed.path).lower()
    if path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return url
    if path.endswith("/image.php") and parsed.hostname in {"debinnenvaart.nl", "www.debinnenvaart.nl"}:
        inner = parse_qs(parsed.query).get("url", [""])[0]
        inside = urlparse(inner)
        if inside.scheme == "https" and inside.hostname == "de-binnenvaart.b-cdn.net" and inside.path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            # The site sometimes returns 404 via its image.php wrapper.
            # Its validated underlying first-party CDN photo is the same image.
            return inner
    return ""


def _image_from_attrs(attrs: dict[str, str]) -> str:
    # Choose an already-published small responsive candidate when available.
    variants: list[tuple[int, str]] = []
    for srcset in (attrs.get("srcset", ""), attrs.get("data-srcset", "")):
        for pair in srcset.split(","):
            bits = pair.strip().split()
            if len(bits) == 2 and re.fullmatch(r"\d+w", bits[1]):
                width = int(bits[1][:-1])
                candidate = _safe_image(urljoin(BASE, bits[0]))
                if candidate and 160 <= width <= 540:
                    variants.append((width, candidate))
    if variants:
        return min(variants, key=lambda x: abs(x[0] - 320))[1]
    for key in ("data-src", "data-lazy-src", "src"):
        candidate = _safe_image(urljoin(BASE, attrs.get(key, "")))
        if candidate:
            return candidate
    return ""


class _ShipDetail(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.text: list[str] = []
        self.images: list[tuple[str, str, str]] = []
        self._heading: str | None = None
        self._last_image = -1
        self._events_since_image = 99

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            self._heading = ""
        if tag == "img":
            data = {str(k).lower(): str(v or "") for k, v in attrs}
            link = _image_from_attrs(data)
            if link:
                self.images.append((link, "", data.get("alt", "")))
                self._last_image = len(self.images) - 1
                self._events_since_image = 0

    def handle_data(self, part: str) -> None:
        part = " ".join(part.split())
        if not part:
            return
        self.text.append(part)
        if self._heading is not None:
            self._heading += " " + part
        if self._last_image >= 0:
            self._events_since_image += 1
            found = PHOTO_CREDIT.search(part)
            if found and self._events_since_image <= 8:
                src, _, alt = self.images[self._last_image]
                artist = found.group(1).split(" - ")[0].strip()
                self.images[self._last_image] = (src, artist[:120], alt + " " + found.group(1))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._heading is not None:
            self.headings.append(self._heading.strip())
            self._heading = None


def _parse_detail(doc: str, name: str, eni: str, page_url: str, mmsi: str,
                  imo: str, now: float) -> dict | None:
    page = _ShipDetail()
    page.feed(doc)
    matching_name = _norm(name) in {_norm(title) for title in page.headings}
    body = " ".join(page.text[:4000])
    if not VESSEL_WORD.search(body):
        return None
    # The page can still use the previous registered name. Only the identical
    # eight-digit ENI proves that a different heading belongs to the AIS hull.
    confirmed_eni = False
    if eni:
        known = {_eni(n) for n in ENI_TAG.findall(body)}
        if known and _eni(eni) not in known:
            return None
        confirmed_eni = _eni(eni) in known
    if not matching_name and not confirmed_eni:
        return None
    # Require a photographer credit for the individual photo. Some genuine
    # gallery thumbnails use opaque filenames and captions naming an older
    # vessel identity. Accept them only on a profile with a confirmed ENI.
    target = _norm(name)
    possibles = []
    for index, (url, artist, alt) in enumerate(page.images):
        if not artist:
            continue
        file_name = _norm(unquote(urlparse(url).path.split("/")[-1]))
        if (target in _norm(alt) or target in file_name or
                (eni and _eni(eni) in file_name) or confirmed_eni):
            possibles.append((index, url, artist))
    if not possibles:
        return None
    _, image_url, artist = possibles[0]
    return {"ok": True, "status": "found", "mmsi": mmsi,
            "shipname": name, "imo": imo or None, "eni": eni or None,
            "image_url": image_url, "page_url": page_url, "title": name,
            "source": "De Binnenvaart", "artist": artist,
            "license": "Thumbnail met toestemming · watermerk behouden",
            "cached_at": now}


def lookup(mmsi: str, shipname: str, imo: str = "", eni: str = "",
           now: float | None = None) -> dict | None:
    if not re.fullmatch(r"\d{9}", str(mmsi or "")) or not shipname:
        return None
    now = time.time() if now is None else now
    for page_url in _candidates(shipname, eni):
        try:
            result = _parse_detail(_fetch(page_url, MAX_DETAIL), shipname,
                                   eni, page_url, mmsi, imo, now)
            if result:
                return result
        except (OSError, ValueError, TimeoutError):
            continue
    return None
