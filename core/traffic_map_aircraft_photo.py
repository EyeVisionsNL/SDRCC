"""Optional on-demand aircraft photo lookup for the experimental traffic map.

No background traffic, tracking, receiver access or external calls until a
user explicitly clicks an aircraft. Data from Planespotters.net public API.
"""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

_URL = "https://api.planespotters.net/pub/photos/hex/"
_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = threading.RLock()
_MAX_CACHE = 512


def _trusted_url(value: object, image: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 500:
        return ""
    try:
        p = urlparse(value)
        host = p.hostname or ""
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
            return ""
        # Planespotters thumbnails are served on its own abbreviated CDN,
        # not just *.planespotters.net. Previous check dropped every such
        # response and falsely reported "no photograph".
        official = (host == "planespotters.net" or
                    host.endswith(".planespotters.net"))
        photo_cdn = host == "t.plnspttrs.net" and image
        if not (official or photo_cdn):
            return ""
        # The image CDN also serves thumbnails from extensionless paths.
        # Origin validation is the restriction; never accept unknown domains.
        return value
    except ValueError:
        return ""


def lookup(hex_id: str, registration: str = "", aircraft_type: str = "") -> dict:
    ident = str(hex_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{6}", ident):
        return {"ok": False, "message": "No verified ICAO hexadecimal identifier"}
    reg = str(registration or "").strip().upper()
    kind = str(aircraft_type or "").strip().upper()
    reg = reg if re.fullmatch(r"[A-Z0-9-]{2,12}", reg) else ""
    kind = kind if re.fullmatch(r"[A-Z0-9]{2,8}", kind) else ""
    key = (ident, reg, kind)
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return dict(cached[1])
    result: dict = {"ok": False, "message": "No verified aircraft photograph available"}
    try:
        hints = urlencode({"reg": reg, "icaoType": kind}) if reg or kind else ""
        request = Request(_URL + ident + ("?" + hints if hints else ""), headers={
            "User-Agent": "SDRCC/0.68 (map-lab on-demand aircraft photo)",
            "Accept": "application/json",
        })
        with urlopen(request, timeout=3.5) as response:
            data = json.load(response)
        photos = data.get("photos") if isinstance(data, dict) else None
        if isinstance(photos, list):
            for photo in photos[:5]:
                if not isinstance(photo, dict):
                    continue
                urls = [photo.get("thumbnail_large"), photo.get("thumbnail")]
                url = ""
                for entry in urls:
                    candidate = entry.get("src") if isinstance(entry, dict) else None
                    url = _trusted_url(candidate, image=True)
                    if url:
                        break
                if not url:
                    continue
                link = _trusted_url(photo.get("link"))
                result = {
                    "ok": True, "image_url": url, "source_url": link,
                    "photographer": str(photo.get("photographer") or "").strip()[:90],
                    "source": "Planespotters.net",
                }
                break
    except (OSError, ValueError, TypeError, TimeoutError):
        pass
    with _LOCK:
        if len(_CACHE) >= _MAX_CACHE:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = (time.monotonic() + (21600 if result["ok"] else 300), result)
    return dict(result)
