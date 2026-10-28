"""Read-only discovery of third-party packages used by SDRCC.

Checks run only on explicit request (cached between refreshes). The update
worker is a separate, narrowly sudo-authorized systemd unit.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from concurrent.futures import ThreadPoolExecutor
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
SATDUMP_RELEASE_API = "https://api.github.com/repos/SatDump/SatDump/releases/latest"
AIRBAND_PAGE = "https://github.com/rtl-airband/RTLSDR-Airband/releases"
AIRBAND_RELEASE_API = "https://api.github.com/repos/rtl-airband/RTLSDR-Airband/releases/latest"
READSB_PAGE = "https://github.com/wiedehopf/readsb/tree/dev"
READSB_VERSION_URL = "https://raw.githubusercontent.com/wiedehopf/readsb/dev/version"
AIRBAND_PROVENANCE = Path("/opt/sdrcc/traffic_voice/share/BUILD-PROVENANCE")
AIRBAND_BINARY = Path("/opt/sdrcc/traffic_voice/bin/rtl_airband")
CACHE_SECONDS = 900
_LOCK = threading.RLock()
_CACHE: dict = {"checked_at": 0.0, "ais_release": None, "error": None,
                "satdump_release": None, "airband_release": None,
                "readsb_upstream": None, "errors": {}}
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


def _github_stable_release(url, page, prefix=""):
    """Fetch a validated published stable release; prereleases are excluded."""
    request = Request(url, headers={
        "User-Agent": "SDRCC-external-release-check",
        "Accept": "application/vnd.github+json",
    })
    with urlopen(request, timeout=6) as response:
        payload = json.loads(response.read(128 * 1024))
    tag = payload.get("tag_name")
    if (not isinstance(tag, str) or
            not re.fullmatch(re.escape(prefix) + r"\d+\.\d+(?:\.\d+)?", tag)
            or payload.get("draft") or payload.get("prerelease")):
        raise ValueError("Unexpected stable release tag")
    version = tag[len(prefix):]
    return {"version": version, "tag": tag, "url": page + "/tag/" + tag,
            "published_at": payload.get("published_at")}


def _readsb_development_version():
    """readsb deliberately has no stable GitHub release feed. Check dev/version."""
    request = Request(READSB_VERSION_URL, headers={
        "User-Agent": "SDRCC-external-release-check",
        "Cache-Control": "no-cache",
    })
    with urlopen(request, timeout=6) as response:
        version = response.read(128).decode("utf-8").strip()
    if version_tuple(version) is None:
        raise ValueError("Invalid readsb dev version")
    return {"version": version, "url": READSB_PAGE, "channel": "dev"}


def release(refresh=False):
    with _LOCK:
        if refresh or not _CACHE["checked_at"] or time.time() - _CACHE["checked_at"] > CACHE_SECONDS:
            sources = {
                "ais_release": _check_ais_release,
                "satdump_release": lambda: _github_stable_release(
                    SATDUMP_RELEASE_API, SATDUMP_PAGE),
                "airband_release": lambda: _github_stable_release(
                    AIRBAND_RELEASE_API, AIRBAND_PAGE, prefix="v"),
                "readsb_upstream": _readsb_development_version,
            }
            errors = {}
            # Independent sources must not block one another, and must not
            # turn a successful check into an ambiguous global failure.
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = {name: executor.submit(fetch) for name, fetch in sources.items()}
                for name, future in results.items():
                    try:
                        _CACHE[name] = future.result()
                    except Exception as exc:
                        _CACHE[name] = None
                        errors[name] = str(exc)[:180]
            _CACHE["errors"] = errors
            _CACHE["error"] = errors.get("ais_release")
            _CACHE["checked_at"] = time.time()
        return dict(_CACHE, errors=dict(_CACHE.get("errors") or {}))


def installed_satdump_version(package, binary):
    """Prefer local binary/version; do not pretend a source build is APT-managed."""
    if not binary:
        return None, "not-installed"
    # SatDump 1.2.2 supports `satdump version` (not `--version`).
    output = command([binary, "version"], timeout=4)
    match = re.search(r"(?i)\bsatdump\s*(?:version\s*)?v?(\d+\.\d+(?:\.\d+)?)\b", output)
    if match:
        return match.group(1), "binary"
    if package:
        return package, "apt"
    # The clean installer pins 1.2.2, but an unrecognised local binary may
    # have been replaced later. Never mark it current based on that assumption.
    return None, "non-apt-unverified"


def installed_airband_version():
    if not AIRBAND_BINARY.is_file():
        return None, "not-installed"
    try:
        provenance = AIRBAND_PROVENANCE.read_text(encoding="utf-8")
    except OSError:
        provenance = ""
    match = re.search(r"(?m)^RTLSDR-Airband\s+v?(\d+\.\d+(?:\.\d+)?)\s*$", provenance)
    if match:
        return match.group(1), "SDRCC patched"
    output = command([str(AIRBAND_BINARY), "-v"], timeout=4)
    match = re.search(r"(?i)\b(?:RTLSDR-Airband|rtl_airband)\s+v?(\d+\.\d+(?:\.\d+)?)\b", output)
    if match:
        return match.group(1), "binary"
    return None, "unverified custom binary"


def newer_than(local, upstream):
    """Compare only clean numeric release versions, never unknown text."""
    if not local or not upstream:
        return None
    match = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)", local)
    parsed = version_tuple(match.group(1)) if match else None
    target = version_tuple(upstream)
    if parsed is None or target is None:
        return None
    return parsed < target


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
    ais_latest = upstream.get("ais_release") or {}
    sat_latest = upstream.get("satdump_release") or {}
    readsb_latest = upstream.get("readsb_upstream") or {}
    air_latest = upstream.get("airband_release") or {}
    errors = upstream.get("errors") or {}
    candidate = _apt_version("satdump", "Candidate")
    installed_pkg = _apt_version("satdump", "Installed")
    satdump_binary = shutil.which("satdump")
    sat_installed, sat_method = installed_satdump_version(installed_pkg, satdump_binary)
    satdump_upgrade = bool(satdump_binary and installed_pkg and candidate and
                           _apt_newer(installed_pkg, candidate))
    sat_upstream_newer = newer_than(sat_installed, sat_latest.get("version"))
    readsb_info = command(["readsb", "--version"])
    readsb_match = re.search(r"readsb version:\s*(\d+\.\d+(?:\.\d+)?)",
                            readsb_info, re.I)
    readsb_installed = readsb_match.group(1) if readsb_match else None
    air_installed, air_method = installed_airband_version()
    readsb_newer = newer_than(readsb_installed, readsb_latest.get("version"))
    air_newer = newer_than(air_installed, air_latest.get("version"))
    ais_upgrade = bool(ais_installed and ais_latest.get("version") and
                       version_tuple(ais_latest["version"]) and version_tuple(ais_installed)
                       and version_tuple(ais_latest["version"]) > version_tuple(ais_installed))
    ais_manageable = bool(apt_ais_installed() and matching_ais_asset(ais_latest))
    ais_can_install = ais_upgrade and ais_manageable

    if satdump_upgrade:
        sat_status = "update"
        sat_reason = "Ubuntu APT update available"
    elif sat_method == "not-installed":
        sat_status, sat_reason = "missing", "SatDump is not installed"
    elif errors.get("satdump_release"):
        sat_status, sat_reason = "manual", "Stable release check unavailable"
    elif sat_upstream_newer:
        sat_status, sat_reason = "review", (
            "New stable release found; non-APT builds need a manual compatibility review"
            if not installed_pkg else "Newer upstream release; check your Ubuntu package")
    elif sat_upstream_newer is None:
        sat_status, sat_reason = "manual", (
            "Source build: exact installed version could not be verified"
            if not installed_pkg else "Installed package version could not be compared")
    else:
        sat_status, sat_reason = "current", (
            "Current stable release (nightly builds excluded)"
            if not installed_pkg else "No newer stable release or Ubuntu package")

    if readsb_installed is None:
        readsb_status = "missing" if not shutil.which("readsb") else "manual"
        readsb_reason = "Version not detected"
    elif errors.get("readsb_upstream"):
        readsb_status, readsb_reason = "manual", "Development version check unavailable"
    elif readsb_newer:
        readsb_status, readsb_reason = "review", (
            "Newer development build; SDRCC receiver integration must be tested before upgrading")
    elif readsb_newer is False:
        readsb_status, readsb_reason = "current", "Current with upstream dev branch"
    else:
        readsb_status, readsb_reason = "manual", "Version comparison unavailable"

    if air_method == "not-installed":
        air_status, air_reason = "missing", "Traffic Voice component not installed"
    elif errors.get("airband_release"):
        air_status, air_reason = "manual", "Stable release check unavailable"
    elif air_newer:
        air_status, air_reason = "review", (
            "New stable version; SDRCC Auto Gain and scan interval patches need porting")
    elif air_newer is False:
        air_status, air_reason = "current", "No newer stable release; SDRCC patches retained"
    else:
        air_status, air_reason = "manual", (
            "Installed binary version could not be verified; SDRCC patches may differ")

    rows = [
        {"id": "ais-catcher", "name": "AIS-catcher", "installed": ais_installed,
         "latest": ais_latest.get("version"), "available": ais_upgrade,
         "can_install": ais_can_install,
         "status": "update" if ais_can_install else
                   "review" if ais_upgrade else
                   "current" if ais_installed and ais_latest.get("version") else "manual",
         "source": "Official GitHub stable release",
         "url": ais_latest.get("url") or RELEASE_PAGE,
         "reason": (errors.get("ais_release") or "Installed version unavailable")
             if not (ais_installed and ais_latest.get("version")) else
             ("New upstream release available" if ais_can_install else
              "New release requires package/platform review" if ais_upgrade else "Up to date")},
        {"id": "satdump", "name": "SatDump", "installed": sat_installed or
         ("Source installation (version unknown)" if sat_method == "non-apt-unverified" else None),
         "latest": sat_latest.get("version"), "available": satdump_upgrade or sat_upstream_newer is True,
         "can_install": satdump_upgrade, "status": sat_status,
         "source": "Official stable releases + Ubuntu APT",
         "url": sat_latest.get("url") or SATDUMP_PAGE,
         "reason": sat_reason},
        {"id": "readsb", "name": "readsb", "installed": readsb_installed,
         "latest": readsb_latest.get("version"), "available": readsb_newer is True,
         "can_install": False, "status": readsb_status,
         "source": "GitHub development branch (not a stable release)",
         "url": READSB_PAGE,
         "reason": readsb_reason},
        {"id": "rtl-airband", "name": "RTLSDR-Airband",
         "installed": (air_installed + (" (" + air_method + ")" if air_method == "SDRCC patched" else ""))
                     if air_installed else None,
         "latest": air_latest.get("version"), "available": air_newer is True,
         "can_install": False, "status": air_status,
         "source": "Official stable releases / local build provenance",
         "url": air_latest.get("url") or AIRBAND_PAGE,
         "reason": air_reason},
    ]
    return {"ok": True, "software": rows, "worker": worker_status(),
            "release_check_error": errors.get("ais_release"),
            "release_check_errors": errors,
            "checked_at": datetime.now(timezone.utc).isoformat()}
