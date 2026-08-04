#!/usr/bin/env python3

import sys
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, Response, jsonify, render_template, request, send_file, abort, stream_with_context

from core import device_manager
from core import weather_planning as weather_planning_core
from core import downloader as tle_downloader
from core import event_bus
from core import live_rf
from core import config as config_core
from core import controlled_iq_capture
from core import iss_voice
from core import iss_voice_audio
from core import iss_voice_audio_monitor
from core import iss_voice_executor
from core import iss_voice_runtime
from core import iss_voice_runtime_recovery
from core import mission_recordings as mission_recordings_core
from core import passes
from core import plugin_registry
from core import plugin_runtime as plugin_runtime_core
from core import plugin_execution_runtime as plugin_execution_runtime_core
from core import plugin_health as plugin_health_core
from core import plugin_manager as plugin_manager_core
from core import plugin_capabilities as plugin_capabilities_core
from core import execution_plan_consumer as execution_plan_consumer_core
from core import execution_journal as execution_journal_core
from core import receiver_manager
from core import receiver_authority
from core import receiver_registry
from core import receiver_runtime as receiver_runtime_core
from core import receiver_inventory as receiver_inventory_core
from core import receiver_contexts as receiver_contexts_core
from core import receiver_monitor
from core import state
from core import tle
from core import system_stats
from core import mission_engine as mission_engine_core
from core import mission_history as mission_history_core
from core import mission_diagnostics
from core import mission_operations
from core import mission_preflight
from core import mission_simulator
from core import mission_scheduler as mission_scheduler_core
from core import mission_queue as mission_queue_core
from core import process_manager
from core import profiles
from core import satdump as satdump_core

app = Flask(__name__)

LOG_FILE = PROJECT_ROOT / "logs" / "sdrcc.log"
SDRCC_SCRIPT = PROJECT_ROOT / "scripts" / "sdrcc.py"
RECEIVER_ROLE_HELPER = Path("/usr/local/sbin/sdrcc-apply-receiver-roles")

IMAGE_DIRS = [
    PROJECT_ROOT / "data" / "images",
    PROJECT_ROOT / "captures",
]

