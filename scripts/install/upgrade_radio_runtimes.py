#!/usr/bin/env python3
"""Pinned SDRCC radio runtime upgrades.

Imported only by the privileged detached external-update worker. Never runs
during a normal SDRCC repository update; does not take control of SDR hardware.
Builds and verifies the new binary before replacing the existing one.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

READSB_URL = "https://github.com/wiedehopf/readsb.git"
READSB_OLD = "cc0d099"
READSB_NEW = "dadfa3307a1951b7ef687cfe3fd66cdb708a4f6f"
READSB_VERSION = "3.16.20"
AIRBAND_URL = "https://github.com/rtl-airband/RTLSDR-Airband.git"
AIRBAND_TAG = "v6.2.0"
AIRBAND_SHA = "66d3076819312c7eae7662028234988dc71d0be5"
AIRBAND_OLD_SHA = "61c5c4061967752da6b491a924664d72184b38fa"
AIRBAND_ROOT = Path("/opt/sdrcc/traffic_voice")
AIRBAND_BIN = AIRBAND_ROOT / "bin/rtl_airband"
AIRBAND_PROVENANCE = AIRBAND_ROOT / "share/BUILD-PROVENANCE"
TRAFFIC_UNIT = "sdrcc-traffic-voice.service"
READSB_UNIT = "readsb.service"


def call(args, *, cwd=None, timeout=180, env=None):
    result = subprocess.run(
        [str(part) for part in args], cwd=cwd, timeout=timeout,
        env=env, check=False, text=True, capture_output=True)
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"{Path(str(args[0])).name} exit {result.returncode}: {detail[-450:]}")
    return result.stdout


def inactive(unit):
    if subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", unit],
                      capture_output=True, timeout=12).returncode == 0:
        raise RuntimeError(f"Stop {unit} in SDRCC before installing its update")


def git_checkout(path, remote, commit, *, branch=None):
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("Source commit must be pinned to the full 40-character SHA")
    call(["git", "init", "-q", path])
    call(["git", "-C", path, "remote", "add", "origin", remote])
    if branch:
        # Keep the actual Git tag in this shallow checkout. Merely fetching
        # FETCH_HEAD can leave 'git describe --tags' without a version.
        if not re.fullmatch(r"v\d+\.\d+\.\d+", branch):
            raise ValueError("Unsupported pinned release tag")
        tag_ref = f"refs/tags/{branch}"
        call(["git", "-C", path, "fetch", "--depth", "1", "origin",
              f"{tag_ref}:{tag_ref}"], timeout=180)
        checkout_ref = tag_ref
    else:
        call(["git", "-C", path, "fetch", "--depth", "1", "origin", commit],
             timeout=180)
        checkout_ref = "FETCH_HEAD"
    call(["git", "-C", path, "checkout", "--quiet", "--detach", checkout_ref])
    actual = call(["git", "-C", path, "rev-parse", "HEAD"]).strip()
    if actual != commit:
        raise RuntimeError(f"Source moved from pinned commit: {actual}")
    if branch:
        resolved_tag = call(["git", "-C", path, "describe", "--tags",
                             "--exact-match"]).strip()
        if resolved_tag != branch:
            raise RuntimeError(f"Pinned release tag missing: expected {branch}")
    return actual


def _copy_if_exists(src, dest):
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return True
    return False


def _service_enabled(unit):
    return subprocess.run(["/usr/bin/systemctl", "is-enabled", "--quiet", unit],
                          capture_output=True, timeout=12).returncode == 0


def _restore_readsb_service(enabled):
    # The receiver must remain stopped. Never restart the hardware following
    # a code upgrade; SDRCC's Mission Engine owns that decision.
    call(["systemctl", "stop", READSB_UNIT], timeout=55)
    call(["systemctl", "enable" if enabled else "disable", READSB_UNIT], timeout=55)


def _build_readsb(work, sha):
    src = work / "readsb"
    src.mkdir()
    git_checkout(src, READSB_URL, sha)
    env = {**os.environ, "DEB_BUILD_OPTIONS": "noddebs"}
    call(["dpkg-buildpackage", "-b", "-ui", "-uc", "-us",
          "--build-profiles=rtlsdr"], cwd=src, env=env, timeout=1500)
    packages = sorted(work.glob("readsb_*.deb"))
    if len(packages) != 1:
        raise RuntimeError(f"readsb build expected one package, got {len(packages)}")
    package_name = call(["dpkg-deb", "-f", packages[0], "Package"]).strip()
    if package_name != "readsb":
        raise RuntimeError("Built package is not readsb")
    return packages[0]


def update_readsb(project, backup, report):
    from core.external_updates import command, newer_than
    output = command(["readsb", "--version"])
    match = re.search(r"readsb version:\s*(\d+\.\d+(?:\.\d+)?)", output, re.I)
    if not match or not newer_than(match.group(1), READSB_VERSION):
        raise RuntimeError("Installed readsb version is unknown or already current")
    # Only upgrade the exact original SDRCC-pinned build. Other local
    # modifications must never be overwritten by the dashboard.
    if "cc0d099" not in output or match.group(1) != "3.16.15":
        raise RuntimeError("readsb is not SDRCC's original pinned build; manual review required")
    inactive(READSB_UNIT)
    if not call(["dpkg-query", "-W", "-f=${Status}", "readsb"]).strip().endswith(
            "installed"):
        raise RuntimeError("readsb is not installed as a Debian package")
    previous_enabled = _service_enabled(READSB_UNIT)
    _copy_if_exists(Path("/etc/default/readsb"), backup / "readsb-default")
    _copy_if_exists(Path("/etc/systemd/system/readsb.service"),
                    backup / "readsb-unit")
    backup_package = None
    install_started = False
    try:
        report("backing_up", "Building original readsb rollback package before upgrade.")
        old_dir = backup / "old-build"
        old_dir.mkdir()
        # Confirm old version from its source tag via the same reproducible
        # Debian packaging pipeline; never delete rollback package.
        git_short = READSB_OLD
        old_src = old_dir / "readsb"
        call(["git", "clone", "--quiet", READSB_URL, old_src], timeout=200)
        call(["git", "-C", old_src, "checkout", "--quiet", git_short])
        if not call(["git", "-C", old_src, "rev-parse", "--short=7", "HEAD"]).strip().startswith(git_short):
            raise RuntimeError("Old readsb rollback commit mismatch")
        env = {**os.environ, "DEB_BUILD_OPTIONS": "noddebs"}
        call(["dpkg-buildpackage", "-b", "-ui", "-uc", "-us",
              "--build-profiles=rtlsdr"], cwd=old_src, env=env, timeout=1500)
        old_debs = list(old_dir.glob("readsb_*.deb"))
        if len(old_debs) != 1:
            raise RuntimeError("Could not build original readsb rollback package")
        backup_package = backup / old_debs[0].name
        shutil.copy2(old_debs[0], backup_package)
        report("installing", "Building pinned readsb 3.16.20 without touching running receivers.")
        new_dir = backup / "new-build"
        new_dir.mkdir()
        candidate = _build_readsb(new_dir, READSB_NEW)
        version = call(["dpkg-deb", "-f", candidate, "Version"]).strip()
        if not version.startswith(READSB_VERSION):
            raise RuntimeError("Built readsb package has an unexpected version")
        # Catch a service that became active while the package was compiling.
        inactive(READSB_UNIT)
        report("installing", "Installing pinned readsb 3.16.20 Debian package.")
        install_started = True
        call(["apt-get", "install", "-y", "--allow-downgrades",
              "-o", "Dpkg::Options::=--force-confold", candidate],
             timeout=500, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
        _restore_readsb_service(previous_enabled)
        _copy_if_exists(backup / "readsb-default", Path("/etc/default/readsb"))
        _copy_if_exists(backup / "readsb-unit",
                        Path("/etc/systemd/system/readsb.service"))
        call(["systemctl", "daemon-reload"])
        updated = command(["readsb", "--version"])
        if READSB_VERSION not in updated:
            raise RuntimeError("readsb did not report 3.16.20 after installation")
        return READSB_VERSION
    except Exception as error:
        if install_started and backup_package:
            try:
                report("restoring", "Restoring previous readsb Debian package.")
                call(["apt-get", "install", "-y", "--allow-downgrades",
                      "-o", "Dpkg::Options::=--force-confold", backup_package],
                     timeout=500,
                     env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})
            except Exception as rollback:
                raise RuntimeError(f"{error}; rollback also failed: {rollback}") from rollback
        raise
    finally:
        if install_started:
            _copy_if_exists(backup / "readsb-default", Path("/etc/default/readsb"))
            _copy_if_exists(backup / "readsb-unit",
                            Path("/etc/systemd/system/readsb.service"))
            call(["systemctl", "daemon-reload"])
            _restore_readsb_service(previous_enabled)


def build_airband_candidate(project: Path, work: Path) -> Path:
    """Stage the exact production build, including version and patch checks.

    RTLSDR-Airband's scripts/find_version calls git describe in the process
    working directory. CMake MUST run with cwd=source, not the systemd
    worker's current directory (which is not a Git checkout).
    """
    source = work / "source"
    source.mkdir()
    git_checkout(source, AIRBAND_URL, AIRBAND_SHA, branch=AIRBAND_TAG)
    call([sys.executable,
          project / "scripts/install/patch_rtlsdr_airband_auto_gain.py",
          source / "src/input-rtlsdr.cpp"])
    call([sys.executable,
          project / "scripts/install/patch_rtlsdr_airband_scan_interval.py",
          source / "src/rtl_airband.cpp"])
    # Check the upstream version helper in the same working directory that
    # will be used during configuration. Patched sources report v6.2.0-dirty.
    detected_version = call([source / "scripts/find_version"], cwd=source).strip()
    if not (detected_version == AIRBAND_TAG
            or detected_version.startswith(AIRBAND_TAG + "-")):
        raise RuntimeError(
            f"RTLSDR-Airband source version check failed: {detected_version!r}")
    build = work / "build"
    call(["cmake", "-S", source, "-B", build, "-DNFM=ON",
          "-DRTLSDR=ON", "-DMIRISDR=OFF", "-DSOAPYSDR=OFF",
          "-DPULSEAUDIO=OFF", "-DPLATFORM=native"],
         cwd=source, timeout=180)
    call(["cmake", "--build", build, "-j", str(min(4, os.cpu_count() or 2))],
         timeout=900)
    candidates = [entry for entry in build.rglob("rtl_airband")
                  if entry.is_file() and os.access(entry, os.X_OK)]
    if len(candidates) != 1:
        raise RuntimeError("Expected exactly one built Airband executable")
    candidate = candidates[0]
    strings = candidate.read_bytes()
    if (b"automatic tuner gain enabled" not in strings or
            b"scan_interval_ms must be 100..500 ms" not in strings):
        raise RuntimeError("SDRCC gain or scan patch marker missing")
    return candidate


def update_airband(project, backup, report):
    from core.external_updates import installed_airband_version
    version, method = installed_airband_version()
    if version != "5.2.0" or method != "SDRCC patched":
        raise RuntimeError("Only SDRCC's original patched Airband 5.2.0 can be upgraded automatically")
    if not AIRBAND_BIN.is_file() or not AIRBAND_PROVENANCE.is_file():
        raise RuntimeError("Original SDRCC Airband binary/provenance missing")
    provenance = AIRBAND_PROVENANCE.read_text(encoding="utf-8")
    if (AIRBAND_OLD_SHA not in provenance or
            "SDRCC v0.56.0f auto-gain patch" not in provenance or
            "SDRCC v0.56.0w scan-interval patch" not in provenance):
        raise RuntimeError("Unrecognised Airband source or custom patch set")
    inactive(TRAFFIC_UNIT)
    config = project / "config/traffic_voice.yaml"
    original_config = config.read_text(encoding="utf-8")
    old_version = "    version: 5.2.0\n"
    old_commit = "    commit: " + AIRBAND_OLD_SHA + "\n"
    if original_config.count(old_version) != 1 or original_config.count(old_commit) != 1:
        raise RuntimeError("Traffic Voice backend metadata is not the expected legacy version")
    replacement = original_config.replace(old_version, "    version: 6.2.0\n", 1).replace(
        old_commit, "    commit: " + AIRBAND_SHA + "\n", 1)
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AIRBAND_BIN, backup / "rtl_airband")
    shutil.copy2(AIRBAND_PROVENANCE, backup / "BUILD-PROVENANCE")
    shutil.copy2(config, backup / "traffic_voice.yaml")
    install_started = False
    try:
        report("installing", "Building patched RTLSDR-Airband 6.2.0 in a staging directory.")
        with tempfile.TemporaryDirectory(prefix="sdrcc-airband-src-") as work:
            candidate = build_airband_candidate(project, Path(work))
            # Validation before downtime, including SDRCC's own two supported
            # backend-version contracts.
            import yaml
            from core import traffic_voice
            data = yaml.safe_load(replacement)
            result = traffic_voice.validate_configuration(data)
            if not result.get("ok"):
                raise RuntimeError("Traffic Voice 6.2.0 config validation failed: "
                                   + "; ".join(result["errors"][:3]))
            inactive(TRAFFIC_UNIT)
            report("installing", "Replacing idle Airband binary, recording source and updating metadata.")
            installed_temp = AIRBAND_BIN.with_name(".rtl_airband-sdrcc-upgrade")
            shutil.copy2(candidate, installed_temp)
            os.chmod(installed_temp, 0o755)
            install_started = True
            os.replace(installed_temp, AIRBAND_BIN)
            provenance_path = AIRBAND_PROVENANCE.with_suffix(".pending")
            provenance_path.write_text(
                "RTLSDR-Airband 6.2.0\n"
                f"commit {AIRBAND_SHA}\n"
                f"source git tag {AIRBAND_TAG}\n"
                "build options NFM=ON RTLSDR=ON MIRISDR=OFF SOAPYSDR=OFF PULSEAUDIO=OFF PLATFORM=native\n"
                "SDRCC v0.56.0f auto-gain patch\n"
                "behavior gain<0 => rtlsdr_set_tuner_gain_mode(dev,0); gain>=0 => existing manual path\n"
                "SDRCC v0.56.0w scan-interval patch\n"
                "behavior scan_interval_ms=100..500 in 50 ms steps; default 200 ms\n",
                encoding="utf-8")
            os.chmod(provenance_path, 0o644)
            os.replace(provenance_path, AIRBAND_PROVENANCE)
            cfg_pending = config.with_suffix(config.suffix + ".sdrcc-upgrade")
            cfg_pending.write_text(replacement, encoding="utf-8")
            os.replace(cfg_pending, config)
            return "6.2.0"
    except Exception:
        if install_started:
            shutil.copy2(backup / "rtl_airband", AIRBAND_BIN)
            shutil.copy2(backup / "BUILD-PROVENANCE", AIRBAND_PROVENANCE)
            shutil.copy2(backup / "traffic_voice.yaml", config)
        raise


def upgrade(product, project, report):
    base = Path("/var/lib/sdrcc/external-backups")
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    backup = Path(tempfile.mkdtemp(prefix=product + "-", dir=base))
    os.chmod(backup, 0o700)
    if product == "readsb":
        return update_readsb(project, backup, report)
    if product == "rtl-airband":
        return update_airband(project, backup, report)
    raise ValueError("Unsupported radio runtime")
