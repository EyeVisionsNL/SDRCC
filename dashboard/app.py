#!/usr/bin/env python3

import sys
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template, request, send_file, abort

from core import automation_controller
from core import device_manager
from core import event_bus
from core import live_rf
from core import config as config_core
from core import passes
from core import rf_diagnostics
from core import receiver_manager
from core import state
from core import tle
from core import system_stats
from core import mission_engine as mission_engine_core
from core import mission_history as mission_history_core
from core import mission_diagnostics
from core import mission_operations
from core import mission_result
from core import mission_preflight
from core import mission_scheduler as mission_scheduler_core
from core import mission_queue as mission_queue_core
from core import process_manager
from core import profiles
from core import satdump as satdump_core

app = Flask(__name__)

LOG_FILE = PROJECT_ROOT / "logs" / "sdrcc.log"
SDRCC_SCRIPT = PROJECT_ROOT / "scripts" / "sdrcc.py"

IMAGE_DIRS = [
    PROJECT_ROOT / "data" / "images",
    PROJECT_ROOT / "captures",
]

SERVICE_ACTIONS = {
    "start_ais": {"label": "AIS starten", "service": "ais-catcher.service", "systemctl": "start"},
    "stop_ais": {"label": "AIS stoppen", "service": "ais-catcher.service", "systemctl": "stop"},
    "restart_ais": {"label": "AIS herstarten", "service": "ais-catcher.service", "systemctl": "restart"},
    "start_adsb": {"label": "ADS-B starten", "service": "readsb.service", "systemctl": "start"},
    "stop_adsb": {"label": "ADS-B stoppen", "service": "readsb.service", "systemctl": "stop"},
    "restart_adsb": {"label": "ADS-B herstarten", "service": "readsb.service", "systemctl": "restart"},
}

SCHEDULER_ACTIONS = {
    "scheduler_auto": {
        "label": "Scheduler AUTO",
        "mode": "AUTO",
    },
    "scheduler_manual": {
        "label": "Scheduler MANUAL",
        "mode": "MANUAL",
    },
    "scheduler_paused": {
        "label": "Scheduler PAUSED",
        "mode": "PAUSED",
    },
}


SCHEDULER_ACTIONS = {
    "scheduler_auto": {
        "label": "Scheduler AUTO",
        "mode": "AUTO",
    },
    "scheduler_manual": {
        "label": "Scheduler MANUAL",
        "mode": "MANUAL",
    },
    "scheduler_paused": {
        "label": "Scheduler PAUSED",
        "mode": "PAUSED",
    },
}


PROFILE_ACTIONS = {
    "profile_adsb": {
        "label": "Profiel ADS-B",
        "profile": "adsb",
    },
    "profile_weather": {
        "label": "Profiel Weather",
        "profile": "weather",
    },
    "profile_manual": {
        "label": "Profiel Manual",
        "profile": "manual",
    },
}


SDRCC_ACTIONS = {
    "next_pass": {"label": "Volgende passage", "command": [sys.executable, str(SDRCC_SCRIPT), "next"], "mode": "run"},
    "schedule": {"label": "Planning tonen", "command": [sys.executable, str(SDRCC_SCRIPT), "schedule"], "mode": "run"},
    "simulate_record": {"label": "Simuleer opname", "command": [sys.executable, str(SDRCC_SCRIPT), "simulate-record"], "mode": "run"},
    "record": {"label": "Record NOW", "command": [sys.executable, str(SDRCC_SCRIPT), "record"], "mode": "start"},
    "update_tle": {"label": "Update TLE", "command": [sys.executable, str(SDRCC_SCRIPT), "update-tle"], "mode": "run"},
}

ACTIONS = {}
ACTIONS.update(SERVICE_ACTIONS)
ACTIONS.update(SCHEDULER_ACTIONS)
ACTIONS.update(PROFILE_ACTIONS)
ACTIONS.update(SDRCC_ACTIONS)


def write_log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def run_command(command, timeout=60):
    return subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def run_systemctl(action, service):
    return run_command(["sudo", "-n", "systemctl", action, service], timeout=30)


def service_state(service_name):
    active_result = subprocess.run(
        ["systemctl", "is-active", service_name],
        text=True,
        capture_output=True,
        timeout=10,
    )

    enabled_result = subprocess.run(
        ["systemctl", "is-enabled", service_name],
        text=True,
        capture_output=True,
        timeout=10,
    )

    active_text = active_result.stdout.strip()
    enabled_text = enabled_result.stdout.strip()

    return {
        "service": service_name,
        "active": active_text == "active",
        "state": active_text if active_text else "unknown",
        "enabled": enabled_text if enabled_text else "unknown",
    }


def serialize_pass(pass_data):
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
        "max_elevation": pass_data["max_elevation"],
        "azimuth": pass_data["azimuth"],
        "frequency_mhz": round(pass_data["frequency"] / 1000000, 3),
        "mode": pass_data["mode"],
        "pipeline": pass_data.get("pipeline"),
    }


def read_log_lines(limit=120):
    if not LOG_FILE.exists():
        return ["Logbestand bestaat nog niet."]

    try:
        lines = LOG_FILE.read_text(errors="ignore").splitlines()
        if not lines:
            return ["Logbestand is leeg."]
        return lines[-limit:]
    except Exception as error:
        return [f"Log lezen mislukt: {error}"]


def detect_image_size(path):
    try:
        with path.open("rb") as file:
            header = file.read(32)

        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            width = int.from_bytes(header[16:20], "big")
            height = int.from_bytes(header[20:24], "big")
            return width, height

        if header.startswith(b"\xff\xd8"):
            with path.open("rb") as file:
                file.read(2)
                while True:
                    marker_start = file.read(1)
                    if not marker_start:
                        break
                    if marker_start != b"\xff":
                        continue

                    marker = file.read(1)
                    while marker == b"\xff":
                        marker = file.read(1)

                    if marker in [b"\xc0", b"\xc2"]:
                        file.read(3)
                        height = int.from_bytes(file.read(2), "big")
                        width = int.from_bytes(file.read(2), "big")
                        return width, height

                    length_bytes = file.read(2)
                    if len(length_bytes) != 2:
                        break
                    length = int.from_bytes(length_bytes, "big")
                    file.seek(length - 2, 1)

    except Exception:
        return None, None

    return None, None


def classify_capture(path):
    name = path.name.lower()

    if "meteor" in name or "m2" in name:
        satellite = "METEOR"
        pipeline = "LRPT"
    elif "noaa" in name:
        satellite = "NOAA"
        pipeline = "APT"
    else:
        satellite = "Onbekend"
        pipeline = "Onbekend"

    if "rgb" in name:
        product = "RGB Composite"
    elif "ir" in name or "thermal" in name:
        product = "Infrared / Thermal"
    elif "221" in name:
        product = "221 Composite"
    else:
        product = "Image"

    return satellite, pipeline, product


