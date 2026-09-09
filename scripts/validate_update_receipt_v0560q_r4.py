#!/usr/bin/env python3
"""Exercise the existing-install update through receipt creation and validation."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check(ok: bool, message: str) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {message}")
    print(f"PASS: {message}")


with tempfile.TemporaryDirectory(prefix="sdrcc-update-receipt-test-") as temporary:
    test_root = Path(temporary)
    project = test_root / "SDRCC"
    fake_bin = test_root / "bin"
    receipt = test_root / "var/lib/sdrcc/install-receipt"

    (project / "venv/bin").mkdir(parents=True)
    (project / "config").mkdir()
    (project / "VERSION").write_text((ROOT / "VERSION").read_text())
    (project / "config/station.yaml").write_text("station:\n  name: Preserve me\n")
    (project / "venv/bin/python").symlink_to(sys.executable)

    fake_bin.mkdir()
    wrappers = {
        "sudo": '#!/usr/bin/env bash\n[[ "${1:-}" == -v ]] && exit 0\nexec "$@"\n',
        "systemctl": '#!/usr/bin/env bash\n[[ "${1:-}" == is-active ]] && exit 1\nexit 0\n',
        "curl": '#!/usr/bin/env bash\nprintf "200"\n',
    }
    for name, text in wrappers.items():
        path = fake_bin / name
        path.write_text(text)
        path.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        PATH=f"{fake_bin}:{environment['PATH']}",
        SDRCC_INSTALL_RECEIPT=str(receipt),
        SDRCC_INSTALL_TEST_MODE="1",
    )
    completed = subprocess.run(
        [str(ROOT / "scripts/install/update_existing.sh"), str(ROOT), str(project)],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    check(completed.returncode == 0, f"update workflow exits successfully: {completed.stderr.strip()}")
    check("dashboard HTTP 200" in completed.stdout, "update reaches post-start dashboard validation")
    check(receipt.exists(), "legacy installation receives a root-owned uninstall receipt")
    receipt_text = receipt.read_text()
    check("legacy_install=1" in receipt_text, "receipt marks externally ambiguous legacy ownership")
    check("airband_installed=1" in receipt_text, "project-specific RTLSDR-Airband ownership is recorded")
    check((project / "uninstall.sh").read_bytes() == (ROOT / "uninstall.sh").read_bytes(), "new uninstaller is deployed by the update")
    check("Preserve me" in (project / "config/station.yaml").read_text(), "existing station configuration is preserved")

print("VALIDATION PASS: existing-install update deploys receipt-aware uninstall")
