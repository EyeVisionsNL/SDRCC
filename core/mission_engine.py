#!/usr/bin/env python3

import json
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

STATE_FILE = PROJECT_ROOT / "data" / "state" / "mission_engine.json"

WATCH_DIRS = [
    PROJECT_ROOT / "captures",
    PROJECT_ROOT / "data" / "images",
    PROJECT_ROOT / "data" / "recordings",
    PROJECT_ROOT / "data" / "satdump",
]

IGNORE_PARTS = [
    "/test/",
    "\\test\\",
    "test_recording",
]

RECORD_EXTENSIONS = {
    ".wav", ".raw", ".iq", ".bin", ".dat", ".s", ".cadu", ".soft",
}

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".bmp",
}

ALL_EXTENSIONS = RECORD_EXTENSIONS | IMAGE_EXTENSIONS

MISSION_STEPS = [
    "IDLE",
    "WAIT FOR PASS",
    "LOCK RECEIVER",
    "RECORDING",
    "DECODING",
    "PROCESSING",
    "ARCHIVE",
    "READY",
]

STEP_PROGRESS = {
    "IDLE": 0,
    "WAIT FOR PASS": 12,
    "LOCK RECEIVER": 25,
    "RECORDING": 45,
    "DECODING": 65,
    "PROCESSING": 82,
    "ARCHIVE": 94,
    "READY": 100,
}


def now_ts():
    return int(time.time())


def ts_text(ts=None):
    if ts is None:
        ts = now_ts()
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(data):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def safe_relative(path):
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except Exception:
        return str(path)


def ignored_path(relative_path):
    low = relative_path.lower()
    return any(part in low for part in IGNORE_PARTS)


def scan_files():
    files = {}

    for watch_dir in WATCH_DIRS:
        if not watch_dir.exists():
            continue

        for path in watch_dir.rglob("*"):
            if not path.is_file():
                continue

            if path.suffix.lower() not in ALL_EXTENSIONS:
                continue

            relative = safe_relative(path)

            if ignored_path(relative):
                continue

            try:
                stat = path.stat()
            except Exception:
                continue

            files[relative] = {
                "path": relative,
                "name": path.name,
                "suffix": path.suffix.lower(),
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            }

    return files


def find_running_processes():
    patterns = [
        "satdump",
        "satdump-cli",
        "rtl_fm",
        "rtl_sdr",
        "rtl_tcp",
        "sox",
        "wxtoimg",
        "rtl_433",
    ]

    try:
        result = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            text=True,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        return []

    processes = []

    for line in result.stdout.splitlines():
        low = line.lower()

        if "mission_engine.py" in low:
            continue

        for pattern in patterns:
            if pattern in low:
                parts = line.strip().split(None, 2)
                if len(parts) >= 2:
                    processes.append({
                        "pid": parts[0],
                        "command": parts[1],
                        "args": parts[2] if len(parts) >= 3 else "",
                        "match": pattern,
                    })
                break

    return processes


def changed_files(previous_files, current_files):
    changed = []

    for path, info in current_files.items():
        previous = previous_files.get(path)

        if previous is None:
            changed.append({
                **info,
                "change": "new",
                "size_delta": info["size"],
            })
            continue

        size_delta = info["size"] - previous.get("size", 0)

        if size_delta != 0 or info["mtime"] != previous.get("mtime"):
            changed.append({
                **info,
                "change": "changed",
                "size_delta": size_delta,
            })

    return changed


def growing_record_files(changes):
    growing = []

    for item in changes:
        if item["suffix"] not in RECORD_EXTENSIONS:
            continue

        if item.get("size_delta", 0) > 0:
            growing.append(item)

    return growing


def recent_image_files(current_files, max_age=90):
    ts = now_ts()
    recent = []

    for item in current_files.values():
        if item["suffix"] not in IMAGE_EXTENSIONS:
            continue

        age = ts - item["mtime"]

        if age <= max_age:
            recent.append({
                **item,
                "age_seconds": age,
            })

    return sorted(recent, key=lambda x: x["mtime"], reverse=True)


def newest_file(current_files):
    if not current_files:
        return None

    return max(current_files.values(), key=lambda x: x["mtime"])


def process_flags(processes):
    matches = [p["match"] for p in processes]

    return {
        "satdump": any("satdump" in m for m in matches),
        "recording_tool": any(m in ["rtl_fm", "rtl_sdr", "rtl_tcp", "sox"] for m in matches),
        "decoder": any(m in ["satdump", "satdump-cli", "wxtoimg"] for m in matches),
    }


def get_next_pass_info():
    try:
        from core import passes

        pass_data = passes.get_next_pass()
        if pass_data is None:
            return None

        start_local = pass_data["start"].astimezone()
        maximum_local = pass_data["maximum"].astimezone()
        end_local = pass_data["end"].astimezone()

        return {
            "name": pass_data["name"],
            "start": start_local.strftime("%Y-%m-%d %H:%M:%S"),
            "maximum": maximum_local.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end_local.strftime("%Y-%m-%d %H:%M:%S"),
            "start_epoch": int(start_local.timestamp()),
            "maximum_epoch": int(maximum_local.timestamp()),
            "end_epoch": int(end_local.timestamp()),
            "max_elevation": float(pass_data["max_elevation"]),
            "azimuth": float(pass_data["azimuth"]),
            "frequency_mhz": round(pass_data["frequency"] / 1000000, 3),
            "mode": pass_data["mode"],
            "pipeline": pass_data.get("pipeline"),
        }
    except Exception:
        return None