SERVICE_ACTIONS = {
    "start_ais": {
        "label": "AIS starten",
        "plugin_id": "ais",
        "systemctl": "start",
    },
    "stop_ais": {
        "label": "AIS stoppen",
        "plugin_id": "ais",
        "systemctl": "stop",
    },
    "restart_ais": {
        "label": "AIS herstarten",
        "plugin_id": "ais",
        "systemctl": "restart",
    },
    "start_adsb": {
        "label": "ADS-B starten",
        "plugin_id": "adsb",
        "systemctl": "start",
    },
    "stop_adsb": {
        "label": "ADS-B stoppen",
        "plugin_id": "adsb",
        "systemctl": "stop",
    },
    "restart_adsb": {
        "label": "ADS-B herstarten",
        "plugin_id": "adsb",
        "systemctl": "restart",
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


SDRCC_ACTIONS = {
    "next_pass": {"label": "Volgende passage", "command": [sys.executable, str(SDRCC_SCRIPT), "next"], "mode": "run"},
    "schedule": {"label": "Planning tonen", "command": [sys.executable, str(SDRCC_SCRIPT), "schedule"], "mode": "run"},
    "simulate_record": {"label": "Simuleer opname", "command": [sys.executable, str(SDRCC_SCRIPT), "simulate-record"], "mode": "run"},
    "record": {"label": "Record NOW", "command": [sys.executable, str(SDRCC_SCRIPT), "record"], "mode": "start"},
}

ACTIONS = {}
ACTIONS.update(SERVICE_ACTIONS)
ACTIONS.update(SCHEDULER_ACTIONS)
ACTIONS.update(SDRCC_ACTIONS)


def write_log(message):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message}\n")


def start_virtual_mission():
    """Compatibility wrapper for the existing dashboard action."""
    return mission_simulator.start(
        scenario="success",
        receiver_id="sdr2",
        duration_seconds=15,
    )["mission"]


def stop_virtual_mission():
    """Compatibility wrapper used by STOP MISSION."""
    status = mission_simulator.stop()
    return bool(status.get("ok"))

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


def apply_receiver_service_configuration(ais_serial, adsb_serial):
    """Use the existing privileged adapter and return its structured result."""
    import json

    result = run_command([
        "sudo",
        "-n",
        str(RECEIVER_ROLE_HELPER),
        str(ais_serial),
        str(adsb_serial),
    ], timeout=180)
    raw = (result.stdout or "").strip()
    try:
        payload = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        payload = {}
    if result.returncode != 0 or not payload.get("ok"):
        payload.update({
            "ok": False,
            "message": payload.get("message")
            or (result.stderr or raw or "Serviceconfiguratie synchroniseren mislukt").strip(),
            "returncode": result.returncode,
        })
    return payload


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


def capture_to_dict(path, mission=None, root=None):
    stat = path.stat()
    age_seconds = int(datetime.now().timestamp() - stat.st_mtime)
    width, height = detect_image_size(path)
    satellite, pipeline, product = classify_capture(path)

    mission = mission if isinstance(mission, dict) else None
    if mission:
        satellite = str(mission.get("satellite") or satellite)
        pipeline = str(mission.get("pipeline") or pipeline)

    if mission and root is not None:
        relative = path.relative_to(root)
        relative_value = str(relative).replace("\\", "/")
        url = f"/mission-preview/{mission.get('mission_id')}/{relative_value}"
        source = "mission"
        mission_id = mission.get("mission_id")
    else:
        relative = path.relative_to(PROJECT_ROOT)
        relative_value = str(relative).replace("\\", "/")
        url = "/capture/" + relative_value
        source = "legacy"
        mission_id = None

    return {
        "filename": path.name,
        "relative_path": relative_value,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "size_kb": round(stat.st_size / 1024, 1),
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "age_seconds": age_seconds,
        "live": age_seconds <= 60,
        "url": url,
        "width": width,
        "height": height,
        "resolution": f"{width}x{height}" if width and height else "-",
        "satellite": satellite,
        "pipeline": pipeline,
        "product": product,
        "source": source,
        "mission_id": mission_id,
    }


def _capture_image_score(path):
    """Prefer useful processed composites over raw channels and map products."""
    name = path.name.lower()
    score = 0
    preferred_tokens = ("rgb", "composite", "msa", "avhrr", "221", "false_color", "false-colour")
    raw_tokens = ("msu-mr-1", "msu-mr-2", "msu-mr-3", "channel", "map", "projection")

    for token in preferred_tokens:
        if token in name:
            score += 20
    for token in raw_tokens:
        if token in name:
            score -= 8

    try:
        stat = path.stat()
        score += min(int(stat.st_size / (256 * 1024)), 20)
        modified = stat.st_mtime
    except OSError:
        modified = 0

    return score, modified, name


def _mission_capture_files(mission):
    output_value = str(mission.get("output_path") or "").strip()
    if not output_value:
        return None, []

    try:
        root = Path(output_value).expanduser().resolve()
    except OSError:
        return None, []
    if not root.exists() or not root.is_dir():
        return None, []

    try:
        files = [
            path for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in MISSION_IMAGE_EXTENSIONS
        ]
    except OSError:
        files = []

    return root, sorted(files, key=_capture_image_score, reverse=True)


def _latest_successful_image_mission():
    try:
        payload = mission_history_core.get_history_payload(limit=100)
    except Exception:
        return None, None, []

    missions = payload.get("missions", []) if isinstance(payload, dict) else []
    for mission in missions:
        result = str(mission.get("result") or mission.get("status") or "").upper()
        is_success = bool(mission.get("success")) or result == "SUCCESS"
        if not is_success:
            continue

        root, files = _mission_capture_files(mission)
        if files:
            return mission, root, files

    return None, None, []


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
    mission, root, files = _latest_successful_image_mission()
    if files:
        return capture_to_dict(files[0], mission=mission, root=root)

    files = find_capture_files()
    if not files:
        return None
    return capture_to_dict(files[0])


def recent_captures(limit=10):
    mission, root, files = _latest_successful_image_mission()
    if files:
        return [capture_to_dict(path, mission=mission, root=root) for path in files[:limit]]

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
    result = str(mission.get("result") or mission.get("status") or "UNKNOWN").upper()
    mission_type = str(mission.get("mission_type") or "").strip().lower()
    plugin_id = str(mission.get("plugin_id") or "").strip().lower()
    pipeline = str(mission.get("pipeline") or "").strip().lower()
    is_iss_voice = (
        mission_type == "iss_voice"
        or plugin_id == "iss_voice"
        or pipeline == "wideband_iq_offline_fm"
    )
    event_text = " ".join(
        f"{event.get('category', '')} {event.get('title', '')} {event.get('detail', '')}"
        for event in events
    ).upper()
    images = max(int(mission.get("image_count") or 0), inventory["images"]["count"])
    recording = (
        bool(mission.get("started_at"))
        or "RECORDING" in event_text
        or inventory["recording"]["available"]
    )

    if is_iss_voice:
        return {
            "result": result,
            "mission_type": "iss_voice",
            "receiver_lock": bool(
                mission.get("receiver")
                or mission.get("receiver_id")
                or mission.get("receiver_serial")
            ),
            "recording": recording,
            "decoder": None,
            "decoder_applicable": False,
            "images": None,
            "images_applicable": False,
            "peak_snr_db": None,
            "snr_applicable": False,
            "audio_content_assessment": str(
                mission.get("audio_content_assessment") or "UNASSESSED"
            ).upper(),
        }

    return {
        "result": result,
        "mission_type": mission_type or "weather",
        "receiver_lock": bool(mission.get("receiver")) and (
            "LOCK RECEIVER" in event_text or "RECEIVER GELOCKED" in event_text or "RECEIVER LOCK" in event_text
        ),
        "recording": recording,
        "decoder": images > 0,
        "decoder_applicable": True,
        "images": images,
        "images_applicable": True,
        "peak_snr_db": mission.get("peak_snr_db"),
        "snr_applicable": True,
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
    live_rf_status = live_rf.get_status()

    mission_phase = str(mission.get("state") or mission.get("phase") or "").upper()
    observer_phase = str((scheduler.get("observer") or {}).get("phase") or "").upper()
    weather_active = mission_phase in {"LOCK RECEIVER", "RECORDING"} or observer_phase in {
        "PREPARE RECEIVER",
        "FINAL APPROACH",
        "PASS ACTIVE",
    }
    iss_runtime = iss_voice_runtime.get_status()
    iss_active = bool(iss_runtime.get("active"))
    authority_snapshot = receiver_authority.get_snapshot(
        mission_status=mission,
        weather_runtime=live_rf_status,
        iss_runtime=iss_runtime,
        use_cache=False,
    )
    authority_roles = authority_snapshot.get("roles") or {}
    weather_runtime = authority_roles.get("weather") or {}
    ais_runtime = authority_roles.get("ais") or {}
    adsb_runtime = authority_roles.get("adsb") or {}
    iss_verified_runtime = authority_roles.get("iss_voice") or {}

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

        if (
            iss_verified_runtime.get("runtime_active")
            and iss_verified_runtime.get("verified_runtime_receiver")
            and device_id == iss_verified_runtime.get("verified_runtime_receiver")
        ):
            current_task = "ISS Voice"
            active_detail = str(iss_runtime.get("phase") or "Actieve ISS-missie")
            status_label = (
                "DRIFT" if iss_verified_runtime.get("configuration_drift") else "LOCKED"
            )
        elif (
            weather_runtime.get("runtime_active")
            and weather_runtime.get("verified_runtime_receiver")
            and device_id == weather_runtime.get("verified_runtime_receiver")
        ):
            current_task = "Weather / METEOR"
            active_detail = "Actieve satellietmissie"
            status_label = "DRIFT" if weather_runtime.get("configuration_drift") else "LOCKED"
        elif (
            ais_runtime.get("service_active")
            and ais_runtime.get("verified_runtime_receiver") == device_id
        ):
            current_task = "AIS"
            active_detail = "ais-catcher.service · verified runtime"
            status_label = "DRIFT" if ais_runtime.get("configuration_drift") else "IN USE"
        elif (
            adsb_runtime.get("service_active")
            and adsb_runtime.get("verified_runtime_receiver") == device_id
        ):
            current_task = "ADS-B"
            active_detail = "readsb.service · verified runtime"
            status_label = "DRIFT" if adsb_runtime.get("configuration_drift") else "IN USE"

        configured_unverified = [
            item for item in (
                weather_runtime,
                ais_runtime,
                adsb_runtime,
                iss_verified_runtime,
            )
            if item.get("runtime_active")
            and item.get("configured_receiver") == device_id
            and not item.get("verified_runtime_receiver")
        ]
        configured_drift = [
            item for item in (
                weather_runtime,
                ais_runtime,
                adsb_runtime,
                iss_verified_runtime,
            )
            if item.get("configuration_drift")
            and item.get("configured_receiver") == device_id
        ]
        if current_task == "Vrij" and configured_unverified:
            current_task = "Runtime unverified"
            active_detail = ", ".join(
                str(item.get("role") or "service").upper()
                for item in configured_unverified
            )
            status_label = "UNVERIFIED"
        elif current_task == "Vrij" and configured_drift:
            active_detail = "Configured receiver differs from verified runtime"
            status_label = "DRIFT"

        next_task = (
            "ISS Voice" if assignments.get("iss_voice") == device_id and not iss_active
            else "Weather / METEOR" if assignments.get("weather") == device_id and not weather_active
            else "-"
        )

        device["default_task"] = default_task
        device["current_task"] = current_task
        device["next_task"] = next_task
        device["active_detail"] = active_detail
        device["status_label"] = status_label
        device["in_use"] = status_label in {"IN USE", "LOCKED", "DRIFT", "UNVERIFIED"}

    return {
        "server_time_epoch": int(datetime.now().timestamp()),
        "sdr2": sdr2,
        "next_pass": next_pass,
        "ais": ais,
        "adsb": adsb,
        "devices": devices,
        "assignments": assignments,
        "receiver_authority": authority_snapshot,
        "weather_rf": config_core.get_weather_rf_config(),
        "tle_present": tle.exists(),
        "system": system_stats.get_stats(),
        "logs": logs,
        "latest_capture": latest_capture,
        "recent_captures": captures,
        "mission": mission,
        "iss_voice": iss_runtime,
        "scheduler": scheduler,
        "actions": [{"id": action_id, "label": data["label"]} for action_id, data in ACTIONS.items()],
    }


def handle_service_action(action_id, action):
    plugin_id = str(action["plugin_id"]).strip().lower()
    systemctl_action = str(action["systemctl"]).strip().lower()
    label = action["label"]

    block = receiver_manager.service_action_block(plugin_id, systemctl_action)
    if block is not None:
        message = block.get("message") or (
            f"{label} geweigerd: receiver is niet beschikbaar."
        )
        write_log(f"{label}: geblokkeerd door Receiver Manager - {message}")
        return jsonify({
            "ok": False,
            "message": message,
            "receiver_handover_block": block,
            "authority": "receiver_manager",
        }), 409

    delegation = execution_plan_consumer_core.delegate_service_action(
        plugin_id,
        systemctl_action,
    )
    service = delegation.get("delegated_target")

    write_log(
        f"{label}: Execution Plan-delegatie "
        f"({plugin_id}, valid={delegation['ok']}, "
        f"target={service!r}, action={systemctl_action})"
    )

    if not delegation["ok"] or not service:
        errors = delegation.get("errors") or [
            "Execution Plan leverde geen geldig servicetarget."
        ]
        message = "; ".join(str(error) for error in errors)
        write_log(f"{label}: delegatie geweigerd - {message}")
        return jsonify({
            "ok": False,
            "message": f"{label} geweigerd: {message}",
            "execution_plan_delegation": delegation,
        }), 409

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
            "execution_plan_delegation": delegation,
            "execution_plan_consumption": delegation,
        })

    write_log(f"{label}: mislukt met returncode {result.returncode}")
    return jsonify({
        "ok": False,
        "message": f"{label} mislukt. Status: {after['state']}",
        "before": before,
        "after": after,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "execution_plan_delegation": delegation,
        "execution_plan_consumption": delegation,
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
    "process": None,
    "stop_requested": False,
    "iss_execution_active": False,
    "iss_execution_result": None,
}


def reset_autopilot_runtime(target_pass=None):
    autopilot_runtime.update({
        "pass_key": mission_queue_core.get_pass_key(target_pass),
        "target_pass": target_pass,
        "preflight_ok": False,
        "last_preflight_attempt": 0.0,
        "prepared": False,
        "locked": False,
        "record_started": False,
        "record_data": None,
        "process": None,
        "stop_requested": False,
        "iss_execution_active": False,
        "iss_execution_result": None,
    })


def restore_autopilot_receiver(detail):
    """Restore or release the current autopilot reservation exactly once."""
    mission_key = autopilot_runtime.get("pass_key")
    if not mission_key:
        return {"ok": True, "released": False, "reason": "no mission key"}
    status = receiver_manager.get_status()
    reservation = next((
        item for item in status.get("canonical_reservations", {}).values()
        if isinstance(item, dict) and item.get("mission_key") == mission_key
    ), None)
    if reservation is None:
        return {"ok": True, "released": False, "reason": "no reservation"}
    if isinstance(reservation.get("handover"), dict):
        return receiver_manager.restore_handover(
            mission_key=mission_key,
            service_state=service_state,
            service_action=run_systemctl,
            wait_for_service=wait_for_service,
            detail=str(detail),
        )
    receiver_manager.release(mission_key=mission_key, detail=str(detail))
    return {"ok": True, "released": True, "errors": []}


def autopilot_prepare_receiver():
    write_log("AUTO: T-90 ontvanger voorbereiden")
    device = device_manager.get_assigned_device("weather")
    if device is None:
        raise RuntimeError("Geen Weather-ontvanger toegewezen")

    conflict_services = device_manager.get_conflicting_services(
        device["id"], exclude_role="weather"
    )
    receiver_manager.begin_handover(
        device["id"],
        mission_key=autopilot_runtime["pass_key"],
        reason="AUTO Weather-missie",
        services=conflict_services,
        service_state=service_state,
        service_action=run_systemctl,
        wait_for_service=wait_for_service,
        previous_profile=state.get_sdr2_state().get("profile"),
    )

    try:
        profiles.set_active_profile("weather")
    except Exception:
        restore_autopilot_receiver(
            "Weather receiver context restored after profile activation failure"
        )
        raise
    write_log(
        f"AUTO: Weather actief op {device['number']} "
        f"({device['serial']}); conflicts={','.join(conflict_services) or 'geen'}"
    )
    event_bus.publish_receiver(
        "INFO",
        "Weather-receiver voorbereid",
        f"{device['number']} ({device['serial']}) is beschikbaar voor AUTO",
        data={
            "device_id": device["id"],
            "serial": device["serial"],
            "conflicting_services": conflict_services,
            "handover_authority": "receiver_manager",
        },
    )


def autopilot_lock_receiver():
    record_data = satdump_core.build_record_command(
        autopilot_runtime.get("target_pass")
    )

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


def set_autopilot_process(process):
    autopilot_runtime["process"] = process


def mission_stop_requested():
    return bool(autopilot_runtime.get("stop_requested"))


def cancel_active_mission(detail="Mission geannuleerd door operator"):
    status = mission_engine_core.get_mission_status()
    if status.get("active_job") is not None:
        mission_engine_core.mission_cancel(detail)


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
        autopilot_runtime["process"] = None

        if mission_stop_requested():
            write_log("AUTO: actieve missie is door operator geannuleerd")
            try:
                live_rf.fail("Mission geannuleerd door operator")
            except Exception as live_error:
                write_log(f"AUTO: Live RF stopstatus kon niet worden gezet: {live_error}")
            cancel_active_mission()
            return

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
            initial.get("cadu_bytes", 0) > 0
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
                process_callback=set_autopilot_process,
            )

            if mission_stop_requested():
                write_log("AUTO: productdecode is door operator geannuleerd")
                try:
                    live_rf.fail("Mission geannuleerd door operator")
                except Exception as live_error:
                    write_log(f"AUTO: Live RF stopstatus kon niet worden gezet: {live_error}")
                cancel_active_mission()
                return

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

        if mission_stop_requested():
            write_log("AUTO: missie geannuleerd vóór resultaatverwerking")
            try:
                live_rf.fail("Mission geannuleerd door operator")
            except Exception as live_error:
                write_log(f"AUTO: Live RF stopstatus kon niet worden gezet: {live_error}")
            cancel_active_mission()
            return

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
        try:
            restored = receiver_manager.restore_handover(
                mission_key=autopilot_runtime.get("pass_key"),
                service_state=service_state,
                service_action=run_systemctl,
                wait_for_service=wait_for_service,
                detail="Weather receiver context restored after mission",
            )
            if not restored.get("ok"):
                write_log(
                    "AUTO ERROR: receiver handover vereist aandacht: "
                    + "; ".join(restored.get("errors") or [])
                )
        except Exception as restore_error:
            write_log(f"AUTO ERROR: receiver handover herstellen mislukt: {restore_error}")
        autopilot_runtime["process"] = None
        mission_engine_core.mission_set_state("READY")
        write_log("AUTO: missie afgerond; oorspronkelijke receivercontext hersteld")
        if autopilot_runtime.get("stop_requested"):
            reset_autopilot_runtime()