def capture_to_dict(path):
    stat = path.stat()
    relative = path.relative_to(PROJECT_ROOT)
    age_seconds = int(datetime.now().timestamp() - stat.st_mtime)
    width, height = detect_image_size(path)
    satellite, pipeline, product = classify_capture(path)

    return {
        "filename": path.name,
        "relative_path": str(relative),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_kb": round(stat.st_size / 1024, 1),
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "age_seconds": age_seconds,
        "live": age_seconds <= 60,
        "url": "/capture/" + str(relative).replace("\\", "/"),
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else "-",
        "satellite": satellite,
        "pipeline": pipeline,
        "product": product,
    }


def find_capture_files():
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    candidates = []

    for image_dir in IMAGE_DIRS:
        if not image_dir.exists():
            continue

        for path in image_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed_extensions:
                candidates.append(path)

    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def find_latest_capture():
    files = find_capture_files()
    if not files:
        return None
    return capture_to_dict(files[0])


def recent_captures(limit=10):
    return [capture_to_dict(path) for path in find_capture_files()[:limit]]



MISSION_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MISSION_RECORDING_EXTENSIONS = {".wav", ".raw", ".iq", ".cfile", ".bin"}
MISSION_LOG_EXTENSIONS = {".log", ".txt"}
MISSION_TELEMETRY_EXTENSIONS = {".json", ".csv", ".cadu"}


def _mission_event_matches(event, mission_id):
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if str(data.get("mission_id") or "") == mission_id:
        return True
    cancelled = data.get("cancelled_job")
    return isinstance(cancelled, dict) and str(cancelled.get("mission_id") or "") == mission_id


def _mission_output_inventory(mission):
    output_value = str(mission.get("output_path") or "").strip()
    inventory = {
        "available": False,
        "output_path": output_value,
        "recording": {"available": False, "count": 0, "bytes": 0},
        "images": {"available": False, "count": 0, "bytes": 0},
        "logs": {"available": False, "count": 0, "bytes": 0},
        "telemetry": {"available": False, "count": 0, "bytes": 0},
        "other": {"available": False, "count": 0, "bytes": 0},
        "preview": None,
        "image_files": [],
    }
    if not output_value:
        return inventory

    root = Path(output_value).expanduser()
    try:
        root = root.resolve()
    except OSError:
        return inventory
    if not root.exists() or not root.is_dir():
        return inventory

    inventory["available"] = True
    image_candidates = []
    try:
        files = [path for path in root.rglob("*") if path.is_file()]
    except OSError:
        files = []

    for path in files[:5000]:
        suffix = path.suffix.lower()
        name = path.name.lower()
        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        if suffix in MISSION_IMAGE_EXTENSIONS:
            bucket = "images"
            image_candidates.append(path)
        elif suffix in MISSION_RECORDING_EXTENSIONS:
            bucket = "recording"
        elif suffix in MISSION_LOG_EXTENSIONS or "log" in name:
            bucket = "logs"
        elif suffix in MISSION_TELEMETRY_EXTENSIONS or "telemetry" in name:
            bucket = "telemetry"
        else:
            bucket = "other"

        inventory[bucket]["count"] += 1
        inventory[bucket]["bytes"] += size
        inventory[bucket]["available"] = True

    if image_candidates:
        image_candidates = sorted(
            image_candidates,
            key=lambda path: (
                str(path.relative_to(root).parent).lower(),
                path.name.lower(),
            ),
        )
        for path in image_candidates[:500]:
            relative = path.relative_to(root)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            relative_value = str(relative).replace(chr(92), "/")
            inventory["image_files"].append({
                "filename": path.name,
                "relative_path": relative_value,
                "directory": str(relative.parent).replace(chr(92), "/"),
                "bytes": size,
                "url": f"/mission-preview/{mission.get('mission_id')}/{relative_value}",
            })

        newest = max(image_candidates, key=lambda path: path.stat().st_mtime if path.exists() else 0)
        relative = newest.relative_to(root)
        relative_value = str(relative).replace(chr(92), "/")
        inventory["preview"] = {
            "filename": newest.name,
            "relative_path": relative_value,
            "url": f"/mission-preview/{mission.get('mission_id')}/{relative_value}",
        }

    return inventory


def _mission_quality(mission, events, inventory):
    mission = mission_result.normalize_history_mission(mission)
    result = str(mission.get("result") or mission.get("status") or "UNKNOWN").upper()
    event_text = " ".join(
        f"{event.get('category', '')} {event.get('title', '')} {event.get('detail', '')}"
        for event in events
    ).upper()
    frames = int(mission.get("frames") or 0)
    cadu = int(mission.get("cadu_bytes") or 0)
    images = max(int(mission.get("image_count") or 0), inventory["images"]["count"])

    return {
        "result": result,
        "receiver_lock": bool(mission.get("receiver")) and (
            "LOCK RECEIVER" in event_text or "RECEIVER GELOCKED" in event_text or "RECEIVER LOCK" in event_text
        ),
        "recording": bool(mission.get("started_at")) or "RECORDING" in event_text or inventory["recording"]["available"],
        "decoder": images > 0,
        "images": images,
        "peak_snr_db": mission.get("peak_snr_db"),
    }

def get_mission_data_for_status():
    mission = mission_engine_core.get_mission_status()

    step_objects = mission.get("steps", [])
    step_names = [step.get("name", "-") for step in step_objects]

    active_index = 0
    for index, step in enumerate(step_objects):
        if step.get("status") == "active":
            active_index = index
            break

    mission["step_states"] = step_objects
    mission["steps"] = step_names
    mission["active_index"] = active_index

    return mission


def get_dashboard_data():
    sdr2 = state.get_sdr2_state()
    raw_next_pass = passes.get_next_pass()
    next_pass = serialize_pass(raw_next_pass)
    devices = device_manager.get_devices()

    ais = service_state("ais-catcher.service")
    adsb = service_state("readsb.service")
    logs = read_log_lines()
    latest_capture = find_latest_capture()
    captures = recent_captures()
    mission = get_mission_data_for_status()
    scheduler = mission_scheduler_core.get_scheduler_status()
    assignments = config_core.get_receiver_assignments()

    mission_phase = str(mission.get("state") or mission.get("phase") or "").upper()
    observer_phase = str((scheduler.get("observer") or {}).get("phase") or "").upper()
    weather_active = mission_phase in {"LOCK RECEIVER", "RECORDING"} or observer_phase in {
        "PREPARE RECEIVER",
        "FINAL APPROACH",
        "PASS ACTIVE",
    }

    for device in devices:
        device_id = device.get("id")

        default_tasks = []
        if assignments.get("ais") == device_id:
            default_tasks.append("AIS")
        if assignments.get("adsb") == device_id:
            default_tasks.append("ADS-B")
        default_task = " / ".join(default_tasks) if default_tasks else "Vrij"

        current_task = "Vrij"
        active_detail = "Geen actieve service"
        status_label = "AVAILABLE"

        if weather_active and assignments.get("weather") == device_id:
            current_task = "Weather / METEOR"
            active_detail = "Actieve satellietmissie"
            status_label = "LOCKED"
        elif assignments.get("ais") == device_id and ais.get("active"):
            current_task = "AIS"
            active_detail = "ais-catcher.service"
            status_label = "IN USE"
        elif assignments.get("adsb") == device_id and adsb.get("active"):
            current_task = "ADS-B"
            active_detail = "readsb.service"
            status_label = "IN USE"

        next_task = (
            "Weather / METEOR"
            if assignments.get("weather") == device_id and not weather_active
            else "-"
        )

        device["default_task"] = default_task
        device["current_task"] = current_task
        device["next_task"] = next_task
        device["active_detail"] = active_detail
        device["status_label"] = status_label
        device["in_use"] = status_label in {"IN USE", "LOCKED"}

    return {
        "server_time_epoch": int(datetime.now().timestamp()),
        "sdr2": sdr2,
        "next_pass": next_pass,
        "ais": ais,
        "adsb": adsb,
        "devices": devices,
        "assignments": assignments,
        "weather_rf": config_core.get_weather_rf_config(),
        "tle_present": tle.exists(),
        "system": system_stats.get_stats(),
        "logs": logs,
        "latest_capture": latest_capture,
        "recent_captures": captures,
        "mission": mission,
        "scheduler": scheduler,
        "actions": [{"id": action_id, "label": data["label"]} for action_id, data in ACTIONS.items()],
    }


