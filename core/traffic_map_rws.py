"""Read-only Hoek van Holland tide and wind data via the installed local RWS relay.

AIS-Catcher's Rijnmond VTS layer accesses the relay from port 8119, while
SDRCC serves Map Lab from 8080. Browsers cannot necessarily POST from the
second origin due to the relay's restricted CORS policy. This same-origin
SDRCC endpoint makes only four fixed local requests and never acts as an
open proxy or contacts arbitrary hosts.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

RELAY = "http://127.0.0.1:8120/ONLINEWAARNEMINGENSERVICES/"
KINDS = frozenset(("tide-measured", "tide-forecast", "wind-speed", "wind-direction"))
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
TIMEOUT_SECONDS = 7


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
    """Return the relay's JSON unmodified, or an explicit safe error.

    The browser never controls the destination, RWS endpoint, station, AQO
    filters or time range. Only a small bounded local JSON response is read.
    """
    if kind not in KINDS:
        return {"ok": False, "error": "unsupported_measurement"}
    endpoint, body = _request(kind)
    request = urllib.request.Request(
        RELAY + endpoint,
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
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
        return {"ok": False, "error": "local_rws_relay_unavailable"}
