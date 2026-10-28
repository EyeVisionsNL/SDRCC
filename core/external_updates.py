"""Read-only discovery of third-party packages used by SDRCC.

Checks run only on explicit request (cached between refreshes). The update
worker is a separate, narrowly sudo-authorized systemd unit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.request import Request, urlopen

WORKER_STATUS = Path("/var/lib/sdrcc/external-update-status.json")
WORKER_UNIT = "sdrcc-external-update.service"
RELEASE_API = "https://api.github.com/repos/jvde-github/AIS-catcher/releases/latest"
RELEASE_PAGE = "https://github.com/jvde-github/AIS-catcher/releases"
SATDUMP_PAGE = "https://github.com/SatDump/SatDump/releases"
CACHE_SECONDS = 900
_LOCK = threading.RLock()
_CACHE: dict = {"checked_at": 0.0, "ais_release": None, "error": None}
VERSION_RE = re.compile(r"(?i)\b(?:ais[- ]?catcher)\s+v?(\d+\.\d+(?:\.\d+)?)\b")
TAG_RE = re.compile(r"^v(\d+\.\d+(?:\.\d+)?)$")


def command(args, timeout=5):
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              check=False, timeout=timeout)
        return (done.stdout or "") + "\n" + (done.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def ais_version(output):
    match = VERSION_RE.search(output or "")
    return match.group(1) if match else None


def version_tuple(value):
    if not value or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        return None
    return tuple(int(x) for x in (value.split(".") + ["0"])[:3])


def _check_ais_release():
    req = Request(RELEASE_API, headers={
        "User-Agent": "SDRCC-external-release-check",
        "Accept": "application/vnd.github+json",
    })
    with urlopen(req, timeout=6) as response:
        payload = json.loads(response.read(65536))
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag):
        raise ValueError("Unexpected AIS-catcher release tag")
    link = payload.get("html_url")
    if not isinstance(link, str) or not link.startswith(RELEASE_PAGE + "/tag/"):
        link = RELEASE_PAGE + "/tag/" + tag
    assets = []
    for entry in payload.get("assets", []):
        name, digest, url = entry.get("name"), entry.get("digest"), entry.get("browser_download_url")
        if (isinstance(name, str)
                and re.fullmatch(r"ais-catcher_ubuntu_[a-z]+_(?:amd64|arm64|armhf)\.deb", name)
                and isinstance(digest, str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                and isinstance(url, str)
                and url == f"https://github.com/jvde-github/AIS-catcher/releases/download/{tag}/{name}"
                and 0 < int(entry.get("size") or 0) <= 50_000_000):
            assets.append({"name": name, "digest": digest, "url": url,
                           "size": entry["size"]})
    return {"version": tag[1:], "tag": tag, "url": link,
            "published_at": payload.get("published_at"), "assets": assets}


def apt_ais_installed():
    return "install ok installed" in command(
        ["/usr/bin/dpkg-query", "-W", "-f=${Status}", "ais-catcher"]).lower()


def matching_ais_asset(upstream):
    """Select a checksum-verified official package for the exact installed OS."""
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8")
    except OSError:
        return None
    def os_field(key):
        for line in os_release.splitlines():
            name, separator, value = line.partition("=")
            if separator and name == key:
                return value.strip().strip('"')
        return ""
    if os_field("ID") != "ubuntu":
        return None
    codename = os_field("VERSION_CODENAME")
    arch = command(["/usr/bin/dpkg", "--print-architecture"]).strip()
    if not re.fullmatch(r"[a-z]{3,16}", codename) or arch not in ("amd64", "arm64", "armhf"):
        return None
    asset_name = f"ais-catcher_ubuntu_{codename}_{arch}.deb"
    return next((entry for entry in upstream.get("assets", [])
                 if entry.get("name") == asset_name), None)


def release(refresh=False):
    with _LOCK:
        if refresh or not _CACHE["checked_at"] or time.time() - _CACHE["checked_at"] > CACHE_SECONDS:
            try:
                _CACHE["ais_release"] = _check_ais_release()
                _CACHE["error"] = None
            except Exception as exc:
                _CACHE["ais_release"] = None
                _CACHE["error"] = str(exc)[:180]
            _CACHE["checked_at"] = time.time()
        return dict(_CACHE)


def _apt_version(package, field):
    result = command(["/usr/bin/apt-cache", "policy", package])
    match = re.search(r"^\s*" + re.escape(field) + r":\s*(\S+)", result, re.M)
    value = match.group(1) if match else None
    return None if value in (None, "(none)") else value


def _apt_newer(installed, candidate):
    if not installed or not candidate:
        return False
    try:
        return subprocess.run(
            ["/usr/bin/dpkg", "--compare-versions", candidate, "gt", installed],
            timeout=3, capture_output=True, check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def worker_status():
    try:
        data = json.loads(WORKER_STATUS.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("state") in {"starting", "backing_up", "installing", "verifying", "restoring"}:
        if command(["/usr/bin/systemctl", "is-active", WORKER_UNIT]).strip() != "active":
            return {**data, "state": "interrupted",
                    "message": "External update worker interrupted; check backup and logs."}
    return data


def snapshot(refresh=False):
    ais_installed = ais_version(command(["AIS-catcher", "-v"]))
    if not ais_installed and shutil.which("AIS-catcher"):
        ais_installed = ais_version(command(["AIS-catcher", "--version"]))
    ais_package = command(["/usr/bin/dpkg-query", "-W", "-f=${Version}", "ais-catcher"]).strip()
    if not ais_installed and ais_package:
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", ais_package)
        if match:
            ais_installed = match.group(1)
    upstream = release(refresh=refresh)
    latest = upstream.get("ais_release") or {}
    candidate = _apt_version("satdump", "Candidate")
    installed = _apt_version("satdump", "Installed")
    satdump_binary = shutil.which("satdump")
    satdump_upgrade = bool(satdump_binary and installed and candidate and
                           _apt_newer(installed, candidate))
    readsb_info = command(["readsb", "--version"])
    readsb_match = re.search(r"readsb version:\s*(\d+\.\d+(?:\.\d+)?)",
                            readsb_info, re.I)
    readsb_version = readsb_match.group(1) if readsb_match else None
    ais_upgrade = bool(ais_installed and latest.get("version") and
                       version_tuple(latest["version"]) and version_tuple(ais_installed)
                       and version_tuple(latest["version"]) > version_tuple(ais_installed))
    ais_manageable = bool(apt_ais_installed() and matching_ais_asset(latest))
    ais_can_install = ais_upgrade and ais_manageable
    rows = [
        {"id": "ais-catcher", "name": "AIS-catcher", "installed": ais_installed,
         "latest": latest.get("version"), "available": ais_upgrade,
         "can_install": ais_can_install, "source": "Official GitHub release",
         "url": latest.get("url") or RELEASE_PAGE,
         "reason": (upstream.get("error") or "Installed version unavailable")
             if not (ais_installed and latest.get("version")) else
             ("New upstream release available" if ais_can_install else
              "New release requires package/platform review" if ais_upgrade else "Up to date")},
        {"id": "satdump", "name": "SatDump", "installed": installed or
         ("Non-APT installation" if satdump_binary else None),
         "latest": candidate, "available": satdump_upgrade,
         "can_install": satdump_upgrade, "source": "Ubuntu APT packages",
         "url": SATDUMP_PAGE,
         "reason": "APT update available" if satdump_upgrade else
                   ("Managed outside APT; update requires manual review"
                    if satdump_binary and not installed else "No newer APT package available")},
        {"id": "readsb", "name": "readsb",
         "installed": readsb_version,
         "latest": None, "available": False, "can_install": False,
         "source": "SDRCC pinned build", "url": "https://github.com/wiedehopf/readsb",
         "reason": "Pinned by SDRCC; compatibility review required"},
        {"id": "rtl-airband", "name": "RTLSDR-Airband",
         "installed": "SDRCC patched v5.2.0" if
            Path("/opt/sdrcc/traffic_voice/bin/rtl_airband").exists() else None,
         "latest": None, "available": False, "can_install": False,
         "source": "SDRCC custom build", "url": "https://github.com/rtl-airband/RTLSDR-Airband",
         "reason": "Custom gain and scan patches; automatic upgrade disabled"},
    ]
    return {"ok": True, "software": rows, "worker": worker_status(),
            "release_check_error": upstream.get("error"),
            "checked_at": datetime.now(timezone.utc).isoformat()}