def handle_service_action(action_id, action):
    service = action["service"]
    systemctl_action = action["systemctl"]
    label = action["label"]

    before = service_state(service)
    write_log(f"{label}: service was {before['state']}")

    result = run_systemctl(systemctl_action, service)

    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            write_log(line)

    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            write_log("ERROR: " + line)

    after = service_state(service)

    if result.returncode == 0:
        write_log(f"{label}: service is nu {after['state']}")
        return jsonify({
            "ok": True,
            "message": f"{label} uitgevoerd. Status: {after['state']}",
            "before": before,
            "after": after,
        })

    write_log(f"{label}: mislukt met returncode {result.returncode}")
    return jsonify({
        "ok": False,
        "message": f"{label} mislukt. Status: {after['state']}",
        "before": before,
        "after": after,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }), 500


def wait_for_profile_stopped(profile_name, timeout=15):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        profile_status = process_manager.get_profile_process_status(
            profile_name
        )

        if profile_status is None:
            return False

        service_active = profile_status.get("active", False)
        process_running = bool(
            str(profile_status.get("process", "")).strip()
        )

        if not service_active and not process_running:
            return True

        time.sleep(0.5)

    return False


def monitor_record_process(process):
    try:
        stdout, stderr = process.communicate()

        if stdout:
            for line in stdout.strip().splitlines():
                write_log(line)

        if stderr:
            for line in stderr.strip().splitlines():
                write_log("ERROR: " + line)

        if process.returncode == 0:
            write_log("Mission Engine: SatDump-opname succesvol afgerond")

            mission_engine_core.mission_set_state("DECODING")
            time.sleep(1)

            mission_engine_core.mission_set_state("PROCESSING")
            time.sleep(1)

            mission_engine_core.mission_set_state("ARCHIVING")
            time.sleep(1)

            mission_engine_core.mission_finish_job(success=True)
            mission_engine_core.mission_set_state("READY")

            write_log("Mission Engine: Mission Job succesvol afgerond")

        else:
            error_message = (
                f"SatDump gestopt met foutcode {process.returncode}"
            )

            write_log(f"Mission Engine: {error_message}")
            mission_engine_core.mission_finish_job(
                success=False,
                error=error_message,
            )
            mission_engine_core.mission_set_state("READY")

    except Exception as error:
        write_log(f"Mission Engine procesbewaking mislukt: {error}")

        try:
            mission_engine_core.mission_finish_job(
                success=False,
                error=str(error),
            )
            mission_engine_core.mission_set_state("READY")
        except Exception as reset_error:
            write_log(
                "Mission Engine kon na procesfout niet herstellen: "
                f"{reset_error}"
            )


def wait_for_service(service_name, expected_state, timeout=15):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        current_state = service_state(service_name)["state"]

        if current_state == expected_state:
            return True

        time.sleep(0.5)

    return False


def handle_scheduler_action(action):
    mode = action["mode"]
    label = action["label"]

    scheduler = mission_scheduler_core.set_scheduler_mode(mode)

    write_log(
        f"Scheduler-modus gewijzigd naar {scheduler['mode']}"
    )

    return jsonify({
        "ok": True,
        "message": f"{label} actief.",
        "scheduler": scheduler,
    })


def handle_profile_action(action):
    profile_name = action["profile"]
    label = action["label"]
    current_sdr = state.get_sdr2_state()

    if current_sdr.get("locked"):
        return jsonify({
            "ok": False,
            "message": "Profiel wisselen kan niet: SDR2 is gelocked.",
        }), 409

    write_log(f"Profielwissel gestart: {profile_name}")

    if profile_name == "weather":
        device = device_manager.get_weather_device()
        if device is None:
            return jsonify({
                "ok": False,
                "message": "Geen Weather-ontvanger toegewezen.",
            }), 400
        conflict_service = device_manager.get_conflicting_service(device["id"])
        if conflict_service and service_state(conflict_service)["active"]:
            result = run_systemctl("stop", conflict_service)
            if result.returncode != 0:
                return jsonify({
                    "ok": False,
                    "message": f"{conflict_service} kon niet worden gestopt.",
                    "error": result.stderr,
                }), 500
            if not wait_for_service(conflict_service, "inactive"):
                return jsonify({
                    "ok": False,
                    "message": f"{conflict_service} stopte niet volledig.",
                }), 500
        write_log(
            f"Weather-profiel gebruikt {device['number']} "
            f"({device['serial']})"
        )

    elif profile_name == "adsb":
        ais_result = run_systemctl("start", "ais-catcher.service")
        adsb_result = run_systemctl("start", "readsb.service")

        if ais_result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher kon niet worden gestart.",
                "error": ais_result.stderr,
            }), 500

        if adsb_result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "ADS-B kon niet worden gestart.",
                "error": adsb_result.stderr,
            }), 500

        if not wait_for_service("ais-catcher.service", "active"):
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher werd niet actief.",
            }), 500

        if not wait_for_service("readsb.service", "active"):
            return jsonify({
                "ok": False,
                "message": "ADS-B werd niet actief.",
            }), 500

    elif profile_name == "manual":
        adsb_result = run_systemctl("stop", "readsb.service")
        ais_result = run_systemctl("start", "ais-catcher.service")

        if adsb_result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "ADS-B kon niet worden gestopt.",
                "error": adsb_result.stderr,
            }), 500

        if ais_result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher kon niet worden gestart.",
                "error": ais_result.stderr,
            }), 500

        if not wait_for_service("readsb.service", "inactive"):
            return jsonify({
                "ok": False,
                "message": "ADS-B stopte niet volledig.",
            }), 500

        if not wait_for_service("ais-catcher.service", "active"):
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher werd niet actief.",
            }), 500

    profile = profiles.set_active_profile(profile_name)

    write_log(
        f"Profielwissel voltooid: {profile_name} ({profile['name']})"
    )

    return jsonify({
        "ok": True,
        "message": f"{label} actief.",
        "profile": profile_name,
    })


