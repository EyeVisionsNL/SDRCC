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

from core import device_manager
from core import passes
from core import state
from core import tle
from core import system_stats
from core import mission_engine as mission_engine_core
from core import mission_preflight
from core import mission_scheduler as mission_scheduler_core
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

    return {
        "server_time_epoch": int(datetime.now().timestamp()),
        "sdr2": sdr2,
        "next_pass": next_pass,
        "ais": ais,
        "adsb": adsb,
        "devices": devices,
        "tle_present": tle.exists(),
        "system": system_stats.get_stats(),
        "logs": logs,
        "latest_capture": latest_capture,
        "recent_captures": captures,
        "mission": mission,
        "scheduler": mission_scheduler_core.get_scheduler_status(),
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
        ais_result = run_systemctl("stop", "ais-catcher.service")

        if ais_result.returncode != 0:
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher kon niet worden gestopt.",
                "error": ais_result.stderr,
            }), 500

        if not wait_for_service("ais-catcher.service", "inactive"):
            return jsonify({
                "ok": False,
                "message": "AIS-Catcher stopte niet volledig.",
            }), 500

        if not wait_for_service("readsb.service", "active"):
            return jsonify({
                "ok": False,
                "message": "ADS-B draait niet meer op SDR2.",
            }), 500

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
    })


def autopilot_prepare_receiver():
    write_log("AUTO: T-90 ontvanger voorbereiden")

    ais_result = run_systemctl("stop", "ais-catcher.service")

    if ais_result.returncode != 0:
        raise RuntimeError(
            "AIS-Catcher kon niet worden gestopt: "
            + ais_result.stderr.strip()
        )

    if not wait_for_service("ais-catcher.service", "inactive"):
        raise RuntimeError("AIS-Catcher stopte niet volledig")

    if not wait_for_service("readsb.service", "active"):
        raise RuntimeError("ADS-B draait niet meer op SDR2")

    profiles.set_active_profile("weather")

    write_log(
        "AUTO: Weather actief op SDR1; ADS-B blijft actief op SDR2"
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
        )

    mission_engine_core.mission_set_state("LOCK RECEIVER")
    autopilot_runtime["record_data"] = record_data

    write_log(
        "AUTO: T-30 receiver gelocked voor "
        f"{pass_data['name']} / {record_data['device']['serial']}"
    )


def monitor_auto_record_process(process):
    try:
        stdout, stderr = process.communicate()

        if stdout:
            for line in stdout.strip().splitlines():
                write_log(line)

        if stderr:
            for line in stderr.strip().splitlines():
                write_log("ERROR: " + line)

        if process.returncode == 0:
            write_log("AUTO: SatDump-opname succesvol afgerond")

            mission_engine_core.mission_set_state("DECODING")
            time.sleep(1)

            mission_engine_core.mission_set_state("PROCESSING")
            time.sleep(1)

            mission_engine_core.mission_set_state("ARCHIVING")
            time.sleep(1)

            mission_engine_core.mission_finish_job(success=True)

        else:
            error_message = (
                f"SatDump gestopt met foutcode {process.returncode}"
            )
            write_log(f"AUTO: {error_message}")

            mission_engine_core.mission_finish_job(
                success=False,
                error=error_message,
            )

    except Exception as error:
        write_log(f"AUTO: procesbewaking mislukt: {error}")

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
        write_log("AUTO: AIS-Catcher herstellen")

        ais_result = run_systemctl(
            "start",
            "ais-catcher.service",
        )

        if ais_result.returncode != 0:
            write_log(
                "AUTO ERROR: AIS-Catcher kon niet worden gestart: "
                + ais_result.stderr.strip()
            )
        elif not wait_for_service(
            "ais-catcher.service",
            "active",
        ):
            write_log(
                "AUTO ERROR: AIS-Catcher werd niet actief"
            )
        else:
            write_log("AUTO: AIS-Catcher is weer actief")

        profiles.set_active_profile("adsb")
        mission_engine_core.mission_set_state("READY")

        write_log(
            "AUTO: missie afgerond; profiel terug naar ADS-B"
        )


