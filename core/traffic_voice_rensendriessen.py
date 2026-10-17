#!/usr/bin/env python3
"""Rensen-Driessen credited vessel thumbnails, on demand and only for exact ship pages."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, unquote
from urllib.request import Request, urlopen
import html
import re
import threading
import time
import unicodedata

BASE = "https://www.rensendriessen.com"
REGISTER = BASE + "/building/our-ships/"
HOSTS = {"www.rensendriessen.com", "rensendriessen.com"}
_cache_lock = threading.RLock()
_register: list[tuple[str, str]] = []
_checked = 0.0


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]", "", value.encode("ascii", "ignore").decode().lower())


def _ship_url(value: str) -> str:
    p = urlparse(urljoin(BASE, html.unescape(value)))
    if p.scheme != "https" or p.hostname not in HOSTS or p.query or p.fragment:
        return ""
    if not re.fullmatch(r"/ships/[a-z0-9-]{2,90}/?", p.path, re.I):
        return ""
    return BASE + p.path.rstrip("/") + "/"


def _image_url(value: str, shipname: str) -> str:
    p = urlparse(urljoin(BASE, html.unescape(value)))
    if p.scheme != "https" or p.hostname not in HOSTS or p.query or p.fragment:
        return ""
    if not p.path.startswith("/wp-content/uploads/"):
        return ""
    filename = unquote(p.path.rsplit("/", 1)[-1])
    if not re.search(r"\.(?:jpe?g|webp|png)$", filename, re.I):
        return ""
    stem = re.sub(r"\.(?:jpe?g|webp|png)$", "", filename, flags=re.I)
    if not _norm(stem).startswith(_norm(shipname)) or any(x in stem.lower() for x in ("logo", "banner", "flag", "icon")):
        return ""
    return p.geturl()


def _read(url: str, maximum: int) -> str:
    p = urlparse(url)
    if (p.scheme != "https" or p.hostname not in HOSTS or p.query or p.fragment
            or (url != REGISTER and not _ship_url(url))):
        raise ValueError("Untrusted Rensen-Driessen URL")
    req = Request(url, headers={"Accept": "text/html", "User-Agent": "SDRCC/0.67 (attributed vessel thumbnail)"})
    with urlopen(req, timeout=8) as response:
        dest = urlparse(response.geturl())
        if dest.scheme != "https" or dest.hostname not in HOSTS or dest.path.rstrip("/") != p.path.rstrip("/"):
            raise ValueError("Untrusted redirect")
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise ValueError("Oversized photo source")
    return payload.decode("utf-8", "replace")


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.images: list[str] = []
        self.headings: list[str] = []
        self.content: list[str] = []
        self.link = ""
        self.link_text: list[str] = []
        self.heading = False
        self.heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "a":
            self.link = _ship_url(str(a.get("href") or ""))
            self.link_text = []
            if str(a.get("href") or "").lower().endswith((".jpg", ".jpeg", ".webp", ".png")):
                self.images.append(str(a["href"]))
        elif tag == "img":
            for key in ("data-src", "data-lazy-src", "src"):
                if a.get(key):
                    self.images.append(str(a[key]))
        elif tag == "h1":
            self.heading = True
            self.heading_text = []

    def handle_data(self, data: str) -> None:
        s = " ".join(data.split())
        if s:
            self.content.append(s)
            if self.link:
                self.link_text.append(s)
            if self.heading:
                self.heading_text.append(s)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            if self.link:
                self.links.append((" ".join(self.link_text).strip(), self.link))
            self.link = ""
        if tag == "h1":
            if self.heading:
                self.headings.append(" ".join(self.heading_text).strip())
            self.heading = False


def _ships() -> list[tuple[str, str]]:
    global _register, _checked
    with _cache_lock:
        if _checked and time.monotonic() - _checked < (43200 if _register else 900):
            return list(_register)
        try:
            p = _Parser()
            p.feed(_read(REGISTER, 4_500_000))
            _register = list(dict.fromkeys((name, url) for name, url in p.links if name))
        except (OSError, ValueError, TimeoutError):
            _register = []
        _checked = time.monotonic()
        return list(_register)


def lookup(mmsi: str, shipname: str, imo: str = "", eni: str = "", now: float | None = None) -> dict | None:
    name = " ".join(str(shipname or "").split())
    if not re.fullmatch(r"\d{9}", str(mmsi or "")) or not 4 <= len(_norm(name)) <= 100:
        return None
    pages = {url for n, url in _ships() if _norm(n) == _norm(name)}
    if len(pages) != 1:
        return None
    url = next(iter(pages))
    try:
        p = _Parser()
        p.feed(_read(url, 1_800_000))
        if not any(_norm(heading).endswith(_norm(name)) for heading in p.headings):
            return None
        body = " ".join(p.content)
        for label, expected, width in (("MMSI", str(mmsi), 9), ("IMO", str(imo or ""), 7), ("ENI", str(eni or ""), 8)):
            found = set(re.findall(rf"\b{label}\s*[:#-]?\s*(\d{{{width}}})\b", body, re.I))
            if found and expected not in found:
                return None
        image = next((photo for value in p.images if (photo := _image_url(value, name))), "")
        if not image:
            return None
        return {
            "ok": True, "status": "found", "mmsi": mmsi, "shipname": name,
            "imo": imo or None, "eni": eni or None, "image_url": image, "page_url": url,
            "title": name, "artist": "Rensen-Driessen Shipbuilding B.V.",
            "source": "Rensen-Driessen", "license": "Thumbnail met toestemming",
            "logo_overlay": True, "cached_at": time.time() if now is None else now,
        }
    except (OSError, ValueError, TimeoutError):
        return None