def handle_sdrcc_action(action_id, action):
    label = action["label"]
    command = action["command"]
    mode = action["mode"]

    write_log(f"Dashboard actie gestart: {label}")

    if mode == "start":
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if action_id == "record":
            watcher = threading.Thread(
                target=monitor_record_process,
                args=(process,),
                daemon=True,
                name="sdrcc-record-monitor",
            )
            watcher.start()

        write_log(
            f"Dashboard actie loopt op achtergrond: {label} "
            f"(PID {process.pid})"
        )

        return jsonify({
            "ok": True,
            "message": f"{label} gestart.",
            "pid": process.pid,
        })

    result = run_command(command, timeout=60)

    if result.stdout.strip():
        for line in result.stdout.strip().splitlines():
            write_log(line)

    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            write_log("ERROR: " + line)

    if result.returncode == 0:
        write_log(f"Dashboard actie klaar: {label}")
        return jsonify({
            "ok": True,
            "message": f"{label} uitgevoerd.",
            "output": result.stdout,
        })

    write_log(f"Dashboard actie fout: {label} returncode {result.returncode}")
    return jsonify({
        "ok": False,
        "message": f"{label} gaf een fout.",
        "output": result.stdout,
        "error": result.stderr,
    }), 500


AUTOPILOT_POLL_SECONDS = 0.5

autopilot_runtime = {
    "pass_key": None,
    "target_pass": None,
    "preflight_ok": False,
    "last_preflight_attempt": 0.0,
    "prepared": False,
    "locked": False,
    "record_started": False,
    "record_data": None,
    "restore_service": None,
    "restore_service_was_active": False,
    "dry_run_completed": False,
}


def reset_autopilot_runtime(target_pass=None):
    autopilot_runtime.update({
        "pass_key": (
            f"{target_pass['name']}:{target_pass['start_epoch']}"
            if target_pass
            else None
        ),
        "target_pass": target_pass,
        "preflight_ok": False,
        "last_preflight_attempt": 0.0,
        "prepared": False,
        "locked": False,
        "record_started": False,
        "record_data": None,
        "restore_service": None,
        "restore_service_was_active": False,
        "dry_run_completed": False,
    })


def autopilot_prepare_receiver():
    write_log("AUTO: T-90 ontvanger voorbereiden")
    device = device_manager.get_weather_device()
    if device is None:
        raise RuntimeError("Geen Weather-ontvanger toegewezen")

    receiver_manager.reserve(
        device["id"],
        mission_key=autopilot_runtime["pass_key"],
        reason="AUTO Weather-missie",
    )

    conflict_service = device_manager.get_conflicting_service(device["id"])
    was_active = bool(
        conflict_service
        and service_state(conflict_service)["active"]
    )
    autopilot_runtime["restore_service"] = conflict_service
    autopilot_runtime["restore_service_was_active"] = was_active

    if was_active:
        result = run_systemctl("stop", conflict_service)
        if result.returncode != 0:
            raise RuntimeError(
                f"{conflict_service} kon niet worden gestopt: "
                + result.stderr.strip()
            )
        if not wait_for_service(conflict_service, "inactive"):
            raise RuntimeError(f"{conflict_service} stopte niet volledig")

    profiles.set_active_profile("weather")
    write_log(
        f"AUTO: Weather actief op {device['number']} "
        f"({device['serial']}); conflict={conflict_service or 'geen'}"
    )
    event_bus.publish_receiver(
        "INFO",
        "Weather-receiver voorbereid",
        f"{device['number']} ({device['serial']}) is beschikbaar voor AUTO",
        data={
            "device_id": device["id"],
            "serial": device["serial"],
            "conflict_service": conflict_service,
            "conflict_was_active": was_active,
        },
    )


def autopilot_lock_receiver():
    record_data = satdump_core.build_record_command()

    if record_data is None:
        raise RuntimeError("Geen geschikte passage gevonden")

    if not record_data["allowed"]:
        raise RuntimeError(record_data["reason"])

    pass_data = record_data["pass"]
    target = autopilot_runtime["target_pass"]

    if target is not None:
        expected_start = int(target["start_epoch"])
        actual_start = int(pass_data["start"].timestamp())

        if abs(expected_start - actual_start) > 5:
            raise RuntimeError(
                "SatDump-pass wijkt af van de geplande AUTO-pass"
            )

    record_data["output_path"].mkdir(
        parents=True,
        exist_ok=True,
    )

    mission_status = mission_engine_core.get_mission_status()

    if mission_status.get("active_job") is None:
        mission_engine_core.mission_create_job(
            satellite=pass_data["name"],
            frequency=pass_data["frequency"],
            mode=pass_data["mode"],
            pipeline=pass_data["pipeline"],
            output_path=str(record_data["output_path"]),
            receiver=record_data["device"]["number"],
            receiver_id=record_data["device"]["id"],
            receiver_serial=record_data["device"]["serial"],
            min_elevation=pass_data.get("min_elevation"),
            max_elevation=pass_data.get("max_elevation"),
            azimuth=pass_data.get("azimuth"),
            sample_rate=pass_data.get("sample_rate"),
            gain_mode=(record_data.get("rf") or {}).get("gain_mode"),
            gain_db=(record_data.get("rf") or {}).get("gain_db"),
            dc_block=(record_data.get("rf") or {}).get("dc_block"),
            iq_swap=(record_data.get("rf") or {}).get("iq_swap"),
        )

    mission_engine_core.mission_set_state("LOCK RECEIVER")
    autopilot_runtime["record_data"] = record_data

    write_log(
        "AUTO: T-30 receiver gelocked voor "
        f"{pass_data['name']} / {record_data['device']['serial']}"
    )
    event_bus.publish_receiver(
        "SYSTEM",
        "Receiver gelocked",
        f"{record_data['device']['number']} voor {pass_data['name']}",
        data={
            "device_id": record_data["device"]["id"],
            "serial": record_data["device"]["serial"],
            "satellite": pass_data["name"],
            "mission_id": (
                mission_engine_core.get_mission_status().get("active_job") or {}
            ).get("mission_id"),
        },
    )


