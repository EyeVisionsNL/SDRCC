#!/usr/bin/env python3
"""Synchronise readsb receiver position from SDRCC Home Position."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

READSB_CONFIG = Path("/etc/default/readsb")
READSB_SERVICE = "readsb.service"


class SyncError(RuntimeError):
    pass


def coordinate(value, minimum, maximum, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SyncError(f"{label} must be numeric") from error
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise SyncError(f"{label} outside valid range")
    return number


def strip_option(options, name):
    pattern = re.compile(
        rf"(^|[ \t])--{re.escape(name)}(?:=[^ \t\"]+|[ \t]+[^ \t\"]+)"
    )
    while True:
        options, count = pattern.subn(lambda match: match.group(1), options)
        if not count:
            break
    return " ".join(options.split())


def render(text, latitude, longitude):
    latitude = coordinate(latitude, -90.0, 90.0, "Latitude")
    longitude = coordinate(longitude, -180.0, 180.0, "Longitude")

    lines = text.splitlines(keepends=True)
    matches = []

    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if line.startswith("DECODER_OPTIONS="):
            matches.append((index, line))

    if len(matches) > 1:
        raise SyncError(
            f"Expected at most one active DECODER_OPTIONS line, found {len(matches)}"
        )

    position = f"--lat {latitude:.6f} --lon {longitude:.6f}"

    if not matches:
        suffix = "" if not text or text.endswith("\n") else "\n"
        return text + suffix + f'DECODER_OPTIONS="{position}"\n'

    index, line = matches[0]
    match = re.fullmatch(r'DECODER_OPTIONS="([^"\n]*)"[ \t]*\n?', line)
    if not match:
        raise SyncError(
            "Unrecognised DECODER_OPTIONS format; existing configuration preserved"
        )

    options = strip_option(match.group(1), "lat")
    options = strip_option(options, "lon")
    options = f"{position} {options}".strip()

    newline = "\n" if line.endswith("\n") else ""
    lines[index] = f'DECODER_OPTIONS="{options}"{newline}'
    return "".join(lines)


def atomic_write(path, text):
    previous = path.stat()

    backup = path.with_name(path.name + ".before-flexground-initialization")
    if not backup.exists():
        shutil.copy2(path, backup)

    fd, temporary = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".sdrcc-position.tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, previous.st_mode & 0o7777)
        os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def sync_file(path, latitude, longitude):
    if not path.exists():
        raise SyncError(f"readsb configuration missing: {path}")

    original = path.read_text(encoding="utf-8")
    updated = render(original, latitude, longitude)

    if updated == original:
        return False

    atomic_write(path, updated)
    return True


def systemctl(*args, check=True):
    result = subprocess.run(
        ["systemctl", *args],
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    if check and result.returncode:
        raise SyncError(
            (result.stderr or result.stdout or "systemctl failed").strip()
        )
    return result


def main():
    if os.geteuid() != 0:
        raise SystemExit("FAIL: root rights required")
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: sdrcc-sync-readsb-position LATITUDE LONGITUDE"
        )

    latitude = coordinate(sys.argv[1], -90.0, 90.0, "Latitude")
    longitude = coordinate(sys.argv[2], -180.0, 180.0, "Longitude")

    original = READSB_CONFIG.read_bytes()
    was_active = (
        systemctl("is-active", "--quiet", READSB_SERVICE, check=False).returncode == 0
    )

    try:
        changed = sync_file(READSB_CONFIG, latitude, longitude)

        if changed and was_active:
            systemctl("restart", READSB_SERVICE)
            if (
                systemctl(
                    "is-active", "--quiet", READSB_SERVICE, check=False
                ).returncode
                != 0
            ):
                raise SyncError("readsb did not become active after restart")

        print(json.dumps({
            "ok": True,
            "changed": changed,
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "readsb_restarted": bool(changed and was_active),
        }))
        return 0

    except Exception as error:
        try:
            READSB_CONFIG.write_bytes(original)
            if was_active:
                systemctl("restart", READSB_SERVICE, check=False)
        except Exception:
            pass

        print(json.dumps({
            "ok": False,
            "message": str(error),
            "rollback_performed": True,
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
