#!/usr/bin/env python3
"""Regression: CI-only GitHub workflows must never block SDRCC updates.

Runs with temporary source and project trees; touches no receiver or service.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "scripts/install/check_update.py"
MANIFEST = ROOT / "scripts/install/update_manifest.json"


def main() -> None:
    actual = json.loads(MANIFEST.read_text(encoding="utf-8"))
    forbidden = [p for p in actual if p == ".github" or p.startswith(".github/")]
    assert not forbidden, f"CI-only paths accidentally added to update manifest: {forbidden}"

    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        source, target = base / "source", base / "installed"
        source.mkdir()
        target.mkdir()
        (source / "VERSION").write_text("test-beta\n", encoding="utf-8")
        (source / "scripts/install").mkdir(parents=True)
        digest = hashlib.sha256((source / "VERSION").read_bytes()).hexdigest()
        manifest = {"VERSION": [digest]}
        manifest_file = source / "scripts/install/update_manifest.json"

        # An older local GitHub Actions file is NOT part of the deployed code,
        # so it must never prevent updating runtime source files.
        old_workflow = target / ".github/workflows/installer-step1.yml"
        old_workflow.parent.mkdir(parents=True)
        old_workflow.write_text("older GitHub Actions workflow\n", encoding="utf-8")

        def check():
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(CHECK), str(source), str(target)],
                text=True, capture_output=True, check=False, timeout=10
            )

        allowed = check()
        assert allowed.returncode == 0, allowed.stderr or allowed.stdout
        assert "PASS:" in allowed.stdout

        # A changed runtime file must STILL be rejected; do not weaken protection.
        (target / "VERSION").write_text("locally tampered\n", encoding="utf-8")
        blocked = check()
        assert blocked.returncode != 0
        assert "locally modified source VERSION" in (blocked.stderr + blocked.stdout)
        (target / "VERSION").unlink()

        # Reintroducing .github in a future manifest is a deliberate error.
        manifest[".github/workflows/installer-step1.yml"] = [digest]
        rejected = check()
        assert rejected.returncode != 0
        assert "CI-only path must not be deployed" in (rejected.stderr + rejected.stdout)

    print("PASS: old GitHub workflow ignored; runtime file protection preserved")


if __name__ == "__main__":
    main()