def monitor_auto_record_process(process):
    output_lines = []
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                output_lines.append(line)
                write_log(line)
                live_rf.update_line(line)

        process.wait()
        live_stdout = "\n".join(output_lines)
        record_data = autopilot_runtime.get("record_data") or {}
        output_path = record_data.get("output_path")
        pipeline = (record_data.get("pass") or {}).get("pipeline")

        initial = satdump_core.analyze_satdump_result(
            returncode=process.returncode,
            stdout=live_stdout,
            stderr="",
            output_path=output_path,
            context=satdump_core.build_event_context(record_data),
        )

        decode_data = None
        combined_stdout = live_stdout
        final_returncode = process.returncode

        if (
            process.returncode == 0
            and initial.get("cadu_bytes", 0) > 0
            and initial.get("image_count", 0) == 0
            and output_path
            and pipeline
        ):
            mission_engine_core.mission_set_state("DECODING")
            write_log(
                "AUTO: live-opname bevat CADU maar nog geen beelden; "
                "offline productdecode gestart"
            )
            event_bus.publish_satdump(
                "INFO",
                "SatDump productdecode gestart",
                "CADU wordt verwerkt naar METEOR-beeldproducten",
                data=satdump_core.build_event_context(record_data),
            )

            decode_data = satdump_core.decode_cadu_products(
                output_path=output_path,
                pipeline=pipeline,
                line_callback=lambda line: (
                    write_log(line),
                    live_rf.update_line(line),
                ),
            )
            combined_stdout = "\n".join(
                part
                for part in (live_stdout, decode_data.get("stdout", ""))
                if part
            )
            final_returncode = decode_data.get("returncode")
            mission_engine_core.mission_set_state("PROCESSING")

            event_bus.publish_satdump(
                "INFO" if final_returncode == 0 else "WARNING",
                "SatDump productdecode afgerond",
                f"Returncode {final_returncode}; output wordt gevalideerd",
                data={
                    **satdump_core.build_event_context(record_data),
                    "returncode": final_returncode,
                    "command": decode_data.get("command"),
                    "cadu_file": decode_data.get("cadu_file"),
                    "products_dir": decode_data.get("products_dir"),
                    "log_file": decode_data.get("log_file"),
                },
            )

        analysis = satdump_core.analyze_satdump_result(
            returncode=final_returncode,
            stdout=combined_stdout,
            stderr="",
            output_path=output_path,
            context=satdump_core.build_event_context(record_data),
        )
        live_rf.finish(analysis)

        write_log(
            "AUTO: SatDump-resultaat "
            f"{analysis['result']} - {analysis['detail']}"
        )

        mission_engine_core.mission_set_state("ARCHIVING")

        active_job = (
            mission_engine_core.get_mission_status().get("active_job") or {}
        )
        diagnostics = mission_diagnostics.write_mission_diagnostics(
            mission={
                **active_job,
                "result": analysis.get("result"),
                "detail": analysis.get("detail"),
                "error": analysis.get("error"),
                "peak_snr_db": analysis.get("peak_snr_db"),
                "frames": analysis.get("frames"),
                "cadu_bytes": analysis.get("cadu_bytes"),
                "image_count": analysis.get("image_count"),
                "duration_seconds": record_data.get("timeout_seconds"),
                "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            pass_data=record_data.get("pass") or {},
            rf=record_data.get("rf") or {},
            analysis=analysis,
            live_returncode=process.returncode,
            live_command=record_data.get("command"),
            decode_data=decode_data,
        )

        metrics = {
            "peak_snr_db": analysis.get("peak_snr_db"),
            "frames": analysis.get("frames"),
            "cadu_bytes": analysis.get("cadu_bytes"),
            "image_count": analysis.get("image_count"),
            "duration_seconds": record_data.get("timeout_seconds"),
            "quality_score": diagnostics.get("quality_score"),
            "quality_grade": diagnostics.get("quality_grade"),
            "diagnostics_path": diagnostics.get("diagnostics_file"),
        }

        write_log(
            "AUTO: Mission Summary | "
            f"satellite={record_data.get('pass', {}).get('name', '-')} | "
            f"duration={metrics.get('duration_seconds', '-')}s | "
            f"peak_snr={metrics.get('peak_snr_db')} dB | "
            f"frames={metrics.get('frames', 0)} | "
            f"images={metrics.get('image_count', 0)} | "
            f"result={analysis['result']}"
        )

        mission_engine_core.mission_finish_job(
            success=analysis["success"],
            result=analysis["result"],
            detail=analysis["detail"],
            error=analysis.get("error"),
            metrics=metrics,
        )

    except Exception as error:
        write_log(f"AUTO: procesbewaking mislukt: {error}")
        try:
            live_rf.fail(str(error))
        except Exception as live_rf_error:
            write_log(f"AUTO: Live RF kon niet worden afgerond: {live_rf_error}")

        try:
            mission_engine_core.mission_finish_job(
                success=False,
                error=str(error),
            )
        except Exception as finish_error:
            write_log(
                "AUTO: Mission Job kon niet worden afgerond: "
                f"{finish_error}"
            )

    finally:
        restore_service = autopilot_runtime.get("restore_service")
        restore_needed = autopilot_runtime.get("restore_service_was_active", False)

        if restore_service and restore_needed:
            write_log(f"AUTO: {restore_service} herstellen")
            result = run_systemctl("start", restore_service)
            if result.returncode != 0:
                write_log(
                    f"AUTO ERROR: {restore_service} kon niet worden gestart: "
                    + result.stderr.strip()
                )
            elif not wait_for_service(restore_service, "active"):
                write_log(f"AUTO ERROR: {restore_service} werd niet actief")
            else:
                write_log(f"AUTO: {restore_service} is weer actief")
                event_bus.publish_receiver(
                    "SUCCESS",
                    "Receiver-service hersteld",
                    f"{restore_service} is weer actief",
                    data={"service": restore_service},
                )

        profiles.set_active_profile("adsb")

        released_data = autopilot_runtime.get("record_data") or {}
        try:
            receiver_manager.release(
                mission_key=autopilot_runtime.get("pass_key"),
                detail="Weather-receiver is vrijgegeven na de missie",
            )
        except Exception as release_error:
            write_log(f"AUTO ERROR: receiver vrijgeven mislukt: {release_error}")
        event_bus.publish_receiver(
            "INFO",
            "Receiver vrijgegeven",
            "Weather-receiver is vrijgegeven na de missie",
            data=satdump_core.build_event_context(released_data),
        )
        mission_engine_core.mission_set_state("READY")
        write_log("AUTO: missie afgerond; profiel terug naar ADS-B")


def autopilot_start_recording():
    record_data = autopilot_runtime.get("record_data")

    if record_data is None:
        raise RuntimeError(
            "Geen voorbereid SatDump-commando beschikbaar"
        )

    mission_status = mission_engine_core.get_mission_status()
    active_job = mission_status.get("active_job") or {}
    receiver_manager.activate(
        mission_key=autopilot_runtime["pass_key"],
        mission_id=active_job.get("mission_id"),
    )

    mission_engine_core.mission_set_state("RECORDING")

    process = subprocess.Popen(
        record_data["command"],
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    live_rf.start(record_data, process.pid)

    watcher = threading.Thread(
        target=monitor_auto_record_process,
        args=(process,),
        daemon=True,
        name="sdrcc-auto-record-monitor",
    )
    watcher.start()

    write_log(
        "AUTO: SatDump gestart "
        f"(PID {process.pid}) voor "
        f"{record_data['pass']['name']}"
    )
    event_bus.publish_satdump(
        "INFO",
        "SatDump AUTO gestart",
        f"PID {process.pid} voor {record_data['pass']['name']}",
        data={
            **satdump_core.build_event_context(record_data),
            "pid": process.pid,
        },
    )


def mission_autopilot_worker():
    write_log("AUTO-controller gestart")

    while True:
        try:
            scheduler = mission_scheduler_core.get_scheduler_status()
            mode = str(scheduler.get("mode") or "MANUAL").upper()
            next_pass = scheduler.get("next_pass")
            controller = automation_controller.get_status(
                mode=mode,
                next_pass=next_pass,
            )

            if mode == "MANUAL":
                automation_controller.update_status(
                    "MANUAL",
                    "Automation Controller staat in handmatige modus",
                    next_action="Wachten op AUTO-modus",
                )
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            if mode == "PAUSED":
                automation_controller.update_status(
                    "PAUSED",
                    "Nieuwe automatische missies zijn gepauzeerd",
                    next_action="Lopende missie veilig laten afronden",
                    target_pass=autopilot_runtime.get("target_pass"),
                )
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            if controller.get("manual_override") and not autopilot_runtime.get("record_started"):
                automation_controller.update_status(
                    "MANUAL OVERRIDE",
                    "Automatische voorbereiding is tijdelijk geblokkeerd",
                    next_action="Manual Override opheffen",
                    target_pass=autopilot_runtime.get("target_pass") or next_pass,
                )
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue


            if automation_controller.is_pass_skipped(next_pass):
                automation_controller.update_status(
                    "SKIPPED",
                    f"{next_pass.get('name', 'Passage')} wordt overgeslagen",
                    next_action="Wachten op volgende passage",
                    target_pass=next_pass,
                )
                if autopilot_runtime.get("target_pass") and not autopilot_runtime.get("record_started"):
                    reset_autopilot_runtime()
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            if autopilot_runtime["target_pass"] is None and next_pass is not None:
                reset_autopilot_runtime(next_pass)
                write_log(
                    "AUTO: passage geselecteerd: "
                    f"{next_pass['name']} om {next_pass['start']}"
                )
                event_bus.publish_automation(
                    "INFO",
                    "Passage geselecteerd",
                    f"{next_pass['name']} om {next_pass['start']}",
                    data={"pass": next_pass},
                )

            target = autopilot_runtime["target_pass"]

            if target is None:
                automation_controller.update_status(
                    "WAITING",
                    "Geen geschikte passage gepland",
                    next_action="Wachten op passageplanning",
                )
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            now_epoch = int(time.time())
            start_epoch = int(target["start_epoch"])
            end_epoch = int(target["end_epoch"])
            seconds_until_start = start_epoch - now_epoch

            config = scheduler["observer"]["config"]
            preflight_seconds = int(config["preflight_seconds"])
            prepare_seconds = int(config["prepare_seconds"])
            lock_seconds = int(config["lock_seconds"])
            dry_run = bool(controller.get("dry_run"))

            status = "WAITING"
            detail = f"Wachten op {target['name']}"
            next_action = "Preflight uitvoeren"
            if 0 < seconds_until_start <= preflight_seconds:
                status = "PREFLIGHT"
                detail = "Preflightvenster is actief"
                next_action = "Receiver voorbereiden"
            if 0 < seconds_until_start <= prepare_seconds:
                status = "PREPARING"
                detail = "Receiver voorbereiden"
                next_action = "Receiver locken"
            if 0 < seconds_until_start <= lock_seconds:
                status = "LOCKING"
                detail = "Receiver locken en laatste controles"
                next_action = "Opname starten bij AOS"
            if autopilot_runtime.get("dry_run_completed"):
                status = "DRY RUN COMPLETE"
                detail = f"Volledige beslisketen voor {target['name']} doorlopen"
                next_action = "Wachten tot passage is beëindigd"
            elif autopilot_runtime.get("record_started"):
                status = "RECORDING"
                detail = "Automatische opname is actief"
                next_action = "Opname afhandelen"

            automation_controller.update_status(
                status,
                detail + (" (DRY RUN)" if dry_run else ""),
                next_action=next_action,
                target_pass=target,
            )

            if (
                0 < seconds_until_start <= preflight_seconds
                and not autopilot_runtime["preflight_ok"]
                and time.monotonic() - autopilot_runtime["last_preflight_attempt"] >= 10
            ):
                autopilot_runtime["last_preflight_attempt"] = time.monotonic()
                result = mission_preflight.run_preflight()
                if result["passed"]:
                    autopilot_runtime["preflight_ok"] = True
                    write_log(f"AUTO: preflight OK voor {target['name']}")
                else:
                    write_log(f"AUTO: preflight FAILED: {result['detail']}")

            if (
                0 < seconds_until_start <= prepare_seconds
                and autopilot_runtime["preflight_ok"]
                and not autopilot_runtime["prepared"]
            ):
                if dry_run:
                    autopilot_runtime["prepared"] = True
                    event_bus.publish_automation(
                        "INFO",
                        "Dry Run: receiver voorbereiden",
                        f"Receiver voor {target['name']} zou nu worden voorbereid",
                        data={"pass": target, "dry_run": True},
                    )
                else:
                    autopilot_prepare_receiver()
                    autopilot_runtime["prepared"] = True

            if (
                0 < seconds_until_start <= lock_seconds
                and autopilot_runtime["prepared"]
                and not autopilot_runtime["locked"]
            ):
                if dry_run:
                    autopilot_runtime["locked"] = True
                    event_bus.publish_automation(
                        "INFO",
                        "Dry Run: receiver lock",
                        f"Receiver voor {target['name']} zou nu worden gelockt",
                        data={"pass": target, "dry_run": True},
                    )
                else:
                    autopilot_lock_receiver()
                    autopilot_runtime["locked"] = True

            if (
                -2 <= seconds_until_start <= 1
                and autopilot_runtime["locked"]
                and not autopilot_runtime["record_started"]
            ):
                autopilot_runtime["record_started"] = True
                if dry_run:
                    autopilot_runtime["dry_run_completed"] = True
                    automation_controller.update_status(
                        "DRY RUN COMPLETE",
                        f"Volledige beslisketen voor {target['name']} doorlopen",
                        next_action="Wachten tot passage is beëindigd",
                        target_pass=target,
                    )
                    event_bus.publish_automation(
                        "SUCCESS",
                        "Dry Run voltooid",
                        f"Geen receiver of SatDump gestart voor {target['name']}",
                        data={"pass": target, "dry_run": True},
                    )
                else:
                    autopilot_start_recording()

            if now_epoch > end_epoch and not autopilot_runtime["record_started"]:
                write_log("AUTO: passage gemist zonder opname; ontvangers herstellen")
                restore_service = autopilot_runtime.get("restore_service")
                if (
                    restore_service
                    and autopilot_runtime.get("restore_service_was_active")
                ):
                    run_systemctl("start", restore_service)
                profiles.set_active_profile("adsb")
                mission_engine_core.mission_reset()
                reset_autopilot_runtime()

            if (
                autopilot_runtime.get("dry_run_completed")
                and now_epoch > end_epoch
            ):
                reset_autopilot_runtime()

            if (
                autopilot_runtime["record_started"]
                and not dry_run
                and mission_engine_core.get_mission_status()["active_job"] is None
                and mission_engine_core.get_mission_status()["phase"] == "READY"
            ):
                reset_autopilot_runtime()

        except Exception as error:
            write_log(f"AUTO-controller fout: {error}")
            automation_controller.update_status(
                "ERROR",
                str(error),
                next_action="Controleer Event Timeline en logs",
                target_pass=autopilot_runtime.get("target_pass"),
            )
            time.sleep(2)

        time.sleep(AUTOPILOT_POLL_SECONDS)


def start_mission_autopilot():
    worker = threading.Thread(
        target=mission_autopilot_worker,
        daemon=True,
        name="sdrcc-mission-autopilot",
    )
    worker.start()
    return worker


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(get_dashboard_data())



@app.route("/api/mission-operations")
def api_mission_operations():
    try:
        return jsonify(mission_operations.get_snapshot())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500

@app.route("/api/live-rf")
def api_live_rf():
    try:
        return jsonify(live_rf.get_status())
    except Exception as error:
        return jsonify({
            "active": False,
            "state": "ERROR",
            "error": str(error),
        }), 500

@app.route("/api/events")
def api_events():
    try:
        limit = request.args.get("limit", default=100, type=int)
        level_values = request.args.getlist("level")
        category_values = request.args.getlist("category")
        events = event_bus.get_events(
            limit=limit or 100,
            levels=level_values,
            categories=category_values,
            newest_first=True,
        )
        status = event_bus.get_status()
        return jsonify({
            "ok": True,
            "count": len(events),
            "total": status["count"],
            "limit": status["limit"],
            "events": events,
        })
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
            "count": 0,
            "events": [],
        }), 500


