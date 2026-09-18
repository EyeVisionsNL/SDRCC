#!/usr/bin/env python3
"""Root-owned managed SDRCC updater.

Dashboard use invokes this helper with no arguments. It launches a separate
transient systemd worker so stopping sdrcc.service cannot kill the update.
The sudoers rule permits only the no-argument launcher command.
"""

from __future__ import annotations

import base64
from datetime import datetime
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
import time

SELF = Path("/usr/local/sbin/sdrcc-update")
RECEIPT = Path("/var/lib/sdrcc/install-receipt")
STATUS_FILE = Path("/var/lib/sdrcc/update-status.json")
LOG_FILE = Path("/var/log/sdrcc-update.log")
LOCK_FILE = Path("/run/lock/sdrcc-update.lock")
REPOSITORY = "https://github.com/EyeVisionsNL/SDRCC.git"
BRANCH = "main"
VERSION_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<suffix>[A-Za-z]*)(?:-r(?P<revision>\d+))?$"
)
UPDATE_UNIT = "sdrcc-update"


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def version_key(value: str):
    match = VERSION_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        match.group("suffix").lower(),
        int(match.group("revision") or 0),
    )


def compare_versions(local: str, remote: str):
    left = version_key(local)
    right = version_key(remote)
    if left is None or right is None:
        raise RuntimeError(f"Unsupported version comparison: {local!r} -> {remote!r}")
    return -1 if left < right else (1 if left > right else 0)


def write_status(state: str, message: str, **extra) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "message": message, "updated_at": now(), **extra}
    temporary = STATUS_FILE.with_name(STATUS_FILE.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, STATUS_FILE)


def read_status() -> dict:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def log(message: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now()}] {message}\n")


def run(command, *, cwd=None, timeout=None, check=False, user=None, env=None):
    cmd = [str(item) for item in command]
    if user:
        cmd = ["/usr/sbin/runuser", "-u", user, "--", *cmd]
    completed = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if completed.stdout:
        log(completed.stdout.rstrip())
    if completed.stderr:
        log(completed.stderr.rstrip())
    if check and completed.returncode:
        raise RuntimeError(
            (completed.stderr or completed.stdout or f"command failed: {' '.join(cmd)}").strip()
        )
    return completed


def receipt_value(key: str) -> str:
    if not RECEIPT.exists():
        raise RuntimeError(f"Installation receipt missing: {RECEIPT}")
    value = ""
    for line in RECEIPT.read_text(encoding="utf-8").splitlines():
        name, separator, raw = line.partition("=")
        if separator and name == key:
            value = raw
    return value


def installation() -> tuple[Path, str, str]:
    encoded = receipt_value("project_root_b64")
    try:
        project_root = Path(base64.b64decode(encoded).decode("utf-8")).resolve()
    except Exception as exc:
        raise RuntimeError("Invalid project_root_b64 in installation receipt") from exc
    install_user = receipt_value("install_user")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", install_user or ""):
        raise RuntimeError("Unsafe install_user in installation receipt")
    if not project_root.is_dir() or not (project_root / "VERSION").is_file():
        raise RuntimeError(f"Installed SDRCC project not found: {project_root}")

    import pwd
    import grp
    stat = project_root.stat()
    try:
        owner = pwd.getpwuid(stat.st_uid).pw_name
        group = grp.getgrgid(stat.st_gid).gr_name
    except KeyError as exc:
        raise RuntimeError("Installed SDRCC owner/group cannot be resolved") from exc
    if owner != install_user:
        raise RuntimeError(
            f"Installation receipt user {install_user} does not own {project_root} (owner={owner})"
        )
    return project_root, install_user, group


