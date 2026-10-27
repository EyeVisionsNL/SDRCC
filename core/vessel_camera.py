"""Curated onboard camera links; no network requests or changes to AIS matching.

MMSI AND current ship name must match. Same-name vessels are never inferred.
Provider pages own their expiring video URLs. See docs/vessel-cameras.md for
identity sources and intentionally excluded ambiguous vessels.
"""
from __future__ import annotations

import re

# name, public camera page slug; checked 2026-10-27.
CAMERAS = {
    "244010927": ("CARISMA", "carisma"),
    "205263890": ("YARIS", "yaris"),
    "244139567": ("MI-MUNDO", "Mi-Mundo"),
    "244219047": ("MEJURI", "mejuri"),
    "244670966": ("SURVIVOR", "survivor"),
    "244660333": ("KAREL DOORMAN", "karel-doorman"),
    "244180341": ("LAUWERSZEE", "lauwerszee"),
    "244850307": ("FURKA", "furka"),
    "244650973": ("EVERINGEN", "everingen"),
    "244700660": ("RED FOX", "red-fox"),
    "244710427": ("STRICK", "strick"),
}


def for_match(match: dict) -> dict | None:
    """Supplement an existing validated ATIS/AIS match, never create one."""
    if not isinstance(match, dict) or match.get("matched") is not True:
        return None
    mmsi = str(match.get("mmsi") or "")
    entry = CAMERAS.get(mmsi)
    if entry is None:
        return None
    name, slug = entry
    normalized = lambda value: re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if normalized(match.get("shipname")) != normalized(name):
        return None
    page = "https://webcam-binnenvaart.nl/pages/cam-" + slug + ".php"
    return {"mmsi": mmsi, "shipname": name, "page_url": page,
            "provider": "Webcam Binnenvaart"}