@app.route("/api/mission-scheduler")
def api_mission_scheduler():
    try:
        return jsonify(mission_scheduler_core.get_scheduler_status())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500



@app.route("/api/automation-controller", methods=["GET", "PUT"])
def api_automation_controller():
    try:
        scheduler = mission_scheduler_core.get_scheduler_status()
        next_pass = scheduler.get("next_pass")

        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            action = str(payload.get("action") or "").strip().lower()

            if action == "dry_run":
                automation_controller.set_dry_run(payload.get("enabled", False))
            elif action == "manual_override":
                automation_controller.set_manual_override(payload.get("enabled", False))
            elif action == "skip_next_pass":
                automation_controller.skip_pass(next_pass)
                if (
                    autopilot_runtime.get("target_pass")
                    and not autopilot_runtime.get("record_started")
                ):
                    reset_autopilot_runtime()
            else:
                raise ValueError("Onbekende Automation Controller-actie")

        return jsonify({
            "ok": True,
            **automation_controller.get_status(
                mode=scheduler.get("mode", "MANUAL"),
                next_pass=next_pass,
            ),
        })
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 500


@app.route("/api/mission-queue", methods=["GET", "PUT"])
def api_mission_queue():
    try:
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            mission_queue_core.update_item(
                payload.get("queue_key"),
                action=payload.get("action"),
            )
        limit = request.args.get("limit", default=10, type=int) or 10
        hours = request.args.get("hours", default=48, type=int) or 48
        target = autopilot_runtime.get("target_pass") or {}
        target_key = None
        active_key = None
        if target and target.get("name") and target.get("start_epoch") is not None:
            target_key = f"{target.get('name')}:{int(target.get('start_epoch'))}"
            if autopilot_runtime.get("record_started"):
                active_key = target_key

        controller = automation_controller.get_status(
            mode=mission_scheduler_core.get_scheduler_status().get("mode", "MANUAL"),
            next_pass=mission_scheduler_core.get_scheduler_status().get("next_pass"),
        )
        return jsonify(mission_queue_core.get_payload(
            limit=limit,
            hours_ahead=hours,
            active_pass_key=active_key,
            target_pass_key=target_key,
            controller_status=controller.get("status"),
        ))
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({"ok": False, "error": str(error), "queue": []}), 500


