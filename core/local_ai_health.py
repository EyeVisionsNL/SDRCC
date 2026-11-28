"""On-demand, read-only station diagnostics. No service or USB control."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import time

from core import local_ai_reception

UNITS = {"AIS": "ais-catcher.service", "ADS-B": "readsb.service"}
PATTERNS = {
    "sdr_wedged": re.compile(r"SDR wedged", re.I),
    "device_not_found": re.compile(r"no device matching|no matching devices", re.I),
    "usb_io_errors": re.compile(r"rtlsdr_(?:demod_)?(?:read|write)_reg failed|i2c wr failed|usb.*(?:error|disconnect)", re.I),
    "usb_reset_failed": re.compile(r"RECEIVER USB RESET FAILED|USB reset failed", re.I),
    "usb_reset_ok": re.compile(r"USB reset OK:", re.I),
    "recovery_exhausted": re.compile(r"retry budget exhausted", re.I),
}


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=3, check=False)
        if result.returncode == 0 and len(result.stdout) <= 1024 * 1024:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def observe_service(label):
    unit = UNITS[label]
    raw = command(["systemctl", "show", unit, "--property=LoadState,ActiveState,SubState,Result,NRestarts"])
    if raw is None:
        return {"state": "unknown", "status": "unknown", "detail": "Service status unavailable"}
    values = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    state = values.get("ActiveState", "unknown")
    sub = values.get("SubState", "")
    if values.get("LoadState") != "loaded":
        status = "unknown"
    elif sub.startswith("auto-restart") or state == "failed":
        status = "attention"
    elif state == "active":
        status = "ok"
    elif state == "inactive":
        status = "idle"
    else:
        status = "unknown"
    restarts = values.get("NRestarts", "")
    return {"state": state, "status": status, "sub_state": sub,
            "restart_count": int(restarts) if restarts.isdecimal() else None,
            "detail": "Service state only; not proof of RF reception"}


def count_events(lines):
    counts = dict.fromkeys(PATTERNS, 0)
    for line in lines:
        for key, pattern in PATTERNS.items():
            if pattern.search(line):
                counts[key] += 1
    return counts


def service_events(label):
    raw = command(["journalctl", "-u", UNITS[label], "--since=-1h", "-n", "150", "--no-pager", "-o", "cat"])
    if raw is None:
        return {"status": "unavailable"}
    lines = raw.splitlines()
    # Empty output can mean no events or no journal access; never claim clean.
    return {"status": "observed" if lines else "no_visible_entries",
            "lines": len(lines), "truncated": len(lines) >= 150, "counts": count_events(lines)}


def station_events(root, now):
    try:
        with (root / "logs/sdrcc.log").open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 65536))
            raw = handle.read(65536).decode("utf-8", "replace")
        lines = []
        for line in raw.splitlines():
            match = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)", line)
            if match:
                epoch = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S").timestamp()
                if now - 3600 <= epoch <= now:
                    lines.append(match[2])
        return {"status": "observed" if lines else "no_visible_entries",
                "lines": len(lines), "truncated": size > 65536, "counts": count_events(lines)}
    except (OSError, ValueError, OverflowError):
        return {"status": "unavailable"}


def resources(root):
    result = {"available_ram_gib": None, "disk_free_gib": None, "load_1m_per_cpu": None,
              "cpu_temperature_c": None}
    try:
        mem = Path("/proc/meminfo").read_text()
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", mem, re.M)
        if match:
            result["available_ram_gib"] = round(int(match[1]) / 1048576, 2)
        result["load_1m_per_cpu"] = round(os.getloadavg()[0] / max(1, os.cpu_count() or 1), 2)
        result["disk_free_gib"] = round(shutil.disk_usage(root).free / 1024**3, 2)
    except OSError:
        pass
    temperatures = []
    for path in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            if (path / "type").read_text().strip() in {"x86_pkg_temp", "cpu-thermal", "cpu_thermal"}:
                value = int((path / "temp").read_text()) / 1000
                if 0 < value < 150:
                    temperatures.append(value)
        except (OSError, ValueError):
            continue
    if temperatures:
        result["cpu_temperature_c"] = round(max(temperatures), 1)
    return result


def usb_observation():
    from core import receiver_hardware, device_manager
    snap = receiver_hardware.scan(refresh=True)
    if not snap["ok"] or snap["ambiguous"]:
        return {"status": "attention" if snap["ambiguous"] else "unknown", "receivers": []}
    rows = []
    for device in device_manager.get_devices()[:16]:
        serial = device.get("serial")
        matches = [r for r in snap["receivers"] if serial and r["serial"] == serial]
        state = receiver_hardware.presence(serial, snap)
        port = matches[0]["usb_path"] if len(matches) == 1 else None
        row = {"receiver": device["number"], "presence": state, "port": port,
               "power_control": None, "runtime_status": None}
        if port:
            for field, name in (("power_control", "control"), ("runtime_status", "runtime_status")):
                try:
                    row[field] = (receiver_hardware.SYSFS / port / "power" / name).read_text().strip()[:32]
                except OSError:
                    pass
        rows.append(row)
    return {"status": "attention" if any(r["presence"] == "MISSING" for r in rows) else
            "ok" if rows and all(r["presence"] == "PRESENT" for r in rows) else "unknown",
            "receivers": rows, "scope": "Kernel USB identity only; not a live transfer test"}


def reception_runtime(label, state):
    if state != "active":
        return {"status": "idle" if state == "inactive" else "unknown"}
    from core import receiver_monitor
    if label == "AIS":
        data, _ = receiver_monitor._read_ais_ships()
        rows = receiver_monitor._extract_list(data, ("ships", "vessels", "targets", "data"))
        valid = isinstance(data, list) or isinstance(data, dict) and any(isinstance(data.get(k), list) for k in ("ships", "vessels", "targets", "data"))
        return {"status": "ok" if valid else "attention", "feed_targets_unfiltered": len(rows) if valid else None,
                "scope": "AIS feed reachable; count is not a validated live vessel count"}
    metrics = receiver_monitor.get_adsb_metrics(True)
    return {"status": "ok" if metrics.get("runtime_files_fresh") and metrics.get("samples_processed", 0) not in (0, None) else "attention",
            "runtime_files_fresh": metrics.get("runtime_files_fresh"),
            "samples_processed": metrics.get("samples_processed"),
            "scope": "Fresh decoder files and cumulative raw sample count; no throughput test"}


def snapshot(root, *, now=None):
    now = time.time() if now is None else now
    services = {}
    for label in UNITS:
        observed = observe_service(label)
        observed["reception"] = reception_runtime(label, observed["state"])
        services[label] = observed
    usb = usb_observation()
    res = resources(root)
    history = local_ai_reception.read_evidence(root, "24h", now=now)
    db = {"status": history["status"], "samples": history.get("samples"),
          "latest_sample_age_seconds": history.get("latest_sample_age_seconds"),
          "latest_sample_stale": history.get("latest_sample_stale"),
          "scope": "Bounded read test only; not a full integrity check"}
    events = {label: service_events(label) for label in UNITS}
    events["SDRCC"] = station_events(root, now)
    findings = []
    for label, item in services.items():
        if item["status"] == "attention" or item["reception"]["status"] == "attention":
            findings.append(label + " service or decoder output requires attention")
    if usb["status"] == "attention":
        findings.append("USB identity missing or ambiguous")
    if db["status"] != "ok" or db["latest_sample_stale"]:
        findings.append("Reception history missing, stale or unreadable")
    for key, value, threshold, lower in (
        ("Available RAM", res["available_ram_gib"], 2, True),
        ("Free disk", res["disk_free_gib"], 2, True),
        ("CPU load per CPU", res["load_1m_per_cpu"], 1.5, False),
        ("CPU temperature", res["cpu_temperature_c"], 85, False),
    ):
        if value is not None and (value < threshold if lower else value >= threshold):
            findings.append(key + " outside advisory threshold")
    recent = any(any(v for k, v in e.get("counts", {}).items() if k != "usb_reset_ok") for e in events.values())
    if recent:
        findings.append("Recent receiver errors or exhausted recovery in visible log entries")
    unknown = (usb["status"] == "unknown" or any(v["status"] == "unknown" or v["reception"]["status"] == "unknown" for v in services.values())
               or any(v is None for v in res.values()) or any(v["status"] != "observed" for v in events.values()))
    return {"kind": "station_health", "observed_utc": local_ai_reception.utc(int(now)),
            "status": "attention" if findings else "partial" if unknown else "ok",
            "services": services, "usb": usb, "resources": res, "database": db,
            "events_last_hour": events, "findings": findings,
            "scope": "Point-in-time observation; stopped services may be intentional. Logs bounded to last 150 entries per unit and last 64 KiB SDRCC log."}
