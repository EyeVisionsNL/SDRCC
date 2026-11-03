"""Read-only local inventory of external radio software used by SDRCC.

No upstream checks, package changes, standalone update worker or elevation.
Compatible runtime upgrades may be included only in tested SDRCC releases.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess

AIRBAND_BINARY = Path("/opt/sdrcc/traffic_voice/bin/rtl_airband")
AIRBAND_PROVENANCE = Path("/opt/sdrcc/traffic_voice/share/BUILD-PROVENANCE")


def command(args, timeout=5):
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                check=False, timeout=timeout)
        if result.returncode:
            return ""
        return (result.stdout or "") + "\n" + (result.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def package_version(name):
    output = command(["/usr/bin/dpkg-query", "-W", "-f=${Version}", name]).strip()
    return output if re.search(r"\d", output) else None


def entry(identifier, name, version, present, source, uncertainty):
    return {
        "id": identifier, "name": name, "installed": version,
        "status": "installed" if present and version else "unknown" if present else "missing",
        "source": source,
        "reason": ("Version detected locally" if present and version else
                   uncertainty if present else "Optional component not installed"),
    }


def snapshot(refresh=False):
    """Return only local versions; refresh is accepted for legacy callers."""
    ais = shutil.which("AIS-catcher")
    ais_out = command([ais, "-v"]) if ais else ""
    if ais and not ais_out:
        ais_out = command([ais, "--version"])
    match = re.search(r"(?i)\bais[- ]?catcher\s+(?:version\s+)?v?(\d+\.\d+(?:\.\d+)?)", ais_out)
    ais_version = match.group(1) if match else (package_version("ais-catcher") if ais else None)

    sat = shutil.which("satdump")
    sat_out = command([sat, "version"], timeout=4) if sat else ""
    match = re.search(r"(?i)\bsatdump\s*(?:version\s*)?v?(\d+\.\d+(?:\.\d+)?)", sat_out)
    sat_version = match.group(1) if match else (package_version("satdump") if sat else None)

    readsb = shutil.which("readsb")
    readsb_out = command([readsb, "--version"]) if readsb else ""
    match = re.search(r"(?i)\breadsb\s+(?:version\s*:\s*|v)(\d+\.\d+(?:\.\d+)?)", readsb_out)
    readsb_version = match.group(1) if match else (package_version("readsb") if readsb else None)

    air_present = AIRBAND_BINARY.is_file()
    provenance = ""
    if air_present:
        try:
            provenance = AIRBAND_PROVENANCE.read_text(encoding="utf-8")
        except OSError:
            pass
    match = re.search(r"(?m)^RTLSDR-Airband\s+v?(\d+\.\d+(?:\.\d+)?)\s*$", provenance)
    if not match and air_present:
        match = re.search(r"(?i)\b(?:RTLSDR-Airband|rtl_airband)\s+v?(\d+\.\d+(?:\.\d+)?)",
                          command([str(AIRBAND_BINARY), "-v"], timeout=4))
    air_version = match.group(1) if match else None

    return {
        "ok": True,
        "software": [
            entry("ais-catcher", "AIS-catcher", ais_version, bool(ais),
                  "Local executable / installed package", "AIS executable found; version unknown"),
            entry("satdump", "SatDump", sat_version, bool(sat),
                  "Local executable / installed package", "SatDump executable found; version unknown"),
            entry("readsb", "readsb", readsb_version, bool(readsb),
                  "Local executable / installed package", "readsb executable found; version unknown"),
            entry("rtl-airband", "RTLSDR-Airband", air_version, air_present,
                  "SDRCC patched build" if provenance and air_version else "Local Traffic Voice binary",
                  "Traffic Voice binary found; version unknown"),
        ],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
