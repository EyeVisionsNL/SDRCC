"""Read-only installed-feature detection for SDRCC Mobile.

An inactive systemd service is *installed*, not missing. Unknown probe results
fail open: keep the tab visible rather than silently hiding a working feature.
The existing feature selection and receiver assignments remain authoritative.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from typing import Any

from core import config as config_core
from core.features import get_features


SERVICE_UNITS = {
    "ais": "ais-catcher.service",
    "adsb": "readsb.service",
    "traffic_voice": "sdrcc-traffic-voice.service",
}
TRAFFIC_VOICE_BINARY = Path("/opt/sdrcc/traffic_voice/bin/rtl_airband")


def _unit_installed(service: str) -> bool | None:
    """Check LoadState, never is-active/is-enabled (those mean something else)."""
    try:
        result = subprocess.run(
            ["systemctl", "show", service, "--property=LoadState", "--value"],
            text=True, capture_output=True, timeout=3, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    state = (result.stdout or "").strip().lower()
    if state in {"loaded", "masked"}:
        return True
    if state == "not-found":
        return False
    return None


def _binary_installed(name: str) -> bool | None:
    try:
        return shutil.which(name) is not None
    except (OSError, ValueError):
        return None


def _component(label: str, *, feature_enabled: bool = True,
               installed: bool | None = True,
               configured: bool | None = True) -> dict[str, Any]:
    if not feature_enabled:
        state, detail = "disabled", "Niet geselecteerd tijdens installatie"
    elif installed is False:
        state, detail = "not_installed", "Software of systeemservice ontbreekt"
    elif configured is False:
        state, detail = "not_configured", "Geen SDR-ontvanger toegewezen"
    elif installed is None or configured is None:
        state, detail = "unknown", "Installatiecontrole tijdelijk niet beschikbaar"
    else:
        state, detail = "ready", "Geïnstalleerd en ingericht"
    return {"label": label, "available": state in {"ready", "unknown"},
            "state": state, "detail": detail}


def _both(first: bool | None, second: bool | None) -> bool | None:
    if first is False or second is False:
        return False
    if first is None or second is None:
        return None
    return True


def _assigned(assignments: dict[str, Any] | None, *roles: str) -> bool | None:
    if assignments is None:
        return None
    return any(bool(assignments.get(role)) for role in roles)


def get_snapshot() -> dict[str, Any]:
    """One bounded, read-only description of mobile modules; no service actions."""
    features = get_features()
    try:
        assignments = config_core.get_receiver_assignments()
    except (OSError, ValueError, KeyError, TypeError):
        assignments = None

    units = {name: _unit_installed(service) for name, service in SERVICE_UNITS.items()}
    ais_installed = _both(units["ais"], _binary_installed("AIS-catcher"))
    adsb_installed = _both(units["adsb"], _binary_installed("readsb"))
    try:
        voice_binary = TRAFFIC_VOICE_BINARY.is_file()
    except OSError:
        voice_binary = None
    voice_installed = _both(units["traffic_voice"], voice_binary)
    satellite_installed = _binary_installed("satdump")
    satellite_enabled = features.get("satellite", True) is True
    voice_enabled = features.get("traffic_voice", True) is True

    components = {
        "ais": _component("AIS-Catcher", installed=ais_installed,
                          configured=_assigned(assignments, "ais")),
        "adsb": _component("ADS-B", installed=adsb_installed,
                           configured=_assigned(assignments, "adsb")),
        "traffic_voice": _component("Marine Traffic / ATIS", feature_enabled=voice_enabled,
                                    installed=voice_installed,
                                    configured=_assigned(assignments, "traffic_voice")),
        "sat": _component("Satellites", feature_enabled=satellite_enabled,
                          installed=satellite_installed,
                          configured=_assigned(assignments, "weather", "iss_voice")),
        "missions": _component("Missions", feature_enabled=satellite_enabled,
                               installed=satellite_installed,
                               configured=_assigned(assignments, "weather", "iss_voice")),
        "system": _component("Systeem"),
    }
    marine_available = (components["ais"]["available"] or
                        components["traffic_voice"]["available"])
    components["marine"] = {
        "label": "Marine", "available": marine_available,
        "state": "ready" if marine_available else "not_configured",
        "detail": "AIS of Marine Voice beschikbaar" if marine_available
                  else "AIS en Marine Voice ontbreken of zijn niet ingericht",
    }
    return {"ok": True, "source": "installed_features_and_receiver_assignments",
            "read_only": True, "components": components}