def autopilot_start_recording():
    record_data = autopilot_runtime.get("record_data")

    if record_data is None:
        raise RuntimeError(
            "Geen voorbereid SatDump-commando beschikbaar"
        )

    satdump_core.align_timeout_to_pass_end(record_data)
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
    autopilot_runtime["process"] = process
    autopilot_runtime["stop_requested"] = False
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


def run_iss_voice_preflight(target):
    """Run mission-generic checks for an ISS Voice queue target."""
    checks = []

    mission_status = mission_engine_core.get_mission_status()
    mission_ready = (
        mission_status.get("active_job") is None
        and str(mission_status.get("phase") or "").upper() == "READY"
    )
    checks.append({
        "name": "Mission Engine",
        "ok": mission_ready,
        "detail": "READY en geen actieve Mission Job" if mission_ready else (
            f"Phase={mission_status.get('phase')}, "
            f"active_job={mission_status.get('active_job') is not None}"
        ),
    })

    validation = iss_voice.validate_config()
    checks.append({
        "name": "ISS Voice configuration",
        "ok": bool(validation.get("ok")),
        "detail": "Configuration valid" if validation.get("ok") else "; ".join(validation.get("errors") or []),
    })

    device = device_manager.get_assigned_device("iss_voice")
    device_ok = bool(device and device.get("serial"))
    checks.append({
        "name": "Assigned receiver",
        "ok": device_ok,
        "detail": (
            f"{device.get('number')} / {device.get('serial')}"
            if device_ok else "No receiver assigned to ISS Voice"
        ),
    })

    receiver_available = bool(
        device and receiver_manager.is_available(
            device["id"], mission_key=autopilot_runtime.get("pass_key")
        )
    )
    checks.append({
        "name": "Receiver availability",
        "ok": receiver_available,
        "detail": (
            f"{device.get('number')} is available"
            if receiver_available and device else "Assigned receiver is reserved by another mission"
        ),
    })

    passed = all(item["ok"] for item in checks)
    failed = [item["name"] for item in checks if not item["ok"]]
    result = {
        "passed": passed,
        "status": "OK" if passed else "FAILED",
        "detail": "All ISS Voice preflight checks passed" if passed else "Failed: " + ", ".join(failed),
        "checks": checks,
    }
    event_bus.publish_preflight(
        "SUCCESS" if passed else "WARNING",
        "ISS Voice preflight passed" if passed else "ISS Voice preflight failed",
        result["detail"],
        data={"passed": passed, "failed_checks": failed, "checks": checks, "pass": target},
    )
    return result


def prepare_iss_voice_receiver(target):
    """Validate the configured receiver before the reservation boundary."""
    device = device_manager.get_assigned_device("iss_voice")
    if device is None:
        raise RuntimeError("No receiver assigned to ISS Voice")
    if not receiver_manager.is_available(
        device["id"], mission_key=autopilot_runtime.get("pass_key")
    ):
        raise RuntimeError(f"{device['number']} is reserved by another mission")
    write_log(
        f"AUTO: ISS Voice receiver prepared: {device['number']} ({device['serial']})"
    )
    event_bus.publish_receiver(
        "INFO",
        "ISS Voice receiver prepared",
        f"{device['number']} ({device['serial']}) passed preparation checks",
        data={
            "device_id": device["id"],
            "serial": device["serial"],
            "mission_type": "iss_voice",
            "pass": target,
        },
    )


def lock_iss_voice_receiver(target):
    """Reserve the configured receiver at the normal mission lock boundary."""
    device = device_manager.get_assigned_device("iss_voice")
    if device is None:
        raise RuntimeError("No receiver assigned to ISS Voice")
    receiver_manager.reserve(
        device["id"],
        mission_key=autopilot_runtime["pass_key"],
        reason="AUTO ISS Voice mission",
    )
    write_log(
        f"AUTO: ISS Voice receiver locked: {device['number']} ({device['serial']})"
    )
    event_bus.publish_mission(
        "INFO",
        "ISS Voice mission locked",
        f"{device['number']} reserved for {target.get('name', 'ISS')}",
        data={
            "device_id": device["id"],
            "serial": device["serial"],
            "mission_type": "iss_voice",
            "pass": target,
        },
    )


def run_iss_voice_autopilot(target):
    """Execute one queue-selected ISS mission through the flexible receiver lifecycle."""
    autopilot_runtime["iss_execution_active"] = True
    try:
        write_log(f"AUTO: ISS Voice execution gestart voor {target.get('name', 'ISS')}")
        result = iss_voice_executor.execute_pass(
            target=target, service_state=service_state, service_action=run_systemctl,
            wait_for_service=wait_for_service,
            mission_key=autopilot_runtime.get("pass_key"),
        )
        autopilot_runtime["iss_execution_result"] = result
        write_log(f"AUTO: ISS Voice execution PASS: {result['mission']['mission_id']}")
    except Exception as error:
        autopilot_runtime["iss_execution_result"] = {"ok": False, "error": str(error)}
        write_log(f"AUTO: ISS Voice execution FAILED: {error}")
        event_bus.publish_mission("ERROR", "ISS Voice mission failed", str(error), data={"pass": target})
    finally:
        autopilot_runtime["iss_execution_active"] = False


