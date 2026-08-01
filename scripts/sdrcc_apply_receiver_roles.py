#!/usr/bin/env python3
"""Root-owned service configuration adapter for SDRCC v0.54.0a.

The dashboard invokes the installed copy at
``/usr/local/sbin/sdrcc-apply-receiver-roles`` through the existing sudo rule.
It changes only readsb/AIS-catcher execution configuration, preserves previous
service states, verifies active runtime serials and restores both configuration
and services on failure. It never decides role policy or edits station.yaml.
"""

from __future__ import annotations

from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


VERSION = "0.54.0a"
READSB_CONFIG = Path("/etc/default/readsb")
AIS_CONFIG = Path("/etc/AIS-catcher/aiscatcher.json")
LOCK_FILE = Path("/run/lock/sdrcc-receiver-assignments.lock")
BACKUP_ROOT = Path("/var/backups/sdrcc/receiver-authority")
READSB_SERVICE = "readsb.service"
AIS_SERVICE = "ais-catcher.service"
AIS_CONTROL_SERVICE = "ais-catcher-control.service"
SERIAL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
READSB_DEVICE_RE = re.compile(
    r"(?P<prefix>(?:^|[ \t\"'])--device(?:=|[ \t]+))"
    r"(?P<serial>[^ \t\r\n\"']+)"
)
AIS_RUNTIME_RE = re.compile(r"Searching for device with SN\s+([^\s]+)", re.IGNORECASE)


class ApplyError(RuntimeError):
    pass


def run(command: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ApplyError(f"Opdracht mislukt: {' '.join(command)}: {error}") from error


def systemctl(action: str, service: str) -> None:
    result = run(["systemctl", action, service], timeout=45)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "onbekende fout").strip()
        raise ApplyError(f"systemctl {action} {service}: {detail}")


