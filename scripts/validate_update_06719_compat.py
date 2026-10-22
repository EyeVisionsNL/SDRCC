#!/usr/bin/env python3
"""Regression for upgrades from SDRCC v0.67.19 without satellite receivers.

Known upstream 0.67.19 file digests must be approved, while actual local edits
must remain blocked by the managed update source check.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/install/check_update.py"
MANIFEST = ROOT / "scripts/install/update_manifest.json"

OFFICIAL_06719_SHA256 = {
    "core/iss_passes.py": "64133f8aa268b37f43f68cd381807d2b8f5e6f8893482712f16a8c6cc0a1aa13",
    "core/passes.py": "68dd6620644494a0e30ad4d7477af21712338acfd0685e35255d2a4bdc6db541",
    "core/satellite_view.py": "974f6e3fbd02c8eefabc5eae86871324f0506caf37eb8ee09c0340a6763532db",
    "dashboard/static/js/home_position.js": "ca76af936f322841300cf1722ecbc8a38bea73a8e29114751aa63fccf640d2ef",
}


def main() -> None:
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for path, historical_sha in OFFICIAL_06719_SHA256.items():
        assert historical_sha in m[path], f"Missing official 0.67.19 hash: {path}"
        # Also verify current source is approved, not just the legacy variant.
        digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert digest in m[path], f"Current source no longer approved: {path}"

    assert not any(path.startswith((".github/", "docs/")) for path in m), (
        "GitHub-only and internal docs must not be part of the deployed source"
    )

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        source, target = base / "source", base / "target"
        (source / "scripts/install").mkdir(parents=True)
        target.mkdir()
        source_file = source / "core/passes.py"
        source_file.parent.mkdir()
        source_file.write_text("new upstream code\n", encoding="utf-8")
        target_file = target / "core/passes.py"
        target_file.parent.mkdir()
        target_file.write_text("old upstream code\n", encoding="utf-8")
        approved = [
            hashlib.sha256(source_file.read_bytes()).hexdigest(),
            hashlib.sha256(target_file.read_bytes()).hexdigest(),
        ]
        (source / "scripts/install/update_manifest.json").write_text(
            json.dumps({"core/passes.py": approved}), encoding="utf-8"
        )

        def check():
            return subprocess.run(
                [sys.executable, str(CHECK), str(source), str(target)],
                text=True, capture_output=True, timeout=12, check=False
            )

        clean = check()
        assert clean.returncode == 0, clean.stdout + clean.stderr

        target_file.write_text("locally customized code\n", encoding="utf-8")
        changed = check()
        assert changed.returncode != 0
        assert "locally modified source core/passes.py" in (
            changed.stdout + changed.stderr
        ), changed.stdout + changed.stderr

        # On a marine/ADS-B-only installation, satellite code may not exist
        # locally. The source integrity check must still pass.
        target_file.unlink()
        without_satellite = check()
        assert without_satellite.returncode == 0, (
            without_satellite.stdout + without_satellite.stderr
        )

    print("PASS: historical 0.67.19 digests approved; custom edits blocked; missing optional target allowed")


if __name__ == "__main__":
    main()
