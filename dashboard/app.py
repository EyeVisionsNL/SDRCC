#!/usr/bin/env python3

import sys
import subprocess
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

app = Flask(__name__)

LOG_FILE = PROJECT_ROOT / "logs" / "sdrcc.log"
SDRCC_SCRIPT = PROJECT_ROOT / "scripts" / "sdrcc.py"

IMAGE_DIRS = [
    PROJECT_ROOT / "data" / "images",
    PROJECT_ROOT / "captures",
]

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

SERVICE_ACTIONS = {
    "start_ais": {"label": "AIS starten", "service": "ais-catcher.service", "systemctl": "start"},
    "stop_ais": {"label": "AIS stoppen", "service": "ais-catcher.service", "systemctl": "stop"},
    "restart_ais": {"label": "AIS herstarten", "service": "ais-catcher.service", "systemctl": "restart"},
    "start_adsb": {"label": "ADS-B starten", "service": "readsb.service", "systemctl": "start"},
    "stop_adsb": {"label": "ADS-B stoppen", "service": "readsb.service", "systemctl": "stop"},
    "restart_adsb": {"label": "ADS-B herstarten", "service": "readsb.service", "systemctl": "restart"},
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


def find_latest_capture():
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
    candidates = []

    for image_dir in IMAGE_DIRS:
        if not image_dir.exists():
            continue

        for path in image_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in allowed_extensions:
                candidates.append(path)

    if not candidates:
        return None

    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    stat = latest.stat()
    relative = latest.relative_to(PROJECT_ROOT)

    age_seconds = int(datetime.now().timestamp() - stat.st_mtime)

    return {
        "filename": latest.name,
        "relative_path": str(relative),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_kb": round(stat.st_size / 1024, 1),
        "age_seconds": age_seconds,
        "live": age_seconds <= 60,
        "url": "/capture/" + str(relative).replace("\\", "/"),
    }


def mission_engine(next_pass, latest_capture, logs):
    phase = "IDLE"
    detail = "Geen actieve opname."
    progress = 0

    log_text = "\n".join(logs[-40:]).lower()

    if next_pass:
        now = int(datetime.now().timestamp())
        remaining = next_pass["start_epoch"] - now

        if remaining < 0:
            phase = "LOCK RECEIVER"
            detail = "Passage is actief of net gestart."
            progress = 30
        elif remaining < 900:
            phase = "WAIT FOR PASS"
            detail = f"Volgende passage binnen {round(remaining / 60)} minuten."
            progress = 15
        else:
            phase = "IDLE"
            detail = "Wachten op volgende passage."
            progress = 5

    if "record now" in log_text or "recording" in log_text:
        phase = "RECORDING"
        detail = "Opname actief of recent gestart."
        progress = 45

    if "satdump" in log_text:
        phase = "DECODING"
        detail = "SatDump activiteit gevonden in log."
        progress = 65

    if latest_capture:
        if latest_capture.get("live"):
            phase = "RECORDING"
            detail = f"Live preview actief: {latest_capture['filename']}"
            progress = 50
        else:
            phase = "READY"
            detail = f"Laatste beeld: {latest_capture['filename']}"
            progress = 100

    active_index = MISSION_STEPS.index(phase) if phase in MISSION_STEPS else 0

    return {
        "phase": phase,
        "detail": detail,
        "progress": progress,
        "steps": MISSION_STEPS,
        "active_index": active_index,
    }


def get_dashboard_data():
    sdr2 = state.get_sdr2_state()
    raw_next_pass = passes.get_next_pass()
    next_pass = serialize_pass(raw_next_pass)
    devices = device_manager.get_devices()

    ais = service_state("ais-catcher.service")
    adsb = service_state("readsb.service")
    logs = read_log_lines()
    latest_capture = find_latest_capture()

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
        "mission": mission_engine(next_pass, latest_capture, logs),
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


def handle_sdrcc_action(action_id, action):
    label = action["label"]
    command = action["command"]
    mode = action["mode"]

    write_log(f"Dashboard actie gestart: {label}")

    if mode == "start":
        subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        write_log(f"Dashboard actie loopt op achtergrond: {label}")

        return jsonify({
            "ok": True,
            "message": f"{label} gestart.",
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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    return jsonify(get_dashboard_data())


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
    app.run(host="0.0.0.0", port=8080, debug=False)


if __name__ == "__main__":
    run()
