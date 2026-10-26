"""Read-only reuse of the installed AIS-Catcher Rijnmond VTS sector plugin.

The EyeVisionsNL AIS-Catcher plugin embeds official Rijkswaterstaat sector
GeoJSON. Parse only its JSON literal; never evaluate the JavaScript and never
contact RWS or reconfigure AIS-Catcher. An absent plugin is an unavailable
optional map layer, not a Map Lab startup error.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re

PLUGIN_PATH = Path("/etc/AIS-catcher/plugins/vts-sectoren.pjs")
_MAX_BYTES = 2_000_000
_MAX_FEATURES = 40


def _read_geojson(text: str) -> dict:
    marker = re.search(r"\bvar\s+RWS_DATA\s*=\s*", text)
    if marker is None:
        raise ValueError("No Rijkswaterstaat sector data in installed plugin")
    decoder = json.JSONDecoder()
    data, _ = decoder.raw_decode(text[marker.end():])
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("Sector data is not GeoJSON")
    features = data.get("features")
    if not isinstance(features, list):
        raise ValueError("Sector features are missing")
    # The maintained v17.x plugin adds a small optional feature after the
    # initial JSON literal. Accept it as literal JSON, never as executable JS.
    for extra in re.finditer(r"\bRWS_DATA\.features\.push\s*\(", text):
        try:
            feature, _ = decoder.raw_decode(text[extra.end():])
        except ValueError:
            continue
        if isinstance(feature, dict):
            features.append(feature)

    # Colours are read from the SAME plugin, not hard-coded independently.
    palette = {}
    color_block = re.search(r"\bvar\s+COLORS\s*=\s*\{(?P<body>.*?)\}", text, re.S)
    if color_block:
        for channel, color in re.findall(
            r"""['"](\d{1,3})['"]\s*:\s*['"](#(?:[0-9a-fA-F]{6}))['"]""",
            color_block.group("body")
        ):
            palette[channel] = color

    result = []
    for raw in features:
        if not isinstance(raw, dict) or raw.get("type") != "Feature":
            continue
        props = raw.get("properties")
        geom = raw.get("geometry")
        if not isinstance(props, dict) or not isinstance(geom, dict):
            continue
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        if not isinstance(geom.get("coordinates"), list):
            continue
        channel = str(props.get("vhfchannel") or "").strip()
        name = str(props.get("name") or "").strip()[:85]
        if not channel.isdecimal() or not name:
            continue
        color = palette.get(channel, "#7ba9c6")
        result.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "name": name, "vhfchannel": channel,
                "color": color, "source": "Rijkswaterstaat vts-deelsector_v",
            },
        })
        if len(result) >= _MAX_FEATURES:
            break
    if not result:
        raise ValueError("No valid sector polygons in installed plugin")
    return {"type": "FeatureCollection", "features": result}


@lru_cache(maxsize=4)
def _cached(path: str, modified_ns: int, size: int) -> dict:
    return _read_geojson(Path(path).read_text(encoding="utf-8"))


def snapshot(path: Path = PLUGIN_PATH) -> dict:
    try:
        stat = path.stat()
        if stat.st_size <= 0 or stat.st_size > _MAX_BYTES:
            raise ValueError("Unexpected size of installed VTS plugin")
        geojson = _cached(str(path), stat.st_mtime_ns, stat.st_size)
    except (OSError, ValueError, UnicodeError):
        return {
            "ok": True, "available": False,
            "message": "Rijnmond VTS plugin not installed or its sector geometry is unavailable",
            "geojson": {"type": "FeatureCollection", "features": []},
            "count": 0,
        }
    return {
        "ok": True, "available": True,
        "source": "Installed AIS-Catcher VTS sectors (Rijkswaterstaat)",
        "geojson": geojson, "count": len(geojson["features"]),
    }