def mission_autopilot_worker():
    write_log("Mission autopilot gestart")

    while True:
        try:
            scheduler = mission_scheduler_core.get_scheduler_status()
            mode = str(scheduler.get("mode") or "MANUAL").upper()
            next_pass = scheduler.get("next_pass")

            if mode in {"MANUAL", "PAUSED"}:
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            if mission_queue_core.is_pass_skipped(next_pass):
                if autopilot_runtime.get("target_pass") and not autopilot_runtime.get("record_started"):
                    restore_autopilot_receiver(
                        "Receiver context restored after Mission Queue skip"
                    )
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
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            # A queue override can be changed while a target is already prepared.
            if mission_queue_core.is_pass_skipped(target) and not autopilot_runtime.get("record_started"):
                write_log(f"AUTO: passage overgeslagen via Mission Queue: {target.get('name', '-')}")
                restore_autopilot_receiver(
                    "Receiver context restored after Mission Queue override"
                )
                reset_autopilot_runtime()
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

            now_epoch = int(time.time())
            start_epoch = int(target["start_epoch"])
            end_epoch = int(target["end_epoch"])
            seconds_until_start = start_epoch - now_epoch

            mission_type = str(target.get("mission_type") or "weather")
            config = scheduler["observer"]["config"]
            preflight_seconds = int(config["preflight_seconds"])
            prepare_seconds = int(config["prepare_seconds"])
            lock_seconds = int(config["lock_seconds"])

            if mission_type == "iss_voice":
                if (
                    0 < seconds_until_start <= preflight_seconds
                    and not autopilot_runtime["preflight_ok"]
                    and time.monotonic() - autopilot_runtime["last_preflight_attempt"] >= 10
                ):
                    autopilot_runtime["last_preflight_attempt"] = time.monotonic()
                    result = run_iss_voice_preflight(target)
                    if result["passed"]:
                        autopilot_runtime["preflight_ok"] = True
                        write_log(f"AUTO: ISS Voice preflight OK for {target['name']}")
                    else:
                        write_log(f"AUTO: ISS Voice preflight FAILED: {result['detail']}")

                if (
                    0 < seconds_until_start <= prepare_seconds
                    and autopilot_runtime["preflight_ok"]
                    and not autopilot_runtime["prepared"]
                ):
                    prepare_iss_voice_receiver(target)
                    autopilot_runtime["prepared"] = True

                if (
                    0 < seconds_until_start <= lock_seconds
                    and autopilot_runtime["prepared"]
                    and not autopilot_runtime["locked"]
                ):
                    lock_iss_voice_receiver(target)
                    autopilot_runtime["locked"] = True

                if (
                    -2 <= seconds_until_start <= 1
                    and autopilot_runtime["locked"]
                    and not autopilot_runtime["record_started"]
                ):
                    autopilot_runtime["record_started"] = True
                    threading.Thread(
                        target=run_iss_voice_autopilot, args=(dict(target),), daemon=True,
                        name="sdrcc-iss-voice-executor",
                    ).start()

                if now_epoch > end_epoch and not autopilot_runtime["record_started"]:
                    try:
                        restore_autopilot_receiver(
                            "ISS Voice pass missed before execution"
                        )
                    except Exception as restore_error:
                        write_log(f"AUTO: ISS Voice reservation restore failed: {restore_error}")
                    write_log("AUTO: ISS Voice pass missed without recording")
                    reset_autopilot_runtime()

                if (
                    autopilot_runtime["record_started"]
                    and not autopilot_runtime.get("iss_execution_active")
                    and autopilot_runtime.get("iss_execution_result") is not None
                ):
                    reset_autopilot_runtime()
                time.sleep(AUTOPILOT_POLL_SECONDS)
                continue

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
                autopilot_prepare_receiver()
                autopilot_runtime["prepared"] = True

            if (
                0 < seconds_until_start <= lock_seconds
                and autopilot_runtime["prepared"]
                and not autopilot_runtime["locked"]
            ):
                autopilot_lock_receiver()
                autopilot_runtime["locked"] = True

            if (
                -2 <= seconds_until_start <= 1
                and autopilot_runtime["locked"]
                and not autopilot_runtime["record_started"]
            ):
                autopilot_runtime["record_started"] = True
                autopilot_start_recording()

            if now_epoch > end_epoch and not autopilot_runtime["record_started"]:
                write_log("AUTO: passage gemist zonder opname; ontvangers herstellen")
                if autopilot_runtime.get("prepared"):
                    restored = restore_autopilot_receiver(
                        "Weather receiver context restored after missed pass"
                    )
                    if not restored.get("ok"):
                        write_log(
                            "AUTO ERROR: herstel na gemiste passage vereist aandacht: "
                            + "; ".join(restored.get("errors") or [])
                        )
                mission_engine_core.mission_reset()
                reset_autopilot_runtime()

            if (
                autopilot_runtime["record_started"]
                and mission_engine_core.get_mission_status()["active_job"] is None
                and mission_engine_core.get_mission_status()["phase"] == "READY"
                and not autopilot_runtime.get("stop_requested")
            ):
                reset_autopilot_runtime()

        except Exception as error:
            write_log(f"Mission autopilot fout: {error}")
            event_bus.publish_automation(
                "ERROR",
                "Mission autopilot fout",
                str(error),
                data={"pass": autopilot_runtime.get("target_pass")},
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



@app.route("/api/iss-voice/audio-monitor", methods=["GET"])
def api_iss_voice_audio_monitor():
    """Read-only status for the ISS Voice live-audio foundation."""
    try:
        return jsonify(iss_voice_audio_monitor.get_status())
    except Exception as error:
        return jsonify({"ok": False, "authority": "observer_only", "error": str(error)}), 500


@app.route("/api/iss-voice/audio-stream", methods=["GET"])
def api_iss_voice_audio_stream():
    """Stream read-only live PCM audio from the active ISS IQ recording."""
    mission_id = str(request.args.get("mission_id") or "").strip()
    if not mission_id:
        return jsonify({"ok": False, "error": "mission_id ontbreekt"}), 400
    try:
        generator = iss_voice_audio_monitor.stream_wav(mission_id)
        return Response(
            stream_with_context(generator),
            mimetype="audio/wav",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except (ValueError, RuntimeError) as error:
        return jsonify({"ok": False, "authority": "observer_only", "error": str(error)}), 409


@app.route("/api/mission-operations")
def api_mission_operations():
    try:
        return jsonify(mission_operations.get_snapshot())
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
        }), 500



@app.route("/api/plugins", methods=["GET"])
def api_plugins():
    """Expose the central read-only plugin registry."""
    include_planned = request.args.get(
        "include_planned",
        default="true",
        type=str,
    ).strip().lower() not in {"0", "false", "no", "off"}

    validation = plugin_registry.validate_registry(
        assignment_roles=config_core.get_assignment_roles(),
    )
    if not validation["ok"]:
        return jsonify({
            "ok": False,
            "read_only": True,
            "source": "plugin_registry",
            "validation": validation,
            "plugins": [],
        }), 500

    payload = plugin_registry.get_registry_snapshot(
        include_planned=include_planned,
    )
    payload["validation"] = validation
    return jsonify(payload)


@app.route("/api/plugin-runtime", methods=["GET"])
def api_plugin_runtime():
    """Expose the read-only plugin runtime observation snapshot."""
    include_planned = request.args.get(
        "include_planned",
        default="true",
        type=str,
    ).strip().lower() not in {"0", "false", "no", "off"}

    try:
        return jsonify(plugin_runtime_core.get_snapshot(
            include_planned=include_planned,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "read_only": True,
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "source": "plugin_runtime",
            "error": str(error),
            "plugins": [],
        }), 500



@app.route("/api/plugin-execution-runtime", methods=["GET"])
def api_plugin_execution_runtime():
    """Expose the observer-only plugin execution lifecycle foundation."""
    include_planned = request.args.get("include_planned", default="true", type=str).strip().lower() not in {"0", "false", "no", "off"}
    try:
        return jsonify(plugin_execution_runtime_core.get_snapshot(include_planned=include_planned))
    except Exception as error:
        return jsonify({"ok": False, "read_only": True, "foundation_only": True, "behavior_changed": False, "error": str(error), "plugins": []}), 500


@app.route("/api/receiver-inventory", methods=["GET"])
def api_receiver_inventory():
    """Expose the read-only physical-to-runtime receiver inventory."""
    try:
        snapshot = receiver_inventory_core.get_snapshot()
        snapshot["assignment_verification"] = receiver_authority.get_snapshot()
        return jsonify(snapshot)
    except Exception as error:
        return jsonify({"ok": False, "read_only": True, "error": str(error), "receivers": []}), 500

@app.route("/api/plugin-health", methods=["GET"])
def api_plugin_health():
    """Expose the read-only plugin health and validation snapshot."""
    include_planned = request.args.get(
        "include_planned",
        default="true",
        type=str,
    ).strip().lower() not in {"0", "false", "no", "off"}

    try:
        return jsonify(plugin_health_core.get_snapshot(
            include_planned=include_planned,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "read_only": True,
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "runtime_source": "plugin_runtime",
            "source": "plugin_health",
            "error": str(error),
            "plugins": [],
        }), 500


@app.route("/api/execution-plan-consumers", methods=["GET"])
def api_execution_plan_consumers():
    return jsonify(execution_plan_consumer_core.get_snapshot())


@app.route("/api/execution-journal", methods=["GET"])
def api_execution_journal():
    """Expose observer-only Execution Plan journal entries."""
    limit = request.args.get("limit", default=100, type=int)
    offset = request.args.get("offset", default=0, type=int)
    plugin_id = request.args.get("plugin", default=None, type=str)
    status = request.args.get("status", default=None, type=str)
    execution_id = request.args.get("execution_id", default=None, type=str)
    return jsonify(execution_journal_core.get_snapshot(
        limit=limit,
        offset=offset,
        plugin_id=plugin_id,
        status=status,
        execution_id=execution_id,
    ))