def autopilot_start_recording():
    record_data = autopilot_runtime.get("record_data")

    if record_data is None:
        raise RuntimeError(
            "Geen voorbereid SatDump-commando beschikbaar"
        )

    mission_engine_core.mission_set_state("RECORDING")

    process = subprocess.Popen(
        record_data["command"],
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

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


def mission_autopilot_worker():
    write_log("AUTO-controller gestart")

    while True:
        try:
            scheduler = (
                mission_scheduler_core.get_scheduler_status()
            )

            if scheduler.get("mode") != "AUTO":
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            next_pass = scheduler.get("next_pass")

            if (
                autopilot_runtime["target_pass"] is None
                and next_pass is not None
            ):
                reset_autopilot_runtime(next_pass)

                write_log(
                    "AUTO: passage geselecteerd: "
                    f"{next_pass['name']} om {next_pass['start']}"
                )

            target = autopilot_runtime["target_pass"]

            if target is None:
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            now_epoch = int(time.time())
            start_epoch = int(target["start_epoch"])
            end_epoch = int(target["end_epoch"])
            seconds_until_start = start_epoch - now_epoch

            config = scheduler["observer"]["config"]
            preflight_seconds = int(
                config["preflight_seconds"]
            )
            prepare_seconds = int(
                config["prepare_seconds"]
            )
            lock_seconds = int(config["lock_seconds"])

            if (
                0 < seconds_until_start <= preflight_seconds
                and not autopilot_runtime["preflight_ok"]
                and time.monotonic()
                - autopilot_runtime["last_preflight_attempt"]
                >= 10
            ):
                autopilot_runtime[
                    "last_preflight_attempt"
                ] = time.monotonic()

                result = mission_preflight.run_preflight()

                if result["passed"]:
                    autopilot_runtime["preflight_ok"] = True
                    write_log(
                        "AUTO: preflight OK voor "
                        f"{target['name']}"
                    )
                else:
                    write_log(
                        "AUTO: preflight FAILED: "
                        f"{result['detail']}"
                    )

            if (
                0 < seconds_until_start <= prepare_seconds
                and autopilot_runtime["preflight_ok"]
                and not autopilot_runtime["prepared"]
            ):
                autopilot_prepare_receiver()
                autopilot_runtime["prepared"] = True

            if (
                0 < seconds_until_start <= lock_seconds
                and autopilot_runtime["prepared"]
                and not autopilot_runtime["locked"]
            ):
                autopilot_lock_receiver()
                autopilot_runtime["locked"] = True

            # Start tussen T-1 en T+2 seconden.
            if (
                -2 <= seconds_until_start <= 1
                and autopilot_runtime["locked"]
                and not autopilot_runtime["record_started"]
            ):
                autopilot_runtime["record_started"] = True
                autopilot_start_recording()

            # Passage gemist of afgebroken voordat opname begon.
            if (
                now_epoch > end_epoch
                and not autopilot_runtime["record_started"]
            ):
                write_log(
                    "AUTO: passage gemist zonder opname; "
                    "ontvangers herstellen"
                )

                run_systemctl(
                    "start",
                    "ais-catcher.service",
                )
                profiles.set_active_profile("adsb")
                mission_engine_core.mission_reset()
                reset_autopilot_runtime()

            # Na een voltooide opname de volgende passage kiezen.
            if (
                autopilot_runtime["record_started"]
                and mission_engine_core.get_mission_status()[
                    "active_job"
                ] is None
                and mission_engine_core.get_mission_status()[
                    "phase"
                ] == "READY"
            ):
                reset_autopilot_runtime()

        except Exception as error:
            write_log(f"AUTO-controller fout: {error}")
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
    start_mission_autopilot()
    app.run(
        host="0.0.0.0",
        port=8080,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    run()
