#!/usr/bin/env python3
"""Conservative on-demand Shipspotting thumbnail lookup for Traffic Voice.

Only public HTML pages are consulted; no login, API bypass, background crawler,
full-size image download or local image copy is used. A verified IMO/MMSI/ENI,
a photo-specific photographer credit and a published thumbnail are mandatory.
If the provider blocks access or changes its markup, other sources take over.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
import html
import re
import time

BASE = "https://www.shipspotting.com"
USER_AGENT = "SDRCC-Flexible-Ground-Station/0.66 (attributed thumbnail lookup)"
PHOTO_PATH = re.compile(r"^/photos/(\d{5,10})/?$")
IMO_RE = re.compile(r"\bIMO\s*:\s*(\d{7})\b", re.I)
MMSI_RE = re.compile(r"\bMMSI\s*:\s*(\d{9})\b", re.I)
ENI_RE = re.compile(r"\bENI\s*:\s*(\d{7,8})\b", re.I)
MAX_SEARCH = 1_500_000
MAX_PHOTO = 1_200_000


def _photo_url(value: str) -> str:
    parsed = urlparse(urljoin(BASE, html.unescape(value or "")))
    if parsed.scheme != "https" or parsed.hostname not in {"www.shipspotting.com", "shipspotting.com"}:
        return ""
    found = PHOTO_PATH.fullmatch(parsed.path)
    return BASE + "/photos/" + found.group(1) if found else ""


def _thumbnail_url(value: str) -> str:
    """Accept an *already published* reduced photo URL; never use /photos/big/."""
    parsed = urlparse(urljoin(BASE, html.unescape(value or "")))
    if parsed.scheme != "https":
        return ""
    if not (parsed.hostname == "shipspotting.com" or
            (parsed.hostname or "").endswith(".shipspotting.com")):
        return ""
    path = parsed.path.lower()
    if not re.search(r"\.(?:jpg|jpeg|png|webp)$", path):
        return ""
    if re.search(r"/(?:big|large|full|original)/", path):
        return ""
    if re.search(r"/photos/(?:small|thumb|thumbnail|medium|preview|teaser)/", path):
        return parsed.geturl()
    # A genuine resized CDN URL, not a full-size image displayed smaller in CSS.
    if "/photos/" in path and re.search(r"(?:^|&)(?:width|w)=([1-4]\d{2})(?:&|$)", parsed.query):
        return parsed.geturl()
    return ""


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.previews: dict[str, str] = {}
        self.images: list[dict[str, str]] = []
        self.words: list[str] = []
        self.meta: dict[str, str] = {}
        self._anchor = ""
        self._ignore = 0

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = {str(key).lower(): str(value or "") for key, value in attributes}
        if tag in ("script", "style", "noscript"):
            self._ignore += 1
        elif tag == "a":
            self._anchor = _photo_url(attrs.get("href", ""))
            if self._anchor and self._anchor not in self.links:
                self.links.append(self._anchor)
        elif tag == "img":
            self.images.append(attrs)
            if self._anchor:
                image = _image_from_attrs(attrs)
                if image:
                    self.previews.setdefault(self._anchor, image)
        elif tag == "meta":
            key = attrs.get("property") or attrs.get("name") or ""
            if key:
                self.meta[key.lower()] = attrs.get("content", "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._anchor = ""
        elif tag in ("script", "style", "noscript"):
            self._ignore = max(0, self._ignore - 1)

    def handle_data(self, data: str) -> None:
        if not self._ignore:
            line = " ".join(data.split())
            if line:
                self.words.append(line)


def _image_from_attrs(attrs: dict[str, str]) -> str:
    for key in ("srcset", "data-srcset"):
        for item in attrs.get(key, "").split(","):
            part = item.strip().split()
            if len(part) == 2 and re.fullmatch(r"\d+w", part[1]):
                width = int(part[1][:-1])
                if 140 <= width <= 500:
                    candidate = _thumbnail_url(part[0])
                    if candidate:
                        return candidate
    for key in ("data-src", "data-lazy-src", "src"):
        candidate = _thumbnail_url(attrs.get(key, ""))
        if candidate:
            return candidate
    return ""


def _download(url: str, cap: int) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"www.shipspotting.com", "shipspotting.com"}:
        raise ValueError("Unexpected Shipspotting URL")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(request, timeout=5.0) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https" or final.hostname not in {"www.shipspotting.com", "shipspotting.com"}:
            raise ValueError("Unexpected Shipspotting redirect")
        data = response.read(cap + 1)
    if len(data) > cap:
        raise ValueError("Shipspotting response exceeds size limit")
    return data.decode("utf-8", "replace")


def _search_links(doc: str) -> tuple[list[str], dict[str, str]]:
    parser = _Page()
    parser.feed(doc)
    # Embedded hydration JSON occasionally holds links absent from HTML anchors.
    # These are only candidates: each detail page must pass all checks below.
    candidates = parser.links[:8]
    if not candidates:
        for match in re.finditer(r"/photos/(\d{5,10})(?=[/?\u0022#]|$)", doc):
            url = _photo_url("/photos/" + match.group(1))
            if url and url not in candidates:
                candidates.append(url)
            if len(candidates) >= 8:
                break
    return candidates, parser.previews


def _credit(words: list[str]) -> str:
    for index, part in enumerate(words[:450]):
        if re.fullmatch(r"photographer\s*:", part, re.I) and index + 1 < len(words):
            name = words[index + 1].strip()
        else:
            match = re.match(r"^Photographer\s*:\s*(.+)$", part, re.I)
            if not match:
                continue
            name = match.group(1).strip()
        name = re.sub(r"\s*\[?\s*View profile.*$", "", name, flags=re.I).strip()
        if 2 <= len(name) <= 120 and name.lower() not in {"unknown", "n/a", "view profile"}:
            return name
    return ""


def _identifiers(words: list[str]) -> tuple[str, str, str]:
    visible = " ".join(words)
    match = re.search(r"\bVessel\s+particulars\b", visible, re.I)
    if not match:
        return "", "", ""
    # Ignore IMO/MMSI numbers appearing in unrelated comments or photo descriptions.
    part = visible[match.end():][:5000]
    part = re.split(r"\b(?:AIS Position|Photo Categories|More of this ship|Comment this photo)\b",
                    part, maxsplit=1, flags=re.I)[0]
    imo = IMO_RE.search(part)
    mmsi = MMSI_RE.search(part)
    eni = ENI_RE.search(part)
    return (imo.group(1) if imo else "",
            mmsi.group(1) if mmsi else "",
            eni.group(1) if eni else "")


def _detail(doc: str, url: str, preview: str, mmsi: str, name: str,
            imo: str, eni: str, now: float) -> dict | None:
    page = _Page()
    page.feed(doc)
    found_imo, found_mmsi, found_eni = _identifiers(page.words)
    # Reject contradictory IDs, even when the displayed name happens to match.
    if imo and found_imo and found_imo != imo:
        return None
    # MMSI changes with flag or operator; a verified IMO or ENI outranks
    # an old MMSI on a correctly identified Shipspotting photo.
    strong_id = bool((imo and found_imo == imo) or
                     (eni and found_eni and found_eni.lstrip("0") == eni.lstrip("0")))
    if found_mmsi and found_mmsi != mmsi and not strong_id:
        return None
    if eni and found_eni and found_eni.lstrip("0") != eni.lstrip("0"):
        return None
    # At least one positive IMO, MMSI or ENI match is mandatory.
    if not ((imo and found_imo == imo) or found_mmsi == mmsi or
            (eni and found_eni and found_eni.lstrip("0") == eni.lstrip("0"))):
        return None
    artist = _credit(page.words
    if not artist:
        return None
    # Search-grid images are normally pre-sized. Otherwise accept only a
    # first-party thumbnail explicitly provided on the photo detail page.
    candidate_images = [preview]
    for key in ("og:image", "twitter:image"):
        candidate_images.append(page.meta.get(key, ""))
    candidate_images.extend(_image_from_attrs(image) for image in page.images[:70])
    thumbnail = next((image for value in candidate_images
                      if (image := _thumbnail_url(value))), "")
    if not thumbnail:
        return None
    return {
        "ok": True, "status": "found", "mmsi": mmsi, "imo": imo or None,
        "eni": eni or None, "shipname": name,
        "image_url": thumbnail, "page_url": url, "title": name,
        "artist": "© " + artist, "license": "",
        "source": "Shipspotting.com", "matched_query": imo or eni or mmsi,
        "cached_at": now,
    }


def lookup(mmsi: str, shipname: str, imo: str = "", eni: str = "",
           now: float | None = None) -> dict | None:
    """Return only verified attributed thumbnails; safely fall through otherwise."""
    if not re.fullmatch(r"\d{9}", str(mmsi or "")):
        return None
    imo = str(imo or "")
    eni = str(eni or "")
    if imo and not re.fullmatch(r"\d{7}", imo):
        return None
    if eni and not re.fullmatch(r"\d{7,8}", eni):
        return None
    now = time.time() if now is None else now
    # Advanced gallery searches accept IMO, MMSI and ENI. On inland vessels
    # an ENI is often available even when Shipspotting lacks an AIS MMSI.
    queries: list[tuple[str, str]] = []
    if imo:
        queries.append(("imo", imo))
    if eni:
        queries.append(("eni", eni.lstrip("0") or "0"))
    queries.append(("mmsi", mmsi))
    for field, identifier in queries:
        search_url = BASE + "/photos/gallery?" + urlencode({
            field: identifier, "sortBy": "newest", "viewType": "normal"
        })
        try:
            links, previews = _search_links(_download(search_url, MAX_SEARCH))
        except (OSError, ValueError, TimeoutError):
            continue
        for photo_url in links[:4]:
            try:
                result = _detail(_download(photo_url, MAX_PHOTO),
                                 photo_url, previews.get(photo_url, ""),
                                 mmsi, shipname, imo, eni, now)
                if result:
                    return result
            except (OSError, ValueError, TimeoutError):
                continue
    return None