@app.route("/api/plugin-manager", methods=["GET"])
def api_plugin_manager():
    """Expose the central read-only Plugin Manager facade."""
    include_planned = request.args.get(
        "include_planned",
        default="true",
        type=str,
    ).strip().lower() not in {"0", "false", "no", "off"}

    try:
        return jsonify(plugin_manager_core.get_snapshot(
            include_planned=include_planned,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "read_only": True,
            "source": "plugin_manager",
            "metadata_authority": "plugin_registry",
            "receiver_authority": "receiver_manager",
            "runtime_source": "plugin_runtime",
            "health_source": "plugin_health",
            "error": str(error),
            "plugins": [],
        }), 500


@app.route("/api/plugin-manager/<plugin_id>/action", methods=["POST"])
def api_plugin_manager_action(plugin_id):
    """Execute an enabled service plugin through existing authority.

    v0.45.0 enables Weather through the existing Mission Scheduler/autopilot
    and keeps AIS/ADS-B on handle_service_action(). No direct SatDump or new
    service-control authority is introduced.
    """
    normalized_plugin = str(plugin_id or "").strip().lower()
    payload = request.get_json(silent=True) or {}
    normalized_action = str(payload.get("action") or "").strip().lower()

    if normalized_plugin == "weather":
        if normalized_action == "start":
            mission_status = mission_engine_core.get_mission_status()
            active_job = mission_status.get("active_job")
            active_runtime = any((
                autopilot_runtime.get("prepared"),
                autopilot_runtime.get("locked"),
                autopilot_runtime.get("record_started"),
                autopilot_runtime.get("process") is not None,
            ))
            if active_job is not None or active_runtime:
                return jsonify({
                    "ok": False,
                    "message": "Er is al een Weather-missie actief of in voorbereiding.",
                    "plugin_id": "weather",
                    "execution_enabled": True,
                    "authority": "existing_mission_scheduler_autopilot_path",
                }), 409

            scheduler_before = mission_scheduler_core.get_scheduler_status()
            next_pass = scheduler_before.get("next_pass")
            if not isinstance(next_pass, dict) or not next_pass.get("name"):
                return jsonify({
                    "ok": False,
                    "message": "Geen geldige eerstvolgende Weather-passage beschikbaar.",
                    "plugin_id": "weather",
                    "execution_enabled": True,
                    "authority": "existing_mission_scheduler_autopilot_path",
                }), 409

            scheduler_after = mission_scheduler_core.set_scheduler_mode("AUTO")
            return jsonify({
                "ok": True,
                "message": "Weather is ingeschakeld voor de eerstvolgende geldige passage.",
                "plugin_id": "weather",
                "action": "start",
                "execution_enabled": True,
                "execution_mode": "delegated_mission_scheduler_autopilot",
                "operation_authority": "existing_mission_scheduler_autopilot_path",
                "behavior_changed": False,
                "immediate_recording": False,
                "selected_pass": next_pass,
                "scheduler_before": scheduler_before,
                "scheduler": scheduler_after,
            })

        if normalized_action == "stop":
            mission_status = mission_engine_core.get_mission_status()
            active_job = mission_status.get("active_job")
            active_runtime = any((
                autopilot_runtime.get("prepared"),
                autopilot_runtime.get("locked"),
                autopilot_runtime.get("record_started"),
                autopilot_runtime.get("process") is not None,
            ))
            if active_job is not None or active_runtime:
                result, status_code = _stop_active_mission()
                result.update({
                    "plugin_id": "weather",
                    "execution_enabled": True,
                    "execution_mode": "delegated_mission_scheduler_autopilot",
                    "operation_authority": "existing_mission_scheduler_autopilot_path",
                    "behavior_changed": False,
                })
                return jsonify(result), status_code

            scheduler_before = mission_scheduler_core.get_scheduler_status()
            scheduler_after = mission_scheduler_core.set_scheduler_mode("MANUAL")
            return jsonify({
                "ok": True,
                "message": "Weather is uitgeschakeld; de Scheduler staat op MANUAL.",
                "plugin_id": "weather",
                "action": "stop",
                "execution_enabled": True,
                "execution_mode": "delegated_mission_scheduler_autopilot",
                "operation_authority": "existing_mission_scheduler_autopilot_path",
                "behavior_changed": False,
                "active_mission_stopped": False,
                "scheduler_before": scheduler_before,
                "scheduler": scheduler_after,
            })

        return jsonify({
            "ok": False,
            "message": f"Niet-ondersteunde WEATHER-actie: {normalized_action!r}",
            "plugin_id": "weather",
            "supported_actions": ["start", "stop"],
        }), 400

    service_actions = {
        "ais": {
            "start": "start_ais",
            "stop": "stop_ais",
            "restart": "restart_ais",
        },
        "adsb": {
            "start": "start_adsb",
            "stop": "stop_adsb",
            "restart": "restart_adsb",
        },
    }

    plugin_actions = service_actions.get(normalized_plugin)
    if plugin_actions is None:
        return jsonify({
            "ok": False,
            "message": f"Plugin execution is nog niet ingeschakeld voor {normalized_plugin or '<leeg>'}.",
            "plugin_id": normalized_plugin,
            "execution_enabled": False,
            "authority": "existing_dashboard_systemctl_path",
        }), 409

    action_id = plugin_actions.get(normalized_action)
    action = SERVICE_ACTIONS.get(action_id) if action_id else None
    if action is None:
        return jsonify({
            "ok": False,
            "message": f"Niet-ondersteunde {normalized_plugin.upper()}-actie: {normalized_action!r}",
            "plugin_id": normalized_plugin,
            "supported_actions": ["start", "stop", "restart"],
        }), 400

    return handle_service_action(action_id, action)


@app.route("/api/plugin-capabilities", methods=["GET"])
def api_plugin_capabilities():
    """Expose the central read-only Plugin Capability Layer."""
    include_planned = request.args.get(
        "include_planned",
        default="true",
        type=str,
    ).strip().lower() not in {"0", "false", "no", "off"}

    try:
        return jsonify(plugin_capabilities_core.get_snapshot(
            include_planned=include_planned,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "read_only": True,
            "source": "plugin_capabilities",
            "metadata_authority": "plugin_registry",
            "error": str(error),
            "plugins": {},
            "capabilities": {},
        }), 500


@app.route("/api/receiver-registry", methods=["GET"])
def api_receiver_registry():
    try:
        return jsonify(receiver_registry.public_snapshot())
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 500


@app.route("/api/receiver-contexts", methods=["GET"])
def api_receiver_contexts():
    """Expose the read-only assignment/default/restore foundation."""
    try:
        return jsonify(receiver_contexts_core.get_snapshot())
    except Exception as error:
        return jsonify({"ok": False, "read_only": True, "error": str(error)}), 500


def _receiver_assignment_block_reason():
    mission = mission_engine_core.get_mission_status()
    receiver_status = get_reconciled_receiver_manager_status()
    reservations = receiver_status.get("canonical_reservations")
    if not isinstance(reservations, dict):
        reservations = receiver_status.get("reservations") or {}
    if (
        mission.get("phase") not in {"READY", "WAIT FOR PASS"}
        or autopilot_runtime.get("prepared")
        or autopilot_runtime.get("locked")
        or autopilot_runtime.get("record_started")
        or any(isinstance(value, dict) for value in reservations.values())
    ):
        return "Receiver assignments kunnen niet tijdens een actieve missie worden gewijzigd."
    return None


def _reserve_assignment_transaction_receivers():
    """Atomically protect the transaction against new mission reservations.

    Receiver Manager remains the reservation authority. Unique owner keys let
    us protect both receivers using its existing one-owner-per-receiver model.
    If a concurrent mission wins either reservation, no assignment mutation is
    started and every reservation already obtained here is released.
    """
    reservation_keys = []
    try:
        receiver_ids = config_core.get_assignment_restore_policy()["receiver_ids"]
        for receiver_id in receiver_ids:
            key = f"receiver_authority:{receiver_id}"
            receiver_manager.reserve(
                receiver_id,
                mission_key=key,
                reason="receiver assignment transaction",
            )
            reservation_keys.append(key)
        return reservation_keys
    except Exception:
        for key in reversed(reservation_keys):
            try:
                receiver_manager.release(
                    mission_key=key,
                    detail="Receiver assignment transaction afgebroken",
                )
            except Exception:
                pass
        raise


def _release_assignment_transaction_receivers(reservation_keys):
    errors = []
    for key in reversed(reservation_keys or []):
        try:
            receiver_manager.release(
                mission_key=key,
                detail="Receiver assignment transaction afgerond",
            )
        except Exception as error:
            errors.append(f"{key}: {error}")
    return errors


