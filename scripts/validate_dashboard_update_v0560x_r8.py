#!/usr/bin/env python3
"""Static and small behavioral checks for the v0.56.0x-r8 dashboard updater."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def check(ok, message):
    if not ok:
        raise SystemExit("FAIL: " + message)
    print("PASS: " + message)


check((ROOT / "VERSION").read_text().strip() == "0.56.0x-r8", "release version is r8")

for relative in [
    "core/update_manager.py",
    "scripts/sdrcc_update.py",
    "dashboard/static/js/update_manager.js",
]:
    check((ROOT / relative).exists(), f"required update component present: {relative}")

for relative in [
    "core/update_manager.py",
    "scripts/sdrcc_update.py",
    "dashboard/app.py",
]:
    ast.parse((ROOT / relative).read_text())
    print("PASS: parseable " + relative)

spec = importlib.util.spec_from_file_location(
    "sdrcc_update_manager_test",
    ROOT / "core/update_manager.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

check(module.compare_versions("0.56.0x-r7", "0.56.0x-r8") == -1, "r7 compares older than r8")
check(module.compare_versions("0.56.0x-r8", "0.56.0x-r8") == 0, "same release compares equal")
check(module.compare_versions("0.56.0x-r9", "0.56.0x-r8") == 1, "local development release can be ahead of main")


class FakeResponse:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, amount):
        return b"0.56.0x-r8\n"


with tempfile.TemporaryDirectory() as directory:
    version = Path(directory) / "VERSION"
    status = Path(directory) / "status.json"
    version.write_text("0.56.0x-r7\n")
    with patch.object(module, "VERSION_FILE", version), \
         patch.object(module, "STATUS_FILE", status), \
         patch.object(module, "urlopen", return_value=FakeResponse()):
        data = module.check_remote_version()
        check(data["update_available"], "read-only remote check reports newer release")
        check(data["latest_version"] == "0.56.0x-r8", "read-only remote check returns latest version")

with tempfile.TemporaryDirectory() as directory:
    status = Path(directory) / "status.json"
    status.write_text(json.dumps({"state": "installing", "message": "old"}))
    with patch.object(module, "STATUS_FILE", status), \
         patch.object(module, "_update_unit_active", return_value=False):
        stale = module._read_worker_status()
        check(stale["state"] == "interrupted", "stale active update status becomes retryable after interruption")

app = (ROOT / "dashboard/app.py").read_text()
template = (ROOT / "dashboard/templates/index.html").read_text()
javascript = (ROOT / "dashboard/static/js/update_manager.js").read_text()
install = (ROOT / "install.sh").read_text()
update = (ROOT / "scripts/install/update_existing.sh").read_text()
uninstall = (ROOT / "uninstall.sh").read_text()
helper = (ROOT / "scripts/sdrcc_update.py").read_text()

check('"/api/update-status"' in app and '"/api/update/install"' in app, "dashboard exposes update status and install endpoints")
check("update_manager.check_remote_version" in app, "startup launches read-only update check")
check('id="sdrcc-update-install"' in template and 'id="sdrcc-update-check"' in template, "Advanced Maintenance contains update controls")
check("update_manager.js?v=0.56.0x-r8" in template, "update browser logic is loaded with r8 cache key")
check("confirm(" in javascript and "/api/update/install" in javascript, "update requires browser confirmation")
check("systemd-run" in helper and "--worker" in helper, "update worker detaches into a transient systemd unit")
check('UPDATE_UNIT = "sdrcc-update"' in helper, "update uses one fixed transient unit for concurrency control")
check("verify_source_manifest" in helper and "hashlib.sha256" in helper, "trusted worker verifies downloaded source hashes")
checker = (ROOT / "scripts/install/check_update.py").read_text()
check("update source hash not approved" in checker, "common update checker verifies source hashes")
check("binding_transaction" in checker and "hardware_recovery" in checker, "common update checker blocks receiver binding/recovery")
check("canonical_reservations" in app and "binding_status()" in app, "dashboard blocks receiver work and hardware recovery")
check(
    "/usr/local/sbin/sdrcc-update" in install
    and 'cat >"$tmp/sdrcc-update"' in install
    and '/usr/local/sbin/sdrcc-update ""' in install
    and '"/etc/sudoers.d/$(basename "$f")"' in install,
    "clean installer installs no-argument update helper boundary",
)
check(
    '/usr/local/sbin/sdrcc-update ""' in update
    and "/etc/sudoers.d/sdrcc-update" in update,
    "manual updater installs no-argument update helper boundary",
)
check(
    '/usr/local/sbin/sdrcc-update ""' in helper,
    "managed updater preserves the no-argument sudoers boundary",
)
check("/usr/local/sbin/sdrcc-update" in uninstall and "/etc/sudoers.d/sdrcc-update" in uninstall, "uninstaller removes update helper boundary")
check(
    "update-status.json" in uninstall
    and "sdrcc-update.log" in uninstall
    and "sdrcc-update.lock" in uninstall
    and "systemctl stop sdrcc-update.service" in uninstall,
    "uninstaller stops updater and removes updater runtime state",
)
check("0.56.0x-r7" in update and "0.56.0x-r8" in update, "manual updater accepts r7 and r8 source versions")

manifest = json.loads((ROOT / "scripts/install/update_manifest.json").read_text())
for relative in [
    "VERSION",
    "install.sh",
    "uninstall.sh",
    "dashboard/app.py",
    "dashboard/templates/index.html",
    "dashboard/static/js/update_manager.js",
    "core/update_manager.py",
    "scripts/sdrcc_update.py",
    "scripts/install/check_update.py",
    "scripts/install/update_existing.sh",
    "scripts/install/validate_install.py",
    "scripts/validate_uninstall_v0560q_r4.py",
    "scripts/validate_dashboard_update_v0560x_r8.py",
]:
    digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
    check(relative in manifest and digest in manifest[relative], f"update manifest contains current hash: {relative}")

print("VALIDATION PASS: SDRCC v0.56.0x-r8 managed dashboard updater")
