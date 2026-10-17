#!/usr/bin/env python3
"""Current De Binnenvaart read-only JSON metadata source for attributed vessel photos.

Only the publisher's public endpoints are requested; no image is downloaded.
The exact current name or an ENI match must identify a single vessel and
each photo must have photographer attribution.
"""
from __future__ import annotations
import json
import re
import time
import unicodedata
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

BASE = "https://debinnenvaart.nl"
API = BASE + "/api/schepen"
MAX_SEARCH = 600_000
MAX_DETAIL = 1_100_000
PAGE_LIMIT = 50
MAX_PAGES = 3


def _norm(value: object) -> str:
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def _eni(value: object) -> str:
    d = re.sub(r"\D", "", str(value or ""))
    return d.lstrip("0") or ("0" if d else "")


def _get_json(url: str, cap: int) -> dict:
    p = urlparse(url)
    if p.scheme != "https" or p.netloc != "debinnenvaart.nl" or p.fragment or not (
        p.path == "/api/schepen" or re.fullmatch(r"/api/schepen/[A-Za-z0-9_-]{1,90}", p.path)
    ):
        raise ValueError("Unsupported photo metadata URL")
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SDRCC-Flexible-Ground-Station/0.67 (attributed thumbnail)",
    })
    with urlopen(req, timeout=5.0) as resp:
        final = urlparse(resp.geturl())
        if final.scheme != "https" or final.netloc != "debinnenvaart.nl" or final.path != p.path:
            raise ValueError("Unexpected photo metadata redirect")
        raw = resp.read(cap + 1)
    if len(raw) > cap:
        raise ValueError("Photo metadata too large")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid photo metadata response")
    return data


def _photo_url(value: object, ship_id: str) -> str:
    url = str(value or "").strip()
    if not url or len(url) > 1024:
        return ""
    p = urlparse(url)
    if (p.scheme != "https" or p.username or p.password or p.fragment or p.query
            or not re.search(r"\.(?:jpe?g|png|webp)$", p.path, re.I)):
        return ""
    if p.netloc == "content.epublisher-cloud.com":
        return url if p.path.startswith("/binnenvaartdata/images/" + ship_id + "/") else ""
    if p.netloc == "de-binnenvaart.b-cdn.net":
        return url
    return ""


def _photographer(row: dict) -> str:
    name = str(row.get("fotograaf") or "").strip()
    if not name:
        credit = str(row.get("credit") or "").strip()
        match = re.match(r"Foto\s*:\s*(.+)", credit, re.I)
        if match:
            name = match.group(1).split(" - ")[0].strip()
    return name if 2 <= len(name) <= 120 and name.lower() not in {"unknown", "onbekend", "n/a", "anonymous"} else ""


def lookup(mmsi: str, shipname: str, imo: str = "", eni: str = "",
           now: float | None = None) -> dict | None:
    if (not re.fullmatch(r"\d{9}", str(mmsi or "")) or
            not _norm(shipname) or len(str(shipname)) > 120 or
            (eni and not re.fullmatch(r"\d{7,8}", str(eni)))):
        return None
    eni = str(eni or "")
    now = time.time() if now is None else now
    try:
        # Current-name matches are preferred; old names and fuzzy matches do
        # not establish the identity of an active AIS vessel.
        valid = {}
        received = 0
        for page in range(1, MAX_PAGES + 1):
            query = API + "?" + urlencode({"q": shipname, "per_page": PAGE_LIMIT, "page": page})
            search = _get_json(query, MAX_SEARCH)
            rows = search.get("data")
            if not isinstance(rows, list):
                return None
            total = int(search.get("totaal"))
            if total < 0:
                return None
            received += len(rows)
            for row in rows:
                if (not isinstance(row, dict) or
                        _norm(row.get("laatste_naam")) != _norm(shipname) or
                        str(row.get("status") or "actief").lower() != "actief"):
                    continue
                if eni and _eni(row.get("eu_nummer_laatste") or row.get("eu_nummer_eerste")) != _eni(eni):
                    continue
                ship_id = str(row.get("id") or "")
                if re.fullmatch(r"[A-Za-z0-9_-]{1,90}", ship_id):
                    valid[ship_id] = row
            if received >= total:
                break
            if not rows or page == MAX_PAGES:
                return None  # Partial search cannot prove a unique match.
        if len(valid) != 1:
            return None
        ship_id, summary = next(iter(valid.items()))
        detail = _get_json(API + "/" + ship_id, MAX_DETAIL)
        if str(detail.get("id") or "") != ship_id or _norm(detail.get("laatste_naam")) != _norm(shipname):
            return None
        if str(detail.get("status") or "actief").lower() != "actief":
            return None
        indexed_eni = str(summary.get("eu_nummer_laatste") or summary.get("eu_nummer_eerste") or "")
        registered_eni = str(detail.get("eu_nummer_laatste") or detail.get("eu_nummer_eerste") or "")
        if indexed_eni and _eni(indexed_eni) != _eni(registered_eni):
            return None
        found_eni = str(detail.get("eu_nummer_laatste") or detail.get("eu_nummer_eerste") or "").strip()
        if eni and _eni(eni) != _eni(found_eni):
            return None
        photos = detail.get("fotos")
        if not isinstance(photos, list):
            return None
        for row in photos[:60]:
            if (not isinstance(row, dict) or
                    str(row.get("is_vlag") or "0").lower() not in {"0", "false"} or
                    str(row.get("goedgekeurd")) != "1"):
                continue
            if row.get("schip_id") and str(row["schip_id"]) != ship_id:
                continue
            artist = _photographer(row)
            if not artist:
                continue
            src = _photo_url(row.get("src"), ship_id)
            image = src or _photo_url(row.get("url"), ship_id)
            if not image:
                continue
            # The search thumb is only used if it belongs to this credited photo.
            thumb = _photo_url(summary.get("thumb"), ship_id)
            if src and thumb == src:
                image = thumb
            return {
                "ok": True, "status": "found", "mmsi": mmsi,
                "shipname": shipname, "imo": imo or None, "eni": found_eni or eni or None,
                "image_url": image, "page_url": BASE + "/schip/" + ship_id,
                "title": shipname, "source": "De Binnenvaart", "artist": artist,
                "license": "Thumbnail met toestemming · watermerk behouden",
                "cached_at": now,
            }
    except (OSError, ValueError, TimeoutError, TypeError):
        return None
    return None
