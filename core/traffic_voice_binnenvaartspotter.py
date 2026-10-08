#!/usr/bin/env python3
"""Binnenvaartspotter.nl Jimdo thumbnail lookup (on demand, no image storage)."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen
from xml.etree import ElementTree
import html
import re
import threading
import time
import unicodedata

SITE = "https://www.binnenvaartspotter.nl"
USER_AGENT = "SDRCC-AIS-ATIS/0.65 (attributed vessel thumbnail lookup)"
SHIP_SECTIONS = ("vrachtschepen", "containerschepen", "tankschepen",
                 "beunschepen", "duw", "sleepboten", "koppelverbanden",
                 "werkschepen", "passagiersschepen", "varend-erfgoed")
ENI_RE = re.compile(r"\bENI\s*(?:[-:]\s*)?(?:nr\.?\s*)?(\d{7,8})\b", re.I)
IMO_RE = re.compile(r"\bIMO\s*(?:[-:]\s*)?(?:nr\.?\s*)?(\d{7})\b", re.I)
MMSI_RE = re.compile(r"\bMMSI\s*(?:[-:]\s*)?(?:nr\.?\s*)?(\d{9})\b", re.I)
SHIP_CONTEXT_RE = re.compile(r"\b(?:motorvrachtschip|motortankschip|motortanker|"
    r"motorbeunschip|motorcontainerschip|vrachtschip|containerschip|beunschip|"
    r"tankerschip|tanker|duwboot|sleepboot|koppelverband|werkschip|"
    r"passagiersschip|binnenvaartschip|schip)\b", re.I)
LOCK = threading.RLock()
SITEMAP: list[str] = []
SITEMAP_CHECKED = 0.0


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]+", "", text.encode("ascii", "ignore").decode().lower())


def _ship_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ("www.binnenvaartspotter.nl", "binnenvaartspotter.nl"):
        return ""
    if parsed.query or parsed.fragment:
        return ""
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) != 2 or not parts[0].lower().startswith(SHIP_SECTIONS):
        return ""
    if any(v in parts[1] for v in (".", "..", "?", "#")):
        return ""
    return SITE + "/" + "/".join(parts) + "/"


def _download(url: str, limit: int) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ("www.binnenvaartspotter.nl", "binnenvaartspotter.nl"):
        raise ValueError("Untrusted Binnenvaartspotter URL")
    request = Request(url, headers={"User-Agent": USER_AGENT,
                                    "Accept": "text/html, application/xml"})
    with urlopen(request, timeout=4.0) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in ("www.binnenvaartspotter.nl", "binnenvaartspotter.nl"):
            raise ValueError("Untrusted photo source redirect")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Photo source response exceeds the byte limit")
    return raw.decode("utf-8", "replace")


def _sitemap() -> list[str]:
    """Read Jimdo's public XML sitemap at most twice a day, retry errors after 15 minutes."""
    global SITEMAP, SITEMAP_CHECKED
    with LOCK:
        now = time.monotonic()
        if SITEMAP_CHECKED and now - SITEMAP_CHECKED < (43200 if SITEMAP else 900):
            return SITEMAP
        try:
            xml = ElementTree.fromstring(_download(SITE + "/sitemap.xml", 3_000_000))
            links: list[str] = []
            for element in xml.iter():
                if element.tag.rsplit("}", 1)[-1].lower() == "loc":
                    page = _ship_url((element.text or "").strip())
                    if page and page not in links:
                        links.append(page)
            SITEMAP = links[:4000]
        except (OSError, ValueError, ElementTree.ParseError):
            SITEMAP = []
        SITEMAP_CHECKED = now
        return SITEMAP


