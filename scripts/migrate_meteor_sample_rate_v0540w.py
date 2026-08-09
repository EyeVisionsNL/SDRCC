#!/usr/bin/env python3
"""Correct only the two configured METEOR LRPT sample rates."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "satellites.yaml"
METEOR_NAMES = ("METEOR-M2 3", "METEOR-M2 4")
OLD_SAMPLE_RATE = 1_000_000
TARGET_SAMPLE_RATE = 1_024_000


def fail(message: str) -> None:
    raise SystemExit(message)


def satellite_block(lines: list[str], name: str) -> tuple[int, int, int]:
    heading = re.compile(rf"^(?P<indent>\s*){re.escape(name)}:\s*(?:#.*)?(?:\r?\n)?$")
    for start, line in enumerate(lines):
        match = heading.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        end = len(lines)
        for index in range(start + 1, len(lines)):
            candidate = lines[index]
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                continue
            candidate_indent = len(candidate) - len(candidate.lstrip())
            if candidate_indent <= indent:
                end = index
                break
        return start, end, indent
    fail(f"Missing satellite block: {name}")


def migrate(path: Path = CONFIG_FILE) -> bool:
    original_text = path.read_text(encoding="utf-8")
    original = yaml.safe_load(original_text) or {}
    satellites = original.get("satellites")
    if not isinstance(satellites, dict):
        fail("config/satellites.yaml has no satellites mapping")

    for name in METEOR_NAMES:
        profile = satellites.get(name)
        if not isinstance(profile, dict):
            fail(f"Missing METEOR profile: {name}")
        value = profile.get("sample_rate")
        if value not in {OLD_SAMPLE_RATE, TARGET_SAMPLE_RATE}:
            fail(f"Unexpected {name} sample_rate: {value!r}")

    lines = original_text.splitlines(keepends=True)
    changed = False
    for name in METEOR_NAMES:
        if satellites[name]["sample_rate"] == TARGET_SAMPLE_RATE:
            continue
        start, end, heading_indent = satellite_block(lines, name)
        matches: list[int] = []
        for index in range(start + 1, end):
            line = lines[index]
            line_indent = len(line) - len(line.lstrip())
            if line_indent <= heading_indent:
                continue
            if re.match(r"^\s*sample_rate\s*:", line):
                matches.append(index)
        if len(matches) != 1:
            fail(f"Expected one sample_rate line in {name}, found {len(matches)}")
        index = matches[0]
        replaced, count = re.subn(
            rf"^(\s*sample_rate\s*:\s*){OLD_SAMPLE_RATE}(\s*(?:#.*)?(?:\r?\n)?)$",
            rf"\g<1>{TARGET_SAMPLE_RATE}\g<2>",
            lines[index],
        )
        if count != 1:
            fail(f"Could not safely update {name} sample_rate")
        lines[index] = replaced
        changed = True

    updated_text = "".join(lines)
    updated = yaml.safe_load(updated_text) or {}
    expected = deepcopy(original)
    for name in METEOR_NAMES:
        expected["satellites"][name]["sample_rate"] = TARGET_SAMPLE_RATE
    if updated != expected:
        fail("Migration changed data outside the two METEOR sample_rate fields")

    if not changed:
        print("METEOR sample rates already set to 1024000 S/s")
        return False

    temp_path = path.with_name(f".{path.name}.v0540w.tmp")
    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(updated_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, path.stat().st_mode & 0o777)
        temp_path.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp_path.unlink(missing_ok=True)

    print("Updated METEOR-M2 3 and METEOR-M2 4 to 1024000 S/s")
    return True


if __name__ == "__main__":
    migrate()