def service_active(service: str) -> bool:
    result = run(["systemctl", "is-active", service], timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "active"


def service_pid(service: str) -> int:
    result = run(["systemctl", "show", service, "--property=MainPID", "--value"], timeout=10)
    try:
        return int(result.stdout.strip() or "0")
    except ValueError:
        return 0


def wait_state(service: str, active: bool, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_active(service) is active:
            return
        time.sleep(0.4)
    expected = "active" if active else "inactive"
    raise ApplyError(f"{service} werd niet {expected}")


def read_readsb_serial() -> str:
    try:
        text = READSB_CONFIG.read_text(encoding="utf-8")
    except OSError as error:
        raise ApplyError(f"Kan {READSB_CONFIG} niet lezen: {error}") from error
    matches = readsb_device_matches(text)
    if not matches:
        raise ApplyError(f"--device ontbreekt in {READSB_CONFIG}")
    if len(matches) != 1:
        raise ApplyError(
            f"Verwacht één actieve readsb --device-optie in {READSB_CONFIG}, "
            f"gevonden {len(matches)}"
        )
    return matches[0][1].group("serial").strip()


def readsb_device_matches(text: str) -> list[tuple[int, re.Match[str]]]:
    """Locate active --device options while ignoring commented EnvironmentFile lines."""
    matches = []
    for index, line in enumerate(text.splitlines(keepends=True)):
        if line.lstrip().startswith("#"):
            continue
        matches.extend((index, match) for match in READSB_DEVICE_RE.finditer(line))
    return matches


def read_ais_payload() -> dict[str, Any]:
    try:
        payload = json.loads(AIS_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ApplyError(f"Kan {AIS_CONFIG} niet lezen: {error}") from error
    if not isinstance(payload, dict):
        raise ApplyError(f"{AIS_CONFIG} bevat geen JSON-object")
    return payload


def active_ais_receiver(payload: dict[str, Any]) -> dict[str, Any]:
    receivers = payload.get("receiver")
    if not isinstance(receivers, list):
        raise ApplyError("AIS receiver-lijst ontbreekt")
    candidates = [
        item for item in receivers
        if isinstance(item, dict)
        and str(item.get("input") or "").strip().upper() == "RTLSDR"
        and item.get("active") is not False
    ]
    if len(candidates) != 1:
        raise ApplyError(
            f"Verwacht één actieve AIS RTLSDR-configuratie, gevonden {len(candidates)}"
        )
    return candidates[0]


def read_ais_serial() -> str:
    return str(active_ais_receiver(read_ais_payload()).get("serial") or "").strip()


def process_cmdline(pid: int) -> list[str]:
    if pid <= 0:
        return []
    try:
        data = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in data.split(b"\0") if part]


def readsb_runtime_serial() -> str | None:
    args = process_cmdline(service_pid(READSB_SERVICE))
    for index, value in enumerate(args):
        if value == "--device" and index + 1 < len(args):
            return args[index + 1].strip()
        if value.startswith("--device="):
            return value.split("=", 1)[1].strip()
    return None


def ais_runtime_serial() -> str | None:
    pid = service_pid(AIS_SERVICE)
    if pid <= 0:
        return None
    result = run([
        "journalctl",
        f"_PID={pid}",
        "--grep=Searching for device with SN",
        "-n",
        "1",
        "--no-pager",
        "-o",
        "cat",
    ], timeout=5)
    if result.returncode != 0:
        return None
    matches = AIS_RUNTIME_RE.findall(result.stdout or "")
    return matches[-1].strip(".,;") if matches else None


def wait_runtime_serial(reader, expected: str, label: str, timeout: float = 25.0) -> str:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = reader()
        if last == expected:
            return last
        time.sleep(0.5)
    raise ApplyError(f"{label} runtime serial verwacht {expected}, waargenomen {last or 'onbekend'}")


def atomic_write(path: Path, data: bytes) -> None:
    stat = path.stat()
    temporary = path.with_name(path.name + ".sdrcc-v0540a.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, stat.st_mode & 0o7777)
        os.chown(temporary, stat.st_uid, stat.st_gid)
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def write_readsb_serial(serial: str) -> None:
    text = READSB_CONFIG.read_text(encoding="utf-8")
    matches = readsb_device_matches(text)
    if len(matches) != 1:
        raise ApplyError(
            f"readsb --device kon niet veilig worden vervangen in {READSB_CONFIG}: "
            f"verwacht één actieve optie, gevonden {len(matches)}"
        )
    lines = text.splitlines(keepends=True)
    index, match = matches[0]
    line = lines[index]
    lines[index] = (
        line[:match.start()]
        + match.group("prefix")
        + serial
        + line[match.end():]
    )
    atomic_write(READSB_CONFIG, "".join(lines).encode("utf-8"))


def write_ais_serial(serial: str) -> None:
    payload = read_ais_payload()
    active_ais_receiver(payload)["serial"] = serial
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write(AIS_CONFIG, encoded)


def create_backup() -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    directory = BACKUP_ROOT / stamp
    directory.mkdir(parents=True, mode=0o700)
    shutil.copy2(READSB_CONFIG, directory / "readsb")
    shutil.copy2(AIS_CONFIG, directory / "aiscatcher.json")
    return directory


def restore_files(backup: Path) -> None:
    shutil.copy2(backup / "readsb", READSB_CONFIG)
    shutil.copy2(backup / "aiscatcher.json", AIS_CONFIG)


def restore_service_states(states: dict[str, bool]) -> list[str]:
    errors = []
    for service in (READSB_SERVICE, AIS_SERVICE, AIS_CONTROL_SERVICE):
        try:
            currently_active = service_active(service)
            should_be_active = states[service]
            if should_be_active and not currently_active:
                systemctl("start", service)
                wait_state(service, True)
            elif not should_be_active and currently_active:
                systemctl("stop", service)
                wait_state(service, False)
        except Exception as error:
            errors.append(f"{service}: {error}")
    return errors


def stop_if_active(service: str) -> None:
    if service_active(service):
        systemctl("stop", service)
        wait_state(service, False)


def apply(ais_serial: str, adsb_serial: str) -> dict[str, Any]:
    for serial in (ais_serial, adsb_serial):
        if not SERIAL_RE.fullmatch(serial):
            raise ApplyError(f"Ongeldig receiver-serienummer: {serial!r}")
    if ais_serial == adsb_serial:
        raise ApplyError("AIS en ADS-B kunnen niet hetzelfde serienummer gebruiken")

    current_ais = read_ais_serial()
    current_adsb = read_readsb_serial()
    states = {
        READSB_SERVICE: service_active(READSB_SERVICE),
        AIS_SERVICE: service_active(AIS_SERVICE),
        AIS_CONTROL_SERVICE: service_active(AIS_CONTROL_SERVICE),
    }
    runtime_ais = ais_runtime_serial() if states[AIS_SERVICE] else None
    runtime_adsb = readsb_runtime_serial() if states[READSB_SERVICE] else None
    change_ais = current_ais != ais_serial or (
        states[AIS_SERVICE] and runtime_ais != ais_serial
    )
    change_adsb = current_adsb != adsb_serial or (
        states[READSB_SERVICE] and runtime_adsb != adsb_serial
    )

    if not change_ais and not change_adsb:
        return {
            "ok": True,
            "version": VERSION,
            "changed": False,
            "message": "Serviceconfiguratie en actieve runtime zijn al gesynchroniseerd.",
            "ais_serial": ais_serial,
            "adsb_serial": adsb_serial,
            "runtime_verified": {
                "ais": not states[AIS_SERVICE] or runtime_ais == ais_serial,
                "adsb": not states[READSB_SERVICE] or runtime_adsb == adsb_serial,
            },
        }

    backup = create_backup()
    try:
        if change_ais:
            stop_if_active(AIS_CONTROL_SERVICE)
            stop_if_active(AIS_SERVICE)
        if change_adsb:
            stop_if_active(READSB_SERVICE)

        if current_ais != ais_serial:
            write_ais_serial(ais_serial)
        if current_adsb != adsb_serial:
            write_readsb_serial(adsb_serial)

        if read_ais_serial() != ais_serial or read_readsb_serial() != adsb_serial:
            raise ApplyError("Serviceconfiguratie kon niet worden teruggelezen")

        if change_adsb and states[READSB_SERVICE]:
            systemctl("start", READSB_SERVICE)
            wait_state(READSB_SERVICE, True)
            wait_runtime_serial(readsb_runtime_serial, adsb_serial, "readsb")
        if change_ais and states[AIS_SERVICE]:
            systemctl("start", AIS_SERVICE)
            wait_state(AIS_SERVICE, True)
            wait_runtime_serial(ais_runtime_serial, ais_serial, "AIS-catcher")
        if change_ais and states[AIS_CONTROL_SERVICE]:
            systemctl("start", AIS_CONTROL_SERVICE)
            wait_state(AIS_CONTROL_SERVICE, True)

        return {
            "ok": True,
            "version": VERSION,
            "changed": True,
            "message": "Receiverrollen transactioneel toegepast en geverifieerd.",
            "ais_serial": ais_serial,
            "adsb_serial": adsb_serial,
            "previous_ais_serial": current_ais,
            "previous_adsb_serial": current_adsb,
            "backup": str(backup),
            "service_states_preserved": True,
            "runtime_verified": {
                "ais": not states[AIS_SERVICE] or ais_runtime_serial() == ais_serial,
                "adsb": not states[READSB_SERVICE] or readsb_runtime_serial() == adsb_serial,
            },
        }
    except Exception as error:
        rollback_errors = []
        for service in (AIS_CONTROL_SERVICE, AIS_SERVICE, READSB_SERVICE):
            try:
                stop_if_active(service)
            except Exception as stop_error:
                rollback_errors.append(f"stop {service}: {stop_error}")
        try:
            restore_files(backup)
        except Exception as restore_error:
            rollback_errors.append(f"config restore: {restore_error}")
        rollback_errors.extend(restore_service_states(states))
        raise ApplyError(
            f"Receiverwisseling mislukt: {error}; rollback "
            + ("geslaagd" if not rollback_errors else "onvolledig: " + "; ".join(rollback_errors))
        ) from error


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "message": "Rootrechten zijn vereist."}))
        return 1
    if len(sys.argv) != 3:
        print(json.dumps({
            "ok": False,
            "message": "Gebruik: sdrcc-apply-receiver-roles AIS_SERIAL ADSB_SERIAL",
        }))
        return 2

    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            result = apply(str(sys.argv[1]).strip(), str(sys.argv[2]).strip())
            print(json.dumps(result, ensure_ascii=False))
            return 0
        except Exception as error:
            print(json.dumps({
                "ok": False,
                "version": VERSION,
                "message": str(error),
                "rollback_performed": True,
            }, ensure_ascii=False))
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