@app.route("/api/mission-history")
def api_mission_history():
    try:
        limit = request.args.get("limit", default=100, type=int)
        result = request.args.get("result", default="", type=str)
        satellite = request.args.get("satellite", default="", type=str)
        query = request.args.get("q", default="", type=str)
        return jsonify(mission_history_core.get_history_payload(
            limit=limit or 100,
            result=result,
            satellite=satellite,
            query=query,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
            "count": 0,
            "missions": [],
            "statistics": {},
        }), 500


@app.route("/api/mission-history/<mission_id>")
def api_mission_history_detail(mission_id):
    try:
        mission = mission_history_core.get_mission(mission_id)
        if mission is None:
            return jsonify({
                "ok": False,
                "error": "Mission niet gevonden",
            }), 404

        mission_id_value = str(mission.get("mission_id") or mission_id)
        events = [
            event for event in event_bus.get_events(limit=100, newest_first=False)
            if _mission_event_matches(event, mission_id_value)
        ]
        inventory = _mission_output_inventory(mission)
        diagnostics = mission_diagnostics.read_mission_diagnostics(
            mission.get("output_path")
        )
        quality = _mission_quality(mission, events, inventory)
        if diagnostics.get("available") and diagnostics.get("quality"):
            quality["score"] = diagnostics["quality"].get("score")
            quality["grade"] = diagnostics["quality"].get("grade")
            quality["components"] = diagnostics["quality"].get("components")
        return jsonify({
            "ok": True,
            "mission": mission,
            "quality": quality,
            "diagnostics": diagnostics,
            "files": inventory,
            "events": events,
        })
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500


@app.route("/mission-preview/<mission_id>/<path:relative_path>")
def mission_preview_file(mission_id, relative_path):
    mission = mission_history_core.get_mission(mission_id)
    if mission is None:
        abort(404)

    output_value = str(mission.get("output_path") or "").strip()
    if not output_value:
        abort(404)

    root = Path(output_value).expanduser().resolve()
    requested = (root / relative_path).resolve()
    try:
        requested.relative_to(root)
    except ValueError:
        abort(403)

    if requested.suffix.lower() not in MISSION_IMAGE_EXTENSIONS:
        abort(403)
    if not requested.exists() or not requested.is_file():
        abort(404)
    return send_file(requested)


@app.route("/api/mission-engine")
def api_mission_engine():
    try:
        return jsonify(mission_engine_core.get_mission_status())
    except Exception as error:
        return jsonify({
            "phase": "IDLE",
            "detail": f"Mission Engine fout: {error}",
            "progress": 0,
            "steps": [],
            "error": str(error),
        })



@app.route("/api/mission-engine/next", methods=["POST"])
def api_mission_engine_next():
    try:
        return jsonify(mission_engine_core.mission_next_state())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500


@app.route("/api/mission-engine/reset", methods=["POST"])
def api_mission_engine_reset():
    try:
        return jsonify(mission_engine_core.mission_reset())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500



@app.route("/api/mission-engine/finish-recording", methods=["POST"])
def api_mission_engine_finish_recording():
    try:
        mission_engine_core.mission_set_state("DECODING")
        mission_engine_core.mission_set_state("PROCESSING")
        mission_engine_core.mission_set_state("ARCHIVING")
        mission_engine_core.mission_set_state("READY")
        write_log("Mission Engine: opname-afhandeling afgerond")
        return jsonify(mission_engine_core.get_mission_status())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500



@app.route("/api/receiver-manager", methods=["GET"])
def api_receiver_manager():
    return jsonify(receiver_manager.get_status())


