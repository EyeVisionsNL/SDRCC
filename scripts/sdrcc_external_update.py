#!/usr/bin/env python3
"""Privileged, opt-in third-party updater. Fixed allowlisted product arguments.

The dashboard may call this *launcher*, never the worker. A detached systemd
unit completes the update without being killed by an HTTP timeout.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

SELF = Path("/usr/local/sbin/sdrcc-external-update")
STATUS = Path("/var/lib/sdrcc/external-update-status.json")
LOCK = Path("/run/lock/sdrcc-external-update.lock")
UPDATE_UNIT = "sdrcc-external-update"
ALLOWED = {"ais-catcher", "satdump", "readsb", "rtl-airband"}
AIS_CONFIG = Path("/etc/AIS-catcher")
AIS_SERVICE = "ais-catcher.service"
AIS_CONTROL = "ais-catcher-control.service"
UPSTREAM_TEMPLATE = "https://raw.githubusercontent.com/jvde-github/AIS-catcher/{tag}/scripts/aiscatcher-install"


def run(args, timeout=45, check=False, **kwargs):
    result = subprocess.run([str(v) for v in args], capture_output=True,
                            text=True, timeout=timeout, check=False, **kwargs)
    if check and result.returncode:
        raise RuntimeError(f"Command failed: {args[0]} (exit {result.returncode})")
    return result


def status(state, message, **extra):
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "message": message, "updated_at":
               datetime.now(timezone.utc).isoformat(), **extra}
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o644)
    os.replace(tmp, STATUS)


def active(unit):
    return run(["/usr/bin/systemctl", "is-active", "--quiet", unit],
               timeout=10).returncode == 0


def enabled(unit):
    return run(["/usr/bin/systemctl", "is-enabled", "--quiet", unit],
               timeout=10).returncode == 0


def service(action, name):
    run(["/usr/bin/systemctl", action, name], timeout=50, check=True)


def restore_service_states(was):
    problems = []
    try:
        run(["/usr/bin/systemctl", "daemon-reload"], timeout=30, check=True)
    except Exception:
        problems.append("systemd reload")
    for name in (AIS_SERVICE, AIS_CONTROL):
        try:
            service("enable" if was[name]["enabled"] else "disable", name)
        except Exception:
            problems.append("boot policy " + name)
    for name in (AIS_SERVICE, AIS_CONTROL):
        try:
            service("start" if was[name]["active"] else "stop", name)
            if was[name]["active"] and not active(name):
                problems.append("service did not remain active: " + name)
        except Exception:
            problems.append("service restore " + name)
    return problems


def safe_copy(src, dest):
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
    elif src.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def restore_from_backup(backup, binary_path):
    errors = []
    try:
        if (backup / "AIS-catcher").exists() and binary_path:
            shutil.copy2(backup / "AIS-catcher", binary_path)
    except Exception:
        errors.append("original AIS executable")
    try:
        if (backup / "config").is_dir():
            shutil.copytree(backup / "config", AIS_CONFIG, dirs_exist_ok=True,
                            symlinks=True)
    except Exception:
        errors.append("AIS configuration")
    for target, saved in (
        (Path("/etc/systemd/system/ais-catcher.service"), backup / "ais-unit"),
        (Path("/etc/systemd/system/ais-catcher.service.d"), backup / "ais-dropins"),
    ):
        try:
            safe_copy(saved, target)
        except Exception:
            errors.append("AIS systemd configuration")
    return errors


def install_ais(external, backup):
    from core.external_updates import ais_version, version_tuple, release
    current = ais_version(external.command(["AIS-catcher", "-v"]))
    latest = release(refresh=True).get("ais_release") or {}
    tag = latest.get("tag", "")
    if not current or not re.fullmatch(r"v\d+\.\d+(?:\.\d+)?", tag):
        raise RuntimeError("AIS version or trusted release cannot be verified")
    if not (version_tuple(tag[1:]) > version_tuple(current)):
        raise RuntimeError("No newer AIS-catcher release is available")
    if not Path("/etc/AIS-catcher/aiscatcher.json").is_file():
        raise RuntimeError("Managed AIS configuration missing; refusing unattended upgrade")
    unit_definition = run(["/usr/bin/systemctl", "cat", AIS_SERVICE], timeout=10)
    if "-E /etc/AIS-catcher/aiscatcher.json 0.0.0.0:8118" not in unit_definition.stdout:
        raise RuntimeError("SDRCC AIS managed-mode port 8118 service guard failed")
    binary = shutil.which("AIS-catcher")
    if not binary or not Path(binary).is_file():
        raise RuntimeError("AIS-catcher executable not found")
    safe_copy(AIS_CONFIG, backup / "config")
    safe_copy(Path(binary), backup / "AIS-catcher")
    safe_copy(Path("/etc/systemd/system/ais-catcher.service"), backup / "ais-unit")
    safe_copy(Path("/etc/systemd/system/ais-catcher.service.d"), backup / "ais-dropins")
    if not external.apt_ais_installed():
        raise RuntimeError("AIS-catcher was not installed as an APT package")
    asset = external.matching_ais_asset(latest)
    if not asset:
        raise RuntimeError("No official, checksum-verified stable package for this Ubuntu release")
    request = Request(asset["url"], headers={"User-Agent": "SDRCC-external-updater"})
    with tempfile.TemporaryDirectory(prefix="sdrcc-ais-stable-", dir="/var/tmp") as directory:
        package = Path(directory) / asset["name"]
        with urlopen(request, timeout=30) as response, package.open("wb") as out:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > asset["size"]:
                    raise RuntimeError("Unexpected AIS package download size")
                digest.update(chunk)
                out.write(chunk)
        if size != asset["size"] or "sha256:" + digest.hexdigest() != asset["digest"]:
            raise RuntimeError("AIS stable package SHA256 verification failed")
        pkg_name = run(["/usr/bin/dpkg-deb", "-f", package, "Package"],
                       timeout=20, check=True).stdout.strip()
        pkg_version = run(["/usr/bin/dpkg-deb", "-f", package, "Version"],
                          timeout=20, check=True).stdout.strip()
        if pkg_name != "ais-catcher" or not pkg_version.startswith(tag[1:]):
            raise RuntimeError("AIS package identity or version mismatch")
        status("installing", "Installing checksum-verified official AIS release " + tag + ".",
               software="ais-catcher")
        run(["/usr/bin/apt-get", "install", "-y",
             "-o", "Dpkg::Options::=--force-confold", package],
            timeout=600, check=True,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    installed = ais_version(external.command(["AIS-catcher", "-v"]))
    if not installed or version_tuple(installed) < version_tuple(tag[1:]):
        raise RuntimeError("AIS executable version did not match requested release")
    # Restore receiver settings unconditionally; the official installer should
    # keep them, but protect our configuration if its behavior changes.
    shutil.copytree(backup / "config", AIS_CONFIG, dirs_exist_ok=True,
                    symlinks=True)
    safe_copy(backup / "ais-unit", Path("/etc/systemd/system/ais-catcher.service"))
    safe_copy(backup / "ais-dropins", Path("/etc/systemd/system/ais-catcher.service.d"))
    config = run(["/usr/bin/systemctl", "cat", AIS_SERVICE], timeout=10, check=True)
    if "-E /etc/AIS-catcher/aiscatcher.json 0.0.0.0:8118" not in config.stdout:
        raise RuntimeError("AIS managed-mode service override no longer specifies port 8118")
    return installed


def install_satdump(external, backup):
    installed = external._apt_version("satdump", "Installed")
    candidate = external._apt_version("satdump", "Candidate")
    if not installed or not candidate or not external._apt_newer(installed, candidate):
        raise RuntimeError("SatDump is not APT-managed or has no newer Ubuntu package")
    # apt-get --only-upgrade never migrates a source-based SatDump install.
    status("installing", "Upgrading SatDump and its data package with Ubuntu APT.",
           software="satdump")
    run(["/usr/bin/apt-get", "update", "-qq"], timeout=240, check=True,
        env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    # Fresh APT metadata may supersede the earlier candidate, but only install
    # packages already known to Ubuntu's configured package repositories.
    run(["/usr/bin/apt-get", "install", "-y", "--only-upgrade",
         "-o", "Dpkg::Options::=--force-confold", "satdump", "satdump-data"],
        timeout=600, check=True, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
    installed_now = external._apt_version("satdump", "Installed")
    if not installed_now or not external._apt_newer(installed, installed_now):
        raise RuntimeError("SatDump APT did not install a newer package")
    return installed_now


def project_root():
    receipt = Path("/var/lib/sdrcc/install-receipt").read_text(encoding="utf-8")
    line = next((row.split("=", 1)[1] for row in receipt.splitlines()
                 if row.startswith("project_root_b64=")), "")
    project = Path(base64.b64decode(line, validate=True).decode("utf-8")).resolve()
    if not (project / "VERSION").is_file() or not (project / "core/external_updates.py").is_file():
        raise RuntimeError("SDRCC project not found")
    return project


def worker(product):
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w") as file:
        try:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 3
        from core import external_updates as external
        if active("sdrcc-update.service"):
            status("failed", "SDRCC code updater is active.", software=product)
            return 3
        backup = None
        previous = None
        binary = None
        try:
            status("starting", "Verifying external update requirements.", software=product)
            if product == "ais-catcher":
                previous = {name: {"active": active(name), "enabled": enabled(name)}
                            for name in (AIS_SERVICE, AIS_CONTROL)}
                binary = shutil.which("AIS-catcher")
                path = Path("/var/lib/sdrcc/external-backups")
                path.mkdir(parents=True, exist_ok=True)
                os.chmod(path, 0o700)
                backup = Path(tempfile.mkdtemp(prefix="ais-", dir=path))
                os.chmod(backup, 0o700)
                # Keep AIS sharing and its control service in a known state
                # while the official installer replaces packages.
                status("backing_up", "Saving AIS settings and service state.", software=product)
                for name in (AIS_CONTROL, AIS_SERVICE):
                    if active(name):
                        service("stop", name)
                installed = install_ais(external, backup)
            elif product == "satdump":
                installed = install_satdump(external, None)
            elif product in {"readsb", "rtl-airband"}:
                from scripts.install import upgrade_radio_runtimes
                def progress(state, message):
                    status(state, message, software=product)
                installed = upgrade_radio_runtimes.upgrade(
                    product, project_root(), progress)
            else:
                raise RuntimeError("Unsupported update target")
            status("verifying", "Checking updated installation.", software=product)
            problems = restore_service_states(previous) if previous else []
            previous = None
            if problems:
                raise RuntimeError("Update installed but service restore needs attention: "
                                   + ", ".join(problems))
            status("success", f"{product} updated to {installed}.", software=product,
                   installed_version=installed)
            return 0
        except Exception as exc:
            errors = []
            if product == "ais-catcher" and backup is not None:
                errors = restore_from_backup(backup, binary)
            if previous:
                errors.extend(restore_service_states(previous))
            message = str(exc)[:210]
            if errors:
                message += "; recovery needs attention: " + ", ".join(errors)
            status("failed", message, software=product, backup_available=bool(backup))
            return 1


def launch(product):
    if active(UPDATE_UNIT + ".service") or active("sdrcc-update.service"):
        print(json.dumps({"ok": False, "message": "An update is already running."}))
        return 3
    status("queued", "External update queued.", software=product)
    result = run(["/usr/bin/systemd-run", "--quiet", "--no-block", "--collect",
                  f"--unit={UPDATE_UNIT}", "--property=Type=exec",
                  str(SELF), "--worker", product], timeout=30)
    if result.returncode:
        status("failed", "Unable to start external update worker.", software=product)
        print(json.dumps({"ok": False, "message": "Could not start update worker."}))
        return 1
    print(json.dumps({"ok": True, "message": "External update started."}))
    return 0


def main():
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "message": "Root rights required."}))
        return 1
    if len(sys.argv) not in (2, 3):
        return 2
    if len(sys.argv) == 2 and sys.argv[1] in ALLOWED:
        return launch(sys.argv[1])
    if len(sys.argv) == 3 and sys.argv[1] == "--worker" and sys.argv[2] in ALLOWED:
        root = project_root()
        sys.path.insert(0, str(root))
        return worker(sys.argv[2])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