def _candidate_urls(name: str) -> list[str]:
    normalized = _norm(name)
    if len(normalized) < 3:
        return []
    found = [url for url in _sitemap() if
             _norm(urlparse(url).path.strip("/").split("/")[-1]) == normalized]
    # More than one ship with the same name: refuse to guess.
    return found if len(found) == 1 else []


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.headings: list[str] = []
        self.images: list[dict[str, str]] = []
        self.words: list[str] = []
        self._heading = ""
        self._depth = 0

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if tag == "img":
            self.images.append({str(k).lower(): str(v or "") for k, v in attributes})
        if tag in ("h1", "h2", "h3") and self._depth == 0:
            self._depth = 1
            self._heading = ""
        elif self._depth:
            self._depth += 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.words.append(text)
            if self._depth:
                self._heading += " " + text

    def handle_endtag(self, tag: str) -> None:
        if self._depth:
            self._depth -= 1
            if self._depth == 0 and self._heading.strip():
                self.headings.append(self._heading.strip())


def _id_compatible(text: str, expression: re.Pattern, expected: str,
                   *, strip_zeros: bool = False) -> bool:
    if not expected.isdigit():
        return True
    found = expression.findall(text)
    if not found:
        return True
    if strip_zeros:
        return (expected.lstrip("0") or "0") in {
            value.lstrip("0") or "0" for value in found
        }
    return expected in found


def _thumbnail_url(url: str) -> str:
    url = html.unescape(str(url or "").strip())
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "image.jimcdn.com":
        return ""
    # Resize the provider's transformed image, never return the original asset.
    if re.search(r"dimension%3D\d+x\d+", url, re.I):
        return re.sub(r"dimension%3D\d+x\d+(?:%3Aformat%3D[a-z0-9]+)?",
                      "dimension%3D320x220%3Aformat%3Djpg", url, count=1, flags=re.I)
    if "cdn-cgi/image/" in url and re.search(r"width%3D\d+", url, re.I):
        return re.sub(r"cdn-cgi/image/[^/]+/",
                      "cdn-cgi/image/width%3D320%2Cheight%3D220%2Cfit%3Dcontain%2Cformat%3Djpg%2C/",
                      url, count=1, flags=re.I)
    return ""


def _result_from_page(document: str, name: str, page_url: str,
                      mmsi: str, imo: str, eni: str, now: float) -> dict | None:
    parser = _Page()
    parser.feed(document)
    target = _norm(name)
    # Page heading plus maritime context, not a random mention of the name.
    if not any(_norm(heading) == target or
               (_norm(heading).endswith(target) and len(_norm(heading)) - len(target) < 32)
               for heading in parser.headings):
        return None
    content = " ".join(parser.words[:2500])
    if not SHIP_CONTEXT_RE.search(content):
        return None
    if not (_id_compatible(content, ENI_RE, eni, strip_zeros=True) and
            _id_compatible(content, IMO_RE, imo) and
            _id_compatible(content, MMSI_RE, mmsi)):
        return None
    candidates: list[tuple[int, str]] = []
    for image in parser.images[:120]:
        uri = image.get("data-src") or image.get("src") or ""
        thumb = _thumbnail_url(uri)
        if not thumb:
            continue
        alt = _norm(image.get("alt") or image.get("title") or "")
        filename = _norm(unquote(urlparse(uri).path.rsplit("/", 1)[-1]).rsplit(".", 1)[0])
        if target not in alt and target not in filename:
            continue
        if any(term in filename for term in ("header", "logo", "banner", "avatar")):
            continue
        candidates.append((3 * int(target in alt) + int(target in filename), thumb))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return {
        "ok": True, "status": "found", "mmsi": mmsi, "shipname": name,
        "imo": imo or None, "eni": eni or None,
        "image_url": candidates[0][1], "page_url": page_url,
        "title": name, "source": "Binnenvaartspotter.nl",
        "artist": "© Peter de Vries", "license": "Thumbnail met toestemming",
        "cached_at": now,
    }


def lookup(mmsi: str, shipname: str, imo: str = "", eni: str = "",
           now: float | None = None) -> dict | None:
    if not re.fullmatch(r"\d{9}", str(mmsi or "")) or not shipname:
        return None
    now = time.time() if now is None else now
    for url in _candidate_urls(shipname):
        try:
            result = _result_from_page(
                _download(url, 1_200_000), shipname, url, mmsi,
                str(imo or ""), str(eni or ""), now
            )
            if result is not None:
                return result
        except (OSError, ValueError, TimeoutError):
            continue
    return None