@app.route("/api/receiver-assignment", methods=["POST"])
def api_receiver_assignment():
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("weather")
    mission = mission_engine_core.get_mission_status()
    receiver_runtime = receiver_manager.get_status()
    if (
        mission.get("phase") not in {"READY", "WAIT FOR PASS"}
        or autopilot_runtime.get("prepared")
        or autopilot_runtime.get("locked")
        or autopilot_runtime.get("record_started")
        or receiver_runtime.get("reservation") is not None
    ):
        return jsonify({
            "ok": False,
            "message": "Receiverkeuze kan niet tijdens een actieve missie.",
        }), 409
    try:
        device = device_manager.get_device(device_id)
        if device is None:
            raise ValueError("Onbekende SDR-keuze")
        assignments = config_core.set_weather_receiver(device_id)
        write_log(
            f"Weather-ontvanger gewijzigd naar {device['number']} "
            f"({device['serial']})"
        )
        event_bus.publish_receiver(
            "INFO",
            "Weather-ontvanger gewijzigd",
            f"Weather gebruikt nu {device['number']} ({device['serial']})",
            data={
                "role": "weather",
                "device_id": device["id"],
                "number": device["number"],
                "serial": device["serial"],
                "assignments": assignments,
            },
        )
        return jsonify({
            "ok": True,
            "message": f"Weather gebruikt nu {device['number']}.",
            "assignments": assignments,
            "device": device,
        })
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)}), 400



@app.route("/api/weather-rf", methods=["GET", "POST"])
def api_weather_rf():
    if request.method == "GET":
        return jsonify({"ok": True, "settings": config_core.get_weather_rf_config()})
    payload = request.get_json(silent=True) or {}
    mission = get_mission_data_for_status()
    scheduler = mission_scheduler_core.get_scheduler_status()
    mission_phase = str(mission.get("state") or mission.get("phase") or "").upper()
    observer_phase = str((scheduler.get("observer") or {}).get("phase") or "").upper()
    blocked = mission_phase not in {"", "READY", "WAIT FOR PASS"} or observer_phase in {
        "PREPARE RECEIVER", "FINAL APPROACH", "PASS ACTIVE"
    }
    if blocked:
        return jsonify({"ok": False, "message": "RF-instellingen zijn geblokkeerd tijdens een missie."}), 409
    try:
        settings = config_core.set_weather_rf_config(payload)
        write_log(f"Weather RF-instellingen gewijzigd: mode={settings['gain_mode']} gain={settings['gain_db']} dB")
        return jsonify({"ok": True, "settings": settings, "message": "RF-instellingen opgeslagen."})
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400


@app.route("/api/weather-spectrum", methods=["POST"])
def api_weather_spectrum():
    payload = request.get_json(silent=True) or {}
    try:
        center_hz = int(payload.get("frequency_hz") or 137100000)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Ongeldige frequentie."}), 400
    if not 24000000 <= center_hz <= 1766000000:
        return jsonify({"ok": False, "message": "Frequentie valt buiten het RTL-SDR-bereik."}), 400
    mission = get_mission_data_for_status()
    scheduler = mission_scheduler_core.get_scheduler_status()
    mission_phase = str(mission.get("state") or mission.get("phase") or "").upper()
    observer_phase = str((scheduler.get("observer") or {}).get("phase") or "").upper()
    busy = mission_phase not in {"", "READY", "WAIT FOR PASS"} or observer_phase in {
        "PREPARE RECEIVER", "FINAL APPROACH", "PASS ACTIVE"
    }
    try:
        result = rf_diagnostics.scan_spectrum(center_hz, mission_busy=busy)
        write_log(f"Spectrumscan uitgevoerd op {center_hz / 1e6:.3f} MHz met {result['device']['number']}")
        return jsonify({"ok": True, "spectrum": result})
    except RuntimeError as error:
        write_log(f"Spectrumscan mislukt: {error}")
        return jsonify({"ok": False, "message": str(error)}), 409

@app.route("/api/capture-status")
def api_capture_status():
    latest_capture = find_latest_capture()

    if latest_capture is None:
        return jsonify({
            "available": False,
            "latest_capture": None,
        })

    return jsonify({
        "available": True,
        "latest_capture": latest_capture,
        "server_time_epoch": int(datetime.now().timestamp()),
    })


@app.route("/api/action", methods=["POST"])
def api_action():
    payload = request.get_json(silent=True) or {}
    action_id = payload.get("action")

    if action_id not in ACTIONS:
        write_log(f"Onbekende dashboardactie geweigerd: {action_id}")
        return jsonify({"ok": False, "message": f"Onbekende actie: {action_id}"}), 400

    action = ACTIONS[action_id]

    try:
        if action_id in SERVICE_ACTIONS:
            return handle_service_action(action_id, action)

        if action_id in SCHEDULER_ACTIONS:
            return handle_scheduler_action(action)

        if action_id in PROFILE_ACTIONS:
            return handle_profile_action(action)

        if action_id == "record":
            record_data = satdump_core.build_record_command()

            if record_data is None:
                write_log("Record NOW geweigerd: geen geschikte passage gevonden")
                return jsonify({
                    "ok": False,
                    "message": "Geen geschikte satellietpassage gevonden.",
                }), 400

            if not record_data["allowed"]:
                reason = record_data["reason"]
                write_log(f"Record NOW geweigerd: {reason}")
                return jsonify({
                    "ok": False,
                    "message": reason,
                }), 400

            pass_data = record_data["pass"]

            mission_engine_core.mission_create_job(
                satellite=pass_data["name"],
                frequency=pass_data["frequency"],
                mode=pass_data["mode"],
                pipeline=pass_data["pipeline"],
                output_path=str(record_data["output_path"]),
                receiver=record_data["device"]["number"],
                receiver_id=record_data["device"]["id"],
                receiver_serial=record_data["device"]["serial"],
            )

            mission_engine_core.mission_set_state("LOCK RECEIVER")
            mission_engine_core.mission_set_state("RECORDING")
            write_log(
                "Mission Engine: ontvangers voorbereiden voor SatDump"
            )

            write_log(
                "Mission Engine: Record NOW gestart voor "
                f"{pass_data['name']} naar {record_data['output_path']}"
            )

        return handle_sdrcc_action(action_id, action)

    except subprocess.TimeoutExpired:
        write_log(f"Dashboard actie timeout: {action['label']}")
        return jsonify({"ok": False, "message": f"{action['label']} duurde te lang."}), 500

    except Exception as error:
        write_log(f"Dashboard actie mislukt: {action['label']} - {error}")
        return jsonify({"ok": False, "message": str(error)}), 500


@app.route("/capture/<path:relative_path>")
def capture_file(relative_path):
    requested = (PROJECT_ROOT / relative_path).resolve()

    allowed_roots = [
        (PROJECT_ROOT / "data" / "images").resolve(),
        (PROJECT_ROOT / "captures").resolve(),
    ]

    if not any(str(requested).startswith(str(root)) for root in allowed_roots):
        abort(403)

    if not requested.exists() or not requested.is_file():
        abort(404)

    return send_file(requested)


def run():
    event_bus.publish_system(
        "SYSTEM",
        "Event Bus gestart",
        "SDRCC operator-eventopslag en API zijn actief.",
    )
    start_mission_autopilot()
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    run()