def safe_relative(name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RuntimeError(f"Unsafe update manifest path: {name!r}")
    return relative


def verify_source_manifest(source: Path) -> None:
    manifest_path = source / "scripts/install/update_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Update manifest must be an object")

    for name, allowed in manifest.items():
        relative = safe_relative(name)
        if not isinstance(allowed, list) or not all(isinstance(value, str) for value in allowed):
            raise RuntimeError(f"Invalid update manifest hash list: {name}")
        if name == "scripts/install/update_manifest.json":
            continue
        source_file = source / relative
        if not source_file.is_file():
            raise RuntimeError(f"Update source missing: {relative}")
        digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
        if digest not in allowed:
            raise RuntimeError(f"Update source hash is not approved: {relative}")


def source_preflight(source: Path, project: Path, install_user: str) -> None:
    checker = source / "scripts/install/check_update.py"
    python = project / "venv/bin/python"
    completed = run(
        [python, checker, source, project],
        timeout=60,
        user=install_user,
    )
    if completed.returncode:
        raise RuntimeError(
            (completed.stderr or completed.stdout or "Update compatibility check failed").strip()
        )

    venv_python = project / "venv/bin/python"
    flexibility = source / "scripts/validate_receiver_flexibility_v0560q.py"
    if venv_python.exists() and flexibility.exists():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(source)
        completed = run(
            [venv_python, flexibility],
            timeout=120,
            user=install_user,
            env=env,
        )
        if completed.returncode:
            raise RuntimeError(
                (completed.stderr or completed.stdout or "Receiver flexibility validation failed").strip()
            )


def backup_install(project: Path, source: Path, current: str, install_user: str, install_group: str) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup = project / ".rollback" / f"{current}-{stamp}"
    (backup / "files").mkdir(parents=True, exist_ok=False)
    shutil.copytree(project / "config", backup / "config", dirs_exist_ok=True)
    shutil.copy2(source / "scripts/install/rollback_code.py", backup / "rollback_code.py")
    state = project / "data/state/receiver_manager.json"
    if state.exists():
        shutil.copy2(state, backup / "receiver_manager.json")
    run(["/bin/chown", "-R", f"{install_user}:{install_group}", project / ".rollback"], check=True)
    return backup


def deploy_manifest(source: Path, project: Path, backup: Path, install_user: str, install_group: str) -> None:
    manifest = json.loads(
        (source / "scripts/install/update_manifest.json").read_text(encoding="utf-8")
    )
    if not isinstance(manifest, dict):
        raise RuntimeError("Update manifest must be an object")

    import pwd
    import grp
    uid = pwd.getpwnam(install_user).pw_uid
    gid = grp.getgrnam(install_group).gr_gid
    created = []
    source_root = source.resolve()
    project_root = project.resolve()

    for name in manifest:
        relative = safe_relative(name)
        src = (source / relative).resolve()
        dst = (project / relative).resolve()
        if source_root not in src.parents:
            raise RuntimeError(f"Source escaped update tree: {relative}")
        if project_root not in dst.parents:
            raise RuntimeError(f"Destination escaped project tree: {relative}")
        if not src.is_file():
            raise RuntimeError(f"Manifest source missing: {relative}")

        old = backup / "files" / relative
        if dst.exists():
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, old)
        else:
            created.append(str(relative))

        dst.parent.mkdir(parents=True, exist_ok=True)
        temporary = dst.with_name(dst.name + ".update-tmp")
        shutil.copy2(src, temporary)
        os.chown(temporary, uid, gid)
        os.replace(temporary, dst)

    (backup / "created.json").write_text(json.dumps(created, indent=2) + "\n", encoding="utf-8")
    run(["/bin/chown", "-R", f"{install_user}:{install_group}", backup], check=True)


