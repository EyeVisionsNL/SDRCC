#!/usr/bin/env python3
"""Restore SDRCC's dedicated AIS-catcher map companion without reinstalling radios.

Installs only sdrcc-mobile-atis.pjs in the existing AIS-catcher plugin folder.
No services, user configuration, passwords, other plugins or SDRCC runtime are
changed. Non-SDRCC files are never overwritten.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT / "dashboard/static/mobile/atis-highlight.pjs"
DEFAULT_TARGET = Path("/etc/AIS-catcher/plugins/sdrcc-mobile-atis.pjs")
MARKER = b"SDRCC-ATIS-MOBILE-BRIDGE"
MAX_BYTES = 25_000


def validated_source(source: Path) -> bytes:
    if source.is_symlink() or not source.is_file():
        raise RuntimeError(f"SDRCC plugin source missing or unsafe: {source}")
    data = source.read_bytes()
    if not data or len(data) > MAX_BYTES or MARKER not in data:
        raise RuntimeError("SDRCC AIS companion source marker/size verification failed")
    return data


def examine_target(target: Path, data: bytes) -> bool:
    """Return True when already installed. Reject unsafe paths or foreign files."""
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise RuntimeError(f"AIS-catcher plugin directory missing or unsafe: {parent}")
    if target.is_symlink():
        raise RuntimeError("Refusing to follow existing plugin symlink")
    if not target.exists():
        return False
    if not target.is_file():
        raise RuntimeError("Existing plugin target is not a regular file")
    old = target.read_bytes()
    if MARKER not in old:
        raise RuntimeError("Refusing to overwrite another author's AIS-catcher plugin")
    return old == data


def install(source: Path = DEFAULT_SOURCE, target: Path = DEFAULT_TARGET) -> str:
    data = validated_source(source)
    # Some clean upstream AIS installs do not create the optional plugins/
    # subdirectory. Create only that exact location and only beneath an
    # already-existing, non-symlinked AIS-catcher configuration directory.
    if (target == DEFAULT_TARGET and not target.parent.exists()):
        config_dir = target.parent.parent
        if not config_dir.is_dir() or config_dir.is_symlink():
            raise RuntimeError(f"AIS-catcher configuration directory missing or unsafe: {config_dir}")
        target.parent.mkdir(mode=0o755)
    if examine_target(target, data):
        return f"PASS: SDRCC AIS map plugin already installed: {target}"
    # Atomic replacement; do not disturb unrelated plugins or alter AIS services.
    parent = target.parent
    old_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o644
    fd, staging = tempfile.mkstemp(prefix=".sdrcc-atis-", dir=str(parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(staging, old_mode)
        os.replace(staging, target)
    finally:
        if os.path.lexists(staging):
            os.unlink(staging)
    return f"PASS: SDRCC AIS map plugin restored: {target}"


def check(source: Path = DEFAULT_SOURCE, target: Path = DEFAULT_TARGET) -> bool:
    data = validated_source(source)
    if examine_target(target, data):
        print(f"PASS: SDRCC AIS-catcher plugin installed: {target}")
        return True
    print(f"MISSING: SDRCC AIS-catcher plugin at {target}")
    return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    task = parser.add_mutually_exclusive_group(required=True)
    task.add_argument("--install", action="store_true")
    task.add_argument("--check", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    try:
        if args.install:
            if os.geteuid() != 0:
                parser.error("--install requires sudo (only this plugin file is written)")
            print(install(args.source))
            print("Enable the SDRCC plugin in AIS-catcher's plugin selector if needed,")
            print("then refresh its map. No AIS service was restarted.")
            return 0
        return 0 if check(args.source) else 2
    except (OSError, RuntimeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