def _apply_receiver_assignment_changes(changes):
    blocked = _receiver_assignment_block_reason()
    if blocked:
        return {"ok": False, "message": blocked}, 409
    reservation_keys = []
    try:
        reservation_keys = _reserve_assignment_transaction_receivers()
        result = receiver_authority.apply_assignments(
            changes,
            privileged_apply=apply_receiver_service_configuration,
        )
    except (TypeError, ValueError) as error:
        return {"ok": False, "message": str(error)}, 400
    except RuntimeError as error:
        return {
            "ok": False,
            "message": f"Receiver Manager kon de assignment transaction niet reserveren: {error}",
        }, 409
    except Exception as error:
        return {"ok": False, "message": str(error)}, 500
    finally:
        release_errors = _release_assignment_transaction_receivers(reservation_keys)
        if release_errors:
            write_log(
                "Receiver Authority reservation release fout: "
                + "; ".join(release_errors)
            )

    if not result.get("ok"):
        write_log(
            "Receiver Authority transaction mislukt: "
            f"{result.get('message')}; rollback_ok={result.get('rollback_ok')}"
        )
        return result, (409 if result.get("rollback_ok") else 500)

    assignments = result.get("assignments") or {}
    write_log(
        "Receiver Authority toegepast: "
        + ", ".join(f"{role}={receiver}" for role, receiver in assignments.items())
    )
    event_bus.publish_receiver(
        "INFO",
        "Receiver assignments applied",
        "Assignment Authority and service configuration are synchronized",
        data={
            "assignment_authority": result.get("assignment_authority"),
            "assignments": assignments,
            "changed": result.get("changed"),
            "configuration_drift": (
                result.get("verification") or {}
            ).get("configuration_drift"),
        },
    )
    return result, 200


@app.route("/api/receiver-assignments", methods=["GET", "POST"])
def api_receiver_assignments():
    """Expose and change the single Receiver Assignment Authority."""
    if request.method == "GET":
        try:
            return jsonify(receiver_authority.get_snapshot())
        except Exception as error:
            return jsonify({"ok": False, "message": str(error)}), 500

    payload = request.get_json(silent=True) or {}
    raw_changes = payload.get("assignments", payload)
    if not isinstance(raw_changes, dict):
        return jsonify({"ok": False, "message": "assignments moet een mapping zijn"}), 400
    allowed = {"weather", "ais", "adsb", "iss_voice"}
    unknown = set(raw_changes) - allowed
    if unknown:
        return jsonify({
            "ok": False,
            "message": "Onbekende receiverrol: " + ", ".join(sorted(unknown)),
        }), 400
    changes = {role: raw_changes[role] for role in allowed if role in raw_changes}
    if not changes:
        return jsonify({"ok": False, "message": "Geen assignments aangeleverd"}), 400
    result, status = _apply_receiver_assignment_changes(changes)
    return jsonify(result), status


@app.route("/api/mission-assignments", methods=["POST"])
def api_mission_assignments():
    payload = request.get_json(silent=True) or {}
    changes = {
        role: payload.get(role)
        for role in config_core.get_mission_assignment_roles()
        if role in payload
    }
    result, status = _apply_receiver_assignment_changes(changes)
    result["mission_assignments"] = config_core.get_mission_assignments()
    result.setdefault("message", "Mission assignments via Assignment Authority toegepast.")
    return jsonify(result), status


@app.route("/api/receiver-defaults", methods=["POST"])
def api_receiver_defaults():
    payload = request.get_json(silent=True) or {}
    try:
        defaults = payload.get("receiver_defaults", payload)
        if not isinstance(defaults, dict):
            raise ValueError("Receiver defaults moeten als mapping worden aangeleverd")
        changes = {"ais": None, "adsb": None}
        for receiver_id, raw_plugins in defaults.items():
            plugins = [raw_plugins] if isinstance(raw_plugins, str) else (raw_plugins or [])
            for plugin_id in plugins:
                normalized = str(plugin_id or "").strip().lower()
                if normalized in changes:
                    if changes[normalized] is not None:
                        raise ValueError(f"{normalized.upper()} kan maar één receiver hebben")
                    changes[normalized] = receiver_id
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    result, status = _apply_receiver_assignment_changes(changes)
    result["receiver_defaults"] = config_core.get_receiver_defaults()
    result.setdefault("message", "Receiver defaults via Assignment Authority toegepast.")
    return jsonify(result), status


@app.route("/api/receiver-runtime", methods=["GET"])
def api_receiver_runtime():
    """Expose the read-only Receiver Runtime observation snapshot."""
    try:
        snapshot = receiver_runtime_core.get_snapshot()
        snapshot["assignment_verification"] = receiver_authority.get_snapshot()
        return jsonify(snapshot)
    except Exception as error:
        return jsonify({
            "ok": False,
            "read_only": True,
            "authority": "receiver_manager",
            "error": str(error),
            "receivers": {},
        }), 500


