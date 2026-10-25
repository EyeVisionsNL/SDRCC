"""Read-only Hoek van Holland measurements from official RWS WaterWebservices.

AIS-Catcher's Rijnmond relay restricts all requests to Origin port 8119,
including server-to-server requests with no Origin. SDRCC therefore contacts
the SAME fixed official upstream service on its own backend. Its browser only
uses the same-origin SDRCC API. Only four fixed requests are possible; no
arbitrary URLs, stations, filters or time ranges are accepted.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

UPSTREAM = ("https://ddapi20-waterwebservices.rijkswaterstaat.nl"
            "/ONLINEWAARNEMINGENSERVICES/")
KINDS = frozenset(("tide-measured", "tide-forecast", "wind-speed", "wind-direction"))
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 15


def _request(kind: str, now: datetime | None = None) -> tuple[str, dict]:
    """Build exactly the AQO bodies used by the Rijnmond AIS-Catcher layer."""
    if kind not in KINDS:
        raise ValueError("Unknown RWS measurement")
    at = now or datetime.now().astimezone()
    if kind.startswith("tide-"):
        process = "meting" if kind == "tide-measured" else "astronomisch"
        start = at - timedelta(hours=6)
        end = at if process == "meting" else at + timedelta(hours=7)
        return "OphalenWaarnemingen", {
            "Locatie": {"Code": "hoekvanholland"},
            "AquoPlusWaarnemingMetadata": {"AquoMetadata": {
                "Compartiment": {"Code": "OW"},
                "Grootheid": {"Code": "WATHTE"},
                "Hoedanigheid": {"Code": "NAP"},
                "Eenheid": {"Code": "cm"},
                "ProcesType": process,
            }},
            "Periode": {
                "Begindatumtijd": start.isoformat(timespec="seconds"),
                "Einddatumtijd": end.isoformat(timespec="seconds"),
            },
        }
    code = "WINDSHD" if kind == "wind-speed" else "WINDRTG"
    return "OphalenLaatsteWaarnemingen", {
        "LocatieLijst": [{"Code": "hoekvanholland"}],
        "AquoPlusWaarnemingMetadataLijst": [{
            "AquoMetadata": {
                "Compartiment": {"Code": "LT"},
                "Grootheid": {"Code": code},
            },
            "WaarnemingMetadata": {
                "OpdrachtgevendeInstantieLijst": ["RIKZ_METEO"],
            },
        }],
    }


def fetch(kind: str, opener=None) -> dict:
    """Return official RWS JSON unchanged, or an explicit safe error.

    The browser never controls the destination, RWS endpoint, station, AQO
    filters or time range. Only bounded data from the fixed RWS host is read.
    """
    if kind not in KINDS:
        return {"ok": False, "error": "unsupported_measurement"}
    endpoint, body = _request(kind)
    request = urllib.request.Request(
        UPSTREAM + endpoint,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json", "User-Agent": "SDRCC-RWS/1.0"},
        method="POST",
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status == 204:
                return {"ok": True, "payload": None}
            if response.status != 200:
                return {"ok": False, "error": "rws_http_error"}
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return {"ok": False, "error": "rws_response_too_large"}
        return {"ok": True, "payload": json.loads(raw)}
    except (OSError, ValueError, TimeoutError, urllib.error.URLError):
        return {"ok": False, "error": "rws_service_unavailable"}