def pass_state(next_pass):
    if not next_pass:
        return {
            "state": "none",
            "detail": "Geen passage bekend.",
            "seconds_to_start": None,
            "seconds_to_end": None,
            "active": False,
        }

    ts = now_ts()
    seconds_to_start = next_pass["start_epoch"] - ts
    seconds_to_end = next_pass["end_epoch"] - ts

    if next_pass["start_epoch"] <= ts <= next_pass["end_epoch"]:
        return {
            "state": "active",
            "detail": f"Pass actief: {next_pass['name']}.",
            "seconds_to_start": seconds_to_start,
            "seconds_to_end": seconds_to_end,
            "active": True,
        }

    if 0 < seconds_to_start <= 900:
        minutes = max(1, round(seconds_to_start / 60))
        return {
            "state": "soon",
            "detail": f"Volgende passage binnen {minutes} minuten: {next_pass['name']}.",
            "seconds_to_start": seconds_to_start,
            "seconds_to_end": seconds_to_end,
            "active": False,
        }

    if seconds_to_start > 900:
        minutes = round(seconds_to_start / 60)
        return {
            "state": "future",
            "detail": f"Volgende passage over {minutes} minuten: {next_pass['name']}.",
            "seconds_to_start": seconds_to_start,
            "seconds_to_end": seconds_to_end,
            "active": False,
        }

    return {
        "state": "past",
        "detail": "Laatste passage is voorbij.",
        "seconds_to_start": seconds_to_start,
        "seconds_to_end": seconds_to_end,
        "active": False,
    }


def determine_phase(previous_state, current_files, changes, processes, next_pass):
    ts = now_ts()
    flags = process_flags(processes)
    growing = growing_record_files(changes)
    recent_images = recent_image_files(current_files)
    latest = newest_file(current_files)
    pass_info = pass_state(next_pass)

    previous_phase = previous_state.get("phase", "READY")
    previous_phase_since = int(previous_state.get("phase_since", ts))

    if flags["satdump"]:
        return "DECODING", "SatDump actief: decoder draait.", growing, recent_images, pass_info

    if growing:
        names = ", ".join(item["name"] for item in growing[:3])
        return "RECORDING", f"Opname actief: groeiend bestand gedetecteerd ({names}).", growing, recent_images, pass_info

    if flags["recording_tool"]:
        return "RECORDING", "Opnameproces actief: SDR recorder draait.", growing, recent_images, pass_info

    if recent_images:
        image = recent_images[0]
        age = image["age_seconds"]

        if age <= 30:
            return "PROCESSING", f"Nieuwe afbeelding verwerkt: {image['name']}.", growing, recent_images, pass_info

        if previous_phase == "PROCESSING" and ts - previous_phase_since < 45:
            return "ARCHIVE", "Product klaar, archiveren afronden.", growing, recent_images, pass_info

    if latest:
        age = ts - latest["mtime"]

        if age <= 120:
            return "PROCESSING", f"Bestanden recent gewijzigd: {latest['name']}.", growing, recent_images, pass_info

    if pass_info["state"] == "active":
        return "LOCK RECEIVER", pass_info["detail"] + " Receiver voorbereiden of wachten op opname.", growing, recent_images, pass_info

    if pass_info["state"] == "soon":
        return "WAIT FOR PASS", pass_info["detail"], growing, recent_images, pass_info

    return "READY", "Geen actieve opname. Systeem klaar voor volgende passage.", growing, recent_images, pass_info


def build_steps(active_phase):
    active_index = MISSION_STEPS.index(active_phase) if active_phase in MISSION_STEPS else 0
    steps = []

    for index, step in enumerate(MISSION_STEPS):
        if index < active_index:
            status = "done"
        elif index == active_index:
            status = "active"
        else:
            status = "pending"

        steps.append({
            "name": step,
            "status": status,
        })

    return steps


def update_events(previous_state, phase, detail):
    ts = now_ts()
    events = previous_state.get("events", [])
    previous_phase = previous_state.get("phase")

    if phase != previous_phase:
        events.insert(0, {
            "time": ts_text(ts),
            "phase": phase,
            "detail": detail,
        })

    return events[:80]


def get_mission_status():
    previous_state = load_state()
    previous_files = previous_state.get("files", {})

    current_files = scan_files()
    changes = changed_files(previous_files, current_files)
    processes = find_running_processes()
    next_pass = get_next_pass_info()

    phase, detail, growing, recent_images, pass_info = determine_phase(
        previous_state,
        current_files,
        changes,
        processes,
        next_pass,
    )

    ts = now_ts()
    previous_phase = previous_state.get("phase")

    if phase == previous_phase:
        phase_since = int(previous_state.get("phase_since", ts))
    else:
        phase_since = ts

    events = update_events(previous_state, phase, detail)

    status = {
        "phase": phase,
        "detail": detail,
        "progress": STEP_PROGRESS.get(phase, 0),
        "steps": build_steps(phase),
        "updated": ts_text(ts),
        "phase_since": phase_since,
        "phase_age_seconds": ts - phase_since,
        "files_seen": len(current_files),
        "files_changed": len(changes),
        "processes": processes,
        "growing_files": growing[:5],
        "recent_images": recent_images[:5],
        "events": events,
        "next_pass": next_pass,
        "pass_state": pass_info,
    }

    save_state({
        "phase": phase,
        "phase_since": phase_since,
        "updated": ts,
        "files": current_files,
        "events": events,
    })

    return status


if __name__ == "__main__":
    print(json.dumps(get_mission_status(), indent=2))