@app.route("/api/receiver-monitor")
def api_receiver_monitor():
    try:
        mission = mission_engine_core.get_mission_status()
        ais = service_state("ais-catcher.service")
        adsb = service_state("readsb.service")
        live = live_rf.get_status()
        authority = receiver_authority.get_snapshot(
            mission_status=mission,
            weather_runtime=live,
            iss_runtime=iss_voice_runtime.get_status(),
            use_cache=False,
        )
        return jsonify(receiver_monitor.get_snapshot(
            devices=device_manager.get_devices(),
            assignments=config_core.get_receiver_assignments(),
            ais_service=ais,
            adsb_service=adsb,
            mission=mission,
            live_rf=live,
            authority_snapshot=authority,
        ))
    except Exception as error:
        return jsonify({
            "ok": False,
            "error": str(error),
            "receivers": [],
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
        target_key = mission_queue_core.get_pass_key(target)
        iss_runtime = iss_voice_runtime.get_status()
        iss_active_key = (
            str(iss_runtime.get("queue_key") or "").strip()
            if iss_runtime.get("active")
            else None
        )
        active_key = iss_active_key or (
            target_key
            if target_key and autopilot_runtime.get("record_started")
            else None
        )

        mission_status = mission_engine_core.get_mission_status()
        if iss_runtime.get("active"):
            live_status = str(iss_runtime.get("phase") or "RECORDING").upper()
        else:
            live_status = str(
                mission_status.get("phase")
                or mission_status.get("state")
                or "WAITING"
            ).upper()
        return jsonify(mission_queue_core.get_payload(
            limit=limit,
            hours_ahead=hours,
            active_pass_key=active_key,
            target_pass_key=target_key,
            controller_status=live_status,
            pinned_pass=target or None,
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


def _active_mission_id():
    status = mission_engine_core.get_mission_status() or {}
    candidates = [
        status.get("active_job"),
        status.get("mission"),
        status.get("target_pass"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            value = str(candidate.get("mission_id") or "").strip()
            if value:
                return value
    return str(status.get("mission_id") or "").strip()


@app.route("/api/mission-history/<mission_id>", methods=["GET", "DELETE"])
def api_mission_history_detail(mission_id):
    if request.method == "DELETE":
        try:
            if mission_id == _active_mission_id():
                return jsonify({
                    "ok": False,
                    "error": "De actieve missie kan niet worden verwijderd",
                }), 409

            result = mission_history_core.delete_mission(mission_id)
            event_bus.publish_mission(
                "INFO",
                "Mission History verwijderd",
                f"Missie {mission_id} is handmatig verwijderd",
                data={
                    "mission_id": mission_id,
                    "satellite": result.get("satellite"),
                    "output_path": result.get("output_path"),
                },
            )
            return jsonify(result)
        except LookupError as error:
            return jsonify({"ok": False, "error": str(error)}), 404
        except ValueError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        except OSError as error:
            return jsonify({
                "ok": False,
                "error": f"Missiebestanden konden niet worden verwijderd: {error}",
            }), 500
        except Exception as error:
            return jsonify({"ok": False, "error": str(error)}), 500

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


def _mission_monitor_payload():
    """Return current mission state and the best available mission image."""
    live = live_rf.get_status() or {}
    active = bool(live.get("active"))
    satellite = str(live.get("satellite") or "").strip()
    state = str(live.get("state") or "IDLE").upper()
    detail = str(live.get("detail") or live.get("last_line") or "").strip()
    output_path = str(live.get("output_path") or "").strip()

    mission = None
    root = None
    files = []

    if output_path:
        mission = {
            "mission_id": "active",
            "satellite": satellite or "Weather mission",
            "pipeline": live.get("pipeline"),
            "output_path": output_path,
        }
        root, files = _mission_capture_files(mission)

    if not files:
        mission, root, files = _latest_successful_image_mission()

    image = None
    if mission and root is not None and files:
        selected = files[0]
        if str(mission.get("mission_id")) == "active":
            try:
                relative = selected.relative_to(root)
                image = capture_to_dict(selected, mission=None, root=None)
                image["url"] = f"/active-mission-preview/{str(relative).replace(chr(92), '/')}"
                image["source"] = "active"
            except (ValueError, OSError):
                image = None
        else:
            image = capture_to_dict(selected, mission=mission, root=root)

    if active:
        title = satellite or "Active weather mission"
        message = detail or "Waiting for the first decoded image..."
    elif image:
        title = str((mission or {}).get("satellite") or "Last successful mission")
        message = "Last successful mission image"
    else:
        title = "No active weather mission"
        message = "Waiting for the next mission..."

    return {
        "ok": True,
        "active": active,
        "state": state,
        "title": title,
        "message": message,
        "satellite": satellite or (mission or {}).get("satellite"),
        "image": image,
        "image_count": int(live.get("image_count") or 0),
        "frames": int(live.get("frames") or 0),
        "cadu_bytes": int(live.get("cadu_bytes") or 0),
        "peak_snr_db": live.get("peak_snr_db"),
        "updated_at": live.get("updated_at"),
    }


@app.route("/api/mission-monitor")
def api_mission_monitor():
    try:
        return jsonify(_mission_monitor_payload())
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 500


@app.route("/active-mission-preview/<path:relative_path>")
def active_mission_preview(relative_path):
    live = live_rf.get_status() or {}
    output_value = str(live.get("output_path") or "").strip()
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


@app.route("/api/mission-simulator")
def api_mission_simulator_status():
    return jsonify(mission_simulator.get_status())


@app.route("/api/mission-simulator/start", methods=["POST"])
def api_mission_simulator_start():
    payload = request.get_json(silent=True) or {}
    try:
        result = mission_simulator.start(
            scenario=payload.get("scenario", "success"),
            receiver_id=payload.get("receiver_id", "sdr2"),
            duration_seconds=payload.get("duration_seconds", 15),
        )
        return jsonify(result)
    except (ValueError, RuntimeError) as error:
        return jsonify({"ok": False, "message": str(error)}), 409
    except Exception as error:
        write_log(f"Mission Simulator startfout: {error}")
        return jsonify({"ok": False, "message": str(error)}), 500


@app.route("/api/mission-simulator/stop", methods=["POST"])
def api_mission_simulator_stop():
    result = mission_simulator.stop()
    return jsonify(result), (200 if result.get("ok") else 409)


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


def _normalise_receiver_id(value):
    text = str(value or "").strip().lower()
    aliases = {
        "1": "sdr1",
        "sdr 1": "sdr1",
        "sdr1": "sdr1",
        "2": "sdr2",
        "sdr 2": "sdr2",
        "sdr2": "sdr2",
    }
    return aliases.get(text)


def _active_mission_receiver(mission_status=None):
    mission_status = mission_status or mission_engine_core.get_mission_status()
    active_job = mission_status.get("active_job") or {}

    for key in ("receiver_id", "receiver", "receiver_name", "device"):
        receiver_id = _normalise_receiver_id(active_job.get(key))
        if receiver_id:
            return receiver_id

    reservation = receiver_manager.get_status().get("reservation") or {}
    device = reservation.get("device") or {}
    for value in (device.get("id"), device.get("number"), device.get("name")):
        receiver_id = _normalise_receiver_id(value)
        if receiver_id:
            return receiver_id

    return None


def _stop_active_mission(receiver_id=None):
    """Stop the active task for one receiver while preserving legacy behaviour.

    The simulator is stopped without changing Scheduler mode. A production
    mission retains the proven safety behaviour and switches the Scheduler to
    MANUAL before cancellation. The optional receiver_id prevents one receiver
    button from stopping work owned by the other receiver.
    """
    requested_receiver = _normalise_receiver_id(receiver_id)
    if receiver_id is not None and requested_receiver is None:
        return {
            "ok": False,
            "message": f"Onbekende receiver: {receiver_id}",
        }, 400

    simulator_status = mission_simulator.get_status().get("simulator", {})
    if simulator_status.get("active"):
        simulator_receiver = _normalise_receiver_id(simulator_status.get("receiver_id"))
        if requested_receiver and simulator_receiver != requested_receiver:
            return {
                "ok": False,
                "message": (
                    f"De actieve simulatiemissie draait op "
                    f"{str(simulator_receiver or 'onbekend').upper()}, niet op "
                    f"{requested_receiver.upper()}."
                ),
                "receiver_id": requested_receiver,
                "active_receiver_id": simulator_receiver,
            }, 409

        result = mission_simulator.stop()
        result.update({
            "operation": "stop",
            "runtime_type": "simulator",
            "receiver_id": simulator_receiver,
            "scheduler_changed": False,
            "scheduler": mission_scheduler_core.get_scheduler_status(),
        })
        return result, (200 if result.get("ok") else 409)

    mission_status = mission_engine_core.get_mission_status()
    active_job = mission_status.get("active_job")
    active_runtime = any((
        autopilot_runtime.get("prepared"),
        autopilot_runtime.get("locked"),
        autopilot_runtime.get("record_started"),
        autopilot_runtime.get("process") is not None,
    ))

    if active_job is None and not active_runtime:
        return {
            "ok": False,
            "message": "Er is geen actieve missie om te stoppen.",
            "mission": mission_status,
        }, 409

    active_receiver = _active_mission_receiver(mission_status)
    if requested_receiver and active_receiver and requested_receiver != active_receiver:
        return {
            "ok": False,
            "message": (
                f"De actieve missie draait op {active_receiver.upper()}, niet op "
                f"{requested_receiver.upper()}."
            ),
            "receiver_id": requested_receiver,
            "active_receiver_id": active_receiver,
            "mission": mission_status,
        }, 409

    mission_scheduler_core.set_scheduler_mode("MANUAL")
    autopilot_runtime["stop_requested"] = True

    process = autopilot_runtime.get("process")
    process_stopped = False
    if process is not None and process.poll() is None:
        write_log(f"STOP MISSION: proces {process.pid} beëindigen")
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            write_log(f"STOP MISSION: proces {process.pid} reageert niet; kill")
            process.kill()
            process.wait(timeout=5)
        process_stopped = True

    # Vóór Recording bestaat er geen watcher die annulering en herstel uitvoert.
    if not autopilot_runtime.get("record_started"):
        cancel_active_mission()
        try:
            restored = restore_autopilot_receiver(
                "Receiver context restored after operator stop"
            )
            if not restored.get("ok"):
                write_log(
                    "STOP MISSION: receiver handover vereist aandacht: "
                    + "; ".join(restored.get("errors") or [])
                )
        except Exception as restore_error:
            write_log(f"STOP MISSION: receiverherstel mislukt: {restore_error}")
        reset_autopilot_runtime()

    event_bus.publish_mission(
        "WARNING",
        "Mission gestopt door operator",
        "Actieve missie is gecontroleerd geannuleerd; Scheduler staat op MANUAL",
        data={
            "mission_id": (active_job or {}).get("mission_id"),
            "receiver_id": active_receiver or requested_receiver,
            "process_stopped": process_stopped,
            "scheduler_mode": "MANUAL",
        },
    )
    write_log("STOP MISSION: annulering aangevraagd; Scheduler MANUAL")

    return {
        "ok": True,
        "message": "Missie gestopt. Mission Scheduler staat op MANUAL.",
        "operation": "stop",
        "runtime_type": "mission_engine",
        "receiver_id": active_receiver or requested_receiver,
        "process_stopped": process_stopped,
        "scheduler_changed": True,
        "mission": mission_engine_core.get_mission_status(),
        "scheduler": mission_scheduler_core.get_scheduler_status(),
    }, 200


@app.route("/api/mission-operations/stop", methods=["POST"])
def api_mission_operations_stop():
    payload = request.get_json(silent=True) or {}
    result, status_code = _stop_active_mission(payload.get("receiver_id"))
    return jsonify(result), status_code


@app.route("/api/mission/stop", methods=["POST"])
def api_stop_mission():
    """Backward-compatible global stop endpoint."""
    result, status_code = _stop_active_mission()
    return jsonify(result), status_code


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



def get_reconciled_receiver_manager_status(*, recover=False):
    """Release a persisted receiver reservation when no mission runtime owns it.

    Receiver reservations are stored on disk so they survive a process restart.
    After an unexpected restart this can leave an ACTIVE reservation behind while
    Mission Engine is already back in READY or WAIT FOR PASS.  Only clear it when
    there is no active Mission Job and no prepared/locked/recording runtime.
    """
    if not recover:
        return receiver_manager.get_status()

    mission = mission_engine_core.get_mission_status()
    phase = str(mission.get("phase") or mission.get("state") or "").upper()
    runtime_active = any((
        mission_simulator.get_status().get("simulator", {}).get("active"),
        autopilot_runtime.get("prepared"),
        autopilot_runtime.get("locked"),
        autopilot_runtime.get("record_started"),
        autopilot_runtime.get("process") is not None,
    ))

    active_keys = []
    if runtime_active and autopilot_runtime.get("pass_key"):
        active_keys.append(autopilot_runtime["pass_key"])
    recovery = receiver_manager.recover_handovers(
        service_state=service_state,
        service_action=run_systemctl,
        wait_for_service=wait_for_service,
        active_mission_keys=active_keys,
    )
    if recovery.get("recovered"):
        write_log(
            "Receiver Manager: "
            f"{recovery['recovered']} achtergebleven handover(s) hersteld"
        )
    if recovery.get("attention"):
        write_log(
            "Receiver Manager: handover recovery vereist aandacht: "
            + str(recovery.get("results"))
        )

    status = receiver_manager.get_status()
    idle_runtime = (
        mission.get("active_job") is None
        and phase in {"READY", "WAIT FOR PASS"}
        and not runtime_active
    )

    if idle_runtime:
        canonical_reservations = status.get("canonical_reservations")
        if not isinstance(canonical_reservations, dict):
            canonical_reservations = {}

        stale_reservations = [
            reservation
            for reservation in canonical_reservations.values()
            if isinstance(reservation, dict)
            and not isinstance(reservation.get("handover"), dict)
            and str(reservation.get("status") or "").upper() != "ATTENTION"
        ]
        for stale in stale_reservations:
            mission_key = str(stale.get("mission_key") or "").strip()
            if not mission_key:
                continue
            receiver_id = (
                stale.get("runtime_id")
                or stale.get("receiver_id")
                or stale.get("registry_id")
                or "-"
            )
            try:
                receiver_manager.release(
                    mission_key=mission_key,
                    detail="Automatisch vrijgegeven na runtime-recovery: geen actieve missie",
                )
                write_log(
                    "Receiver Manager: achtergebleven reservering automatisch "
                    f"vrijgegeven ({receiver_id}, {mission_key})"
                )
            except Exception as release_error:
                write_log(
                    "Receiver Manager: automatische reservation recovery mislukt "
                    f"({receiver_id}, {mission_key}): {release_error}"
                )

        if stale_reservations:
            status = receiver_manager.get_status()

    return status


@app.route("/api/iss-voice/controlled-capture", methods=["POST"])
def api_iss_voice_controlled_capture():
    """Run one explicit bounded IQ capture; never schedule automatically."""
    payload = request.get_json(silent=True) or {}
    try:
        duration = int(payload.get("duration_seconds", 5))
        result = controlled_iq_capture.execute_controlled_capture(
            duration_seconds=duration,
            mission_id=payload.get("mission_id"),
            service_state=service_state,
            service_action=run_systemctl,
            wait_for_service=wait_for_service,
        )
        write_log(
            "ISS CONTROLLED CAPTURE: "
            f"{result['mission_id']} via {result['receiver']['number']} PASS"
        )
        return jsonify(result)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        write_log(f"ISS CONTROLLED CAPTURE FAILED: {error}")
        return jsonify({"ok": False, "error": str(error)}), 409


@app.route("/api/iss-voice/demodulate", methods=["POST"])
def api_iss_voice_demodulate():
    """Demodulate one existing ISS Voice IQ capture without receiver access."""
    payload = request.get_json(silent=True) or {}
    try:
        validation = iss_voice.validate_config()
        if not validation["ok"]:
            raise RuntimeError("ISS Voice-config ongeldig: " + "; ".join(validation["errors"]))
        config = validation["config"]
        if not bool(config.get("offline_demodulation_enabled")):
            raise RuntimeError("Offline demodulatie is uitgeschakeld")
        result = iss_voice_audio.demodulate_mission(payload.get("mission_id"), config)
        write_log(
            "ISS OFFLINE DEMODULATION: "
            f"{payload.get('mission_id')} -> {result['wav_path']} PASS"
        )
        return jsonify(result)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        write_log(f"ISS OFFLINE DEMODULATION FAILED: {error}")
        return jsonify({"ok": False, "error": str(error)}), 409


@app.route("/api/mission-recordings", methods=["GET"])
def api_mission_recordings():
    try:
        return jsonify(mission_recordings_core.inventory(
            limit=request.args.get("limit", default=100, type=int) or 100
        ))
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 500


@app.route("/api/mission-recordings/file/<path:relative_path>", methods=["GET"])
def api_mission_recording_file(relative_path):
    try:
        path = mission_recordings_core.safe_path(str(mission_recordings_core.ROOT / relative_path))
        return send_file(path, conditional=True)
    except (ValueError, FileNotFoundError):
        abort(404)


@app.route("/api/iss-voice/execute", methods=["POST"])
def api_iss_voice_execute():
    payload = request.get_json(silent=True) or {}
    try:
        result = iss_voice_executor.execute_pass(
            target=payload, service_state=service_state, service_action=run_systemctl,
            wait_for_service=wait_for_service,
        )
        return jsonify(result)
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        return jsonify({"ok": False, "error": str(error)}), 409


@app.route("/api/receiver-manager", methods=["GET"])
def api_receiver_manager():
    return jsonify(get_reconciled_receiver_manager_status())


@app.route("/api/receiver-assignment", methods=["POST"])
def api_receiver_assignment():
    payload = request.get_json(silent=True) or {}
    device_id = payload.get("weather")
    try:
        device = device_manager.get_device(device_id)
        if device is None:
            raise ValueError("Onbekende SDR-keuze")
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    result, status = _apply_receiver_assignment_changes({"weather": device_id})
    result["device"] = device
    result.setdefault("message", f"Weather gebruikt nu {device['number']}.")
    return jsonify(result), status



@app.route("/api/receiver-roles", methods=["POST"])
def api_receiver_roles():
    payload = request.get_json(silent=True) or {}
    roles = {
        "sdr1": str(payload.get("sdr1", "manual")).strip().lower(),
        "sdr2": str(payload.get("sdr2", "manual")).strip().lower(),
    }
    try:
        if any(role not in {"ais", "adsb", "manual"} for role in roles.values()):
            raise ValueError("Receiverrol moet AIS, ADS-B of manual zijn")
        if len([role for role in roles.values() if role == "ais"]) > 1:
            raise ValueError("AIS kan maar aan één receiver worden toegewezen")
        if len([role for role in roles.values() if role == "adsb"]) > 1:
            raise ValueError("ADS-B kan maar aan één receiver worden toegewezen")
        changes = {
            "ais": next((receiver for receiver, role in roles.items() if role == "ais"), None),
            "adsb": next((receiver for receiver, role in roles.items() if role == "adsb"), None),
        }
    except Exception as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    result, status = _apply_receiver_assignment_changes(changes)
    result["roles"] = roles
    result.setdefault("message", "Receiverrollen via Assignment Authority toegepast.")
    return jsonify(result), status


@app.route("/api/receiver-roles/apply", methods=["POST"])
def api_receiver_roles_apply():
    assignments = config_core.get_receiver_assignments()
    result, status = _apply_receiver_assignment_changes(assignments)
    result.setdefault("message", "Serviceconfiguratie met Assignment Authority gesynchroniseerd.")
    return jsonify(result), status


@app.route("/api/weather-planning", methods=["GET", "POST"])
def api_weather_planning():
    if request.method == "GET":
        try:
            return jsonify({
                "ok": True,
                "settings": weather_planning_core.get_config(),
                "tle": tle.get_status(),
            })
        except (ValueError, OSError) as error:
            return jsonify({"ok": False, "message": str(error)}), 500

    payload = request.get_json(silent=True) or {}
    if str(payload.get("action") or "").lower() == "refresh":
        result = tle_downloader.refresh_required_tles(force=bool(payload.get("force", False)))
        usable = bool(result.get("ok") or result.get("preserved"))
        write_log(
            "Mission Planner TLE refresh: "
            + (result.get("message") or result.get("error") or "unknown result")
        )
        return jsonify({
            "ok": usable,
            "warning": not bool(result.get("ok")),
            "message": result.get("message"),
            "error": result.get("error"),
            "tle": result.get("status") or tle.get_status(),
            "settings": weather_planning_core.get_config(),
        }), (200 if usable else 503)

    mission = get_mission_data_for_status()
    scheduler = mission_scheduler_core.get_scheduler_status()
    mission_phase = str(mission.get("state") or mission.get("phase") or "").upper()
    observer_phase = str((scheduler.get("observer") or {}).get("phase") or "").upper()
    blocked = mission_phase not in {"", "READY", "WAIT FOR PASS"} or observer_phase in {
        "PREPARE RECEIVER", "FINAL APPROACH", "PASS ACTIVE"
    }
    if blocked:
        return jsonify({"ok": False, "message": "Weather Planning is geblokkeerd tijdens een missie."}), 409
    try:
        settings = weather_planning_core.set_config(payload)
        write_log("Mission Planner pass-window profiles updated")
        return jsonify({
            "ok": True,
            "settings": settings,
            "tle": tle.get_status(),
            "message": "Pass-window settings saved. New Mission Queue entries use them immediately.",
        })
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    except OSError as error:
        return jsonify({"ok": False, "message": f"Configuratie kon niet worden opgeslagen: {error}"}), 500


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
        write_log(f"Weather/METEOR-instellingen gewijzigd: mode={settings['gain_mode']} gain={settings['gain_db']} dB lna_agc={settings['lna_agc']} fill_missing={settings['fill_missing']} rs_usecheck={settings['rs_usecheck']}")
        return jsonify({"ok": True, "settings": settings, "message": "Weather / METEOR-instellingen opgeslagen."})
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400


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

        if action_id == "simulate_record":
            mission = start_virtual_mission()
            return jsonify({
                "ok": True,
                "message": "Virtuele missie gestart. STOP MISSION is nu beschikbaar.",
                "mission": mission,
            })

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



def recover_stale_iss_voice_observer():
    """Reconcile the persisted ISS observer after an interrupted restart."""
    try:
        receiver_status = get_reconciled_receiver_manager_status(recover=True)
        result = iss_voice_runtime_recovery.recover_if_stale(
            mission_status=mission_engine_core.get_mission_status(),
            receiver_status=receiver_status,
            iss_execution_active=bool(autopilot_runtime.get("iss_execution_active")),
        )
        if result.get("changed"):
            write_log(
                "ISS Voice runtime: achtergebleven observerstatus automatisch "
                f"hersteld ({result.get('mission_id') or '-'})"
            )
        return result
    except Exception as recovery_error:
        write_log(f"ISS Voice runtime recovery overgeslagen: {recovery_error}")
        return {"ok": False, "changed": False, "error": str(recovery_error)}

def run():
    recover_stale_iss_voice_observer()
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