def install_privileged_helpers(source: Path, install_user: str) -> None:
    helpers = {
        "scripts/sdrcc_disable_ais_autostart.py": "/usr/local/sbin/sdrcc-disable-ais-autostart",
        "scripts/sdrcc_disable_self_autostart.py": "/usr/local/sbin/sdrcc-disable-self-autostart",
        "scripts/sdrcc_sync_readsb_position.py": "/usr/local/sbin/sdrcc-sync-readsb-position",
        "scripts/sdrcc_update.py": "/usr/local/sbin/sdrcc-update",
    }
    for relative, target in helpers.items():
        run(
            ["/usr/bin/install", "-o", "root", "-g", "root", "-m", "0755", source / relative, target],
            check=True,
        )

    rules = {
        "/etc/sudoers.d/sdrcc-ais-autostart":
            f"{install_user} ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-ais-autostart\n",
        "/etc/sudoers.d/sdrcc-self-autostart":
            f"{install_user} ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-disable-self-autostart\n",
        "/etc/sudoers.d/sdrcc-readsb-position":
            f"{install_user} ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-sync-readsb-position *\n",
        "/etc/sudoers.d/sdrcc-update":
            f'{install_user} ALL=(root) NOPASSWD: /usr/local/sbin/sdrcc-update ""\n',
    }
    for target, text in rules.items():
        temporary = Path(target + ".tmp")
        temporary.write_text(text, encoding="utf-8")
        os.chmod(temporary, 0o440)
        run(["/usr/sbin/visudo", "-cf", temporary], check=True)
        os.replace(temporary, target)


def home_position(project: Path, install_user: str) -> tuple[str, str]:
    python = project / "venv/bin/python"
    code = (
        "from core.config import get_home_position;"
        "p=get_home_position();"
        "print(f\"{p['latitude']}\\t{p['longitude']}\")"
    )
    completed = run(
        [python, "-c", code],
        cwd=project,
        timeout=30,
        check=True,
        user=install_user,
    )
    pieces = completed.stdout.strip().split("\t")
    if len(pieces) != 2:
        raise RuntimeError("Could not read Home Position from installed configuration")
    return pieces[0], pieces[1]


def wait_dashboard(timeout: int = 75) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = run(
            [
                "/usr/bin/curl", "--max-time", "4", "-s", "-o", "/dev/null",
                "-w", "%{http_code}", "http://127.0.0.1:8080/api/status",
            ],
            timeout=8,
        )
        if result.stdout.strip() == "200":
            return
        time.sleep(1)
    raise RuntimeError("Dashboard did not return HTTP 200 after update")


def worker() -> int:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another SDRCC update worker already holds the update lock.")
        return 3

    project = None
    backup = None
    was_active = False
    current = None
    target = None

    try:
        project, install_user, install_group = installation()
        current = (project / "VERSION").read_text(encoding="utf-8").strip()
        write_status("starting", "Preparing SDRCC update.", current_version=current)
        log(f"Managed update started from {current}")

        with tempfile.TemporaryDirectory(prefix="sdrcc-update-", dir="/var/tmp") as temporary:
            os.chmod(temporary, 0o755)
            source = Path(temporary) / "source"
            write_status("downloading", "Downloading current SDRCC main branch.", current_version=current)
            run(
                [
                    "/usr/bin/git", "clone", "--quiet", "--depth", "1",
                    "--branch", BRANCH, "--single-branch", REPOSITORY, source,
                ],
                timeout=180,
                check=True,
            )

            verify_source_manifest(source)
            target = (source / "VERSION").read_text(encoding="utf-8").strip()
            comparison = compare_versions(current, target)
            commit = run(
                ["/usr/bin/git", "-C", source, "rev-parse", "HEAD"],
                timeout=20,
                check=True,
            ).stdout.strip()

            if comparison >= 0:
                message = (
                    "SDRCC is already up to date."
                    if comparison == 0
                    else f"Installed version {current} is ahead of main ({target}); no update installed."
                )
                write_status(
                    "up_to_date",
                    message,
                    current_version=current,
                    target_version=target,
                    source_commit=commit,
                )
                return 0

            write_status(
                "validating",
                f"Validating update {current} -> {target}.",
                current_version=current,
                target_version=target,
                source_commit=commit,
            )
            source_preflight(source, project, install_user)

            write_status(
                "backing_up",
                f"Creating rollback backup for {current}.",
                current_version=current,
                target_version=target,
                source_commit=commit,
            )
            backup = backup_install(project, source, current, install_user, install_group)

            was_active = run(
                ["/usr/bin/systemctl", "is-active", "--quiet", "sdrcc.service"],
                timeout=10,
            ).returncode == 0
            run(["/usr/bin/systemctl", "stop", "sdrcc.service"], timeout=45, check=True)

            source_preflight(source, project, install_user)

            write_status(
                "installing",
                f"Installing SDRCC {target}.",
                current_version=current,
                target_version=target,
                source_commit=commit,
                backup=str(backup),
            )
            deploy_manifest(source, project, backup, install_user, install_group)
            install_privileged_helpers(source, install_user)

            latitude, longitude = home_position(project, install_user)
            run(
                ["/usr/local/sbin/sdrcc-sync-readsb-position", latitude, longitude],
                timeout=60,
                check=True,
            )

            compile_result = run(
                [
                    project / "venv/bin/python", "-m", "compileall", "-q",
                    project / "core", project / "dashboard",
                ],
                timeout=120,
                user=install_user,
            )
            if compile_result.returncode:
                raise RuntimeError("Python compilation failed after update")

            write_status(
                "restarting",
                f"Restarting SDRCC {target}.",
                current_version=current,
                target_version=target,
                source_commit=commit,
                backup=str(backup),
            )
            run(["/usr/bin/systemctl", "start", "sdrcc.service"], timeout=45, check=True)
            wait_dashboard()

            installed = (project / "VERSION").read_text(encoding="utf-8").strip()
            if installed != target:
                raise RuntimeError(f"Installed VERSION mismatch: expected {target}, got {installed}")

            write_status(
                "success",
                f"SDRCC updated successfully to {target}.",
                current_version=current,
                target_version=target,
                installed_version=installed,
                source_commit=commit,
                backup=str(backup),
            )
            log(f"Managed update completed: {current} -> {target}")
            return 0

    except Exception as exc:
        message = str(exc)
        log(f"Managed update failed: {message}")
        if project is not None and was_active:
            try:
                run(["/usr/bin/systemctl", "start", "sdrcc.service"], timeout=45)
            except Exception:
                pass
        write_status(
            "failed",
            message,
            current_version=current,
            target_version=target,
            backup=str(backup) if backup else None,
        )
        return 1


def update_unit_active() -> bool:
    return run(
        ["/usr/bin/systemctl", "is-active", "--quiet", UPDATE_UNIT + ".service"],
        timeout=10,
    ).returncode == 0


def launch() -> int:
    if update_unit_active():
        print(json.dumps({
            "ok": False,
            "message": "An SDRCC update is already running.",
        }))
        return 3

    result = run(
        [
            "/usr/bin/systemd-run", "--quiet", "--no-block", "--collect",
            f"--unit={UPDATE_UNIT}", "--property=Type=exec", str(SELF), "--worker",
        ],
        timeout=30,
    )
    if result.returncode:
        if update_unit_active():
            print(json.dumps({
                "ok": False,
                "message": "An SDRCC update is already running.",
            }))
            return 3
        write_status("failed", "Could not start the detached SDRCC update worker.")
        print(json.dumps({
            "ok": False,
            "message": (result.stderr or result.stdout or "systemd-run failed").strip(),
        }))
        return 1

    print(json.dumps({
        "ok": True,
        "message": "SDRCC update started. The dashboard will restart during installation.",
        "unit": UPDATE_UNIT + ".service",
    }))
    return 0


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "message": "Root rights required."}))
        return 1
    if len(sys.argv) == 1:
        return launch()
    if sys.argv[1:] == ["--worker"]:
        return worker()
    print(json.dumps({"ok": False, "message": "Unsupported arguments."}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
