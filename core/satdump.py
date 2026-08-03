#!/usr/bin/env python3

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from core import mission_result
from zoneinfo import ZoneInfo
import subprocess
import time

from core import event_bus
from core import passes
from core import config as config_core
from core import process_manager
from core import receiver_manager
from core import state
from core.device_manager import get_assigned_device, get_conflicting_services

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "recordings"


def _active_mission_context():
    """Return active Mission Engine telemetry without creating an import cycle."""

    try:
        from core import mission_engine as mission_engine_core

        active_job = (
            mission_engine_core.get_mission_status().get("active_job") or {}
        )
        return {
            key: active_job.get(key)
            for key in (
                "mission_id",
                "satellite",
                "receiver",
                "receiver_id",
                "receiver_serial",
                "frequency",
                "frequency_mhz",
                "mode",
                "pipeline",
                "output_path",
            )
            if active_job.get(key) is not None
        }
    except Exception:
        return {}


def build_event_context(record_data=None):
    """Build one consistent telemetry payload for SatDump and receiver events."""

    record_data = record_data or {}
    pass_data = record_data.get("pass") or {}
    device = record_data.get("device") or {}
    context = _active_mission_context()

    context.update({
        "satellite": pass_data.get("name", context.get("satellite")),
        "receiver": device.get("number", context.get("receiver")),
        "receiver_id": device.get("id", context.get("receiver_id")),
        "receiver_serial": device.get(
            "serial", context.get("receiver_serial")
        ),
        "frequency": pass_data.get("frequency", context.get("frequency")),
        "frequency_mhz": (
            round(pass_data["frequency"] / 1_000_000, 3)
            if pass_data.get("frequency") is not None
            else context.get("frequency_mhz")
        ),
        "mode": pass_data.get("mode", context.get("mode")),
        "pipeline": pass_data.get("pipeline", context.get("pipeline")),
        "sample_rate": pass_data.get("sample_rate"),
        "output_path": (
            str(record_data["output_path"])
            if record_data.get("output_path") is not None
            else context.get("output_path")
        ),
        "timeout_seconds": record_data.get("timeout_seconds"),
    })
    return {key: value for key, value in context.items() if value is not None}


def check_recording_allowed():
    current_state = state.get_sdr2_state()
    device = get_assigned_device("weather")

    if current_state["profile"] not in {"weather", "adsb"}:
        return False, (
            f"SDR2 staat nu op profiel '{current_state['profile']}'.\n"
            "Opnemen is alleen toegestaan vanuit het profiel "
            "weather of adsb."
        )

    if device and device["id"] == "sdr2" and current_state["locked"]:
        return False, "SDR2 is gelocked en mag nu niet gebruikt worden."

    if device and device["id"] == "sdr2" and current_state["status"] != "idle":
        return False, (
            f"SDR2 is niet vrij.\n"
            f"Status : {current_state['status']}\n"
            f"Process: {current_state['process']}"
        )

    if device is None:
        return False, "Geen dynamische SDR gevonden."

    if not device.get("serial"):
        return False, "Dynamische SDR heeft geen serienummer."

    return True, "OK"


def _normalize_planned_pass(pass_data):
    item = deepcopy(pass_data)
    for field in ("start", "maximum", "end"):
        if hasattr(item.get(field), "timestamp"):
            continue
        epoch = item.get(f"{field}_epoch")
        if epoch is None:
            raise ValueError(f"Planned pass has no {field} time")
        item[field] = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    item.setdefault("duration_seconds", int((item["end"] - item["start"]).total_seconds()))
    return item


def build_record_command(pass_data=None):
    allowed, reason = check_recording_allowed()

    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
        }

    next_pass = _normalize_planned_pass(pass_data) if pass_data is not None else passes.get_next_pass()

    if next_pass is None:
        return None

    device = get_assigned_device("weather")

    start_local = next_pass["start"].astimezone(LOCAL_TZ)
    safe_name = next_pass["name"].replace(" ", "_").replace("/", "_")
    folder_name = f"{start_local.strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    output_path = OUTPUT_DIR / folder_name

    duration = next_pass["end"] - next_pass["start"]
    timeout_seconds = max(1, int(duration.total_seconds()))

    command = [
        "satdump",
        "live",
        next_pass["pipeline"],
        str(output_path),
        "--source",
        "rtlsdr",
        "--source_id",
        device["serial"],
        "--frequency",
        str(next_pass["frequency"]),
        "--samplerate",
        str(next_pass["sample_rate"]),
        "--timeout",
        str(timeout_seconds),
    ]

    rf = config_core.get_weather_rf_config()
    if rf["lna_agc"]:
        command.extend(["--lna_agc", "true"])
    elif rf["gain_mode"] == "manual":
        command.extend(["--gain", str(rf["gain_db"])])
    if rf["dc_block"]:
        command.append("--dc_block")
    if rf["iq_swap"]:
        command.append("--iq_swap")
    if rf["fill_missing"]:
        command.extend(["--fill_missing", "true"])
    if rf["rs_usecheck"]:
        command.extend(["--rs_usecheck", "true"])

    return {
        "allowed": True,
        "reason": "OK",
        "pass": next_pass,
        "device": device,
        "output_path": output_path,
        "timeout_seconds": timeout_seconds,
        "rf": rf,
        "command": command,
    }


def align_timeout_to_pass_end(record_data, *, now_epoch=None):
    """Keep SatDump bounded by the immutable falling-edge end time."""
    data = record_data
    pass_data = data.get("pass") or {}
    end = pass_data.get("end")
    end_epoch = int(end.timestamp()) if hasattr(end, "timestamp") else int(pass_data.get("end_epoch") or 0)
    current_epoch = int(datetime.now(timezone.utc).timestamp()) if now_epoch is None else int(now_epoch)
    remaining = max(1, end_epoch - current_epoch)
    command = list(data.get("command") or [])
    if "--timeout" not in command:
        raise ValueError("SatDump command has no timeout argument")
    timeout_index = command.index("--timeout") + 1
    if timeout_index >= len(command):
        raise ValueError("SatDump timeout argument has no value")
    command[timeout_index] = str(remaining)
    data["command"] = command
    data["timeout_seconds"] = remaining
    return data


def print_record_preview():
    data = build_record_command()

    print("SatDump record preview")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return

    if not data["allowed"]:
        print("Opname niet toegestaan.")
        print()
        print(data["reason"])
        return

    _print_record_data(data)


def simulate_record():
    data = build_record_command()

    print("SatDump simulation")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        return

    if not data["allowed"]:
        print("Simulatie niet toegestaan.")
        print()
        print(data["reason"])
        return

    data["output_path"].mkdir(parents=True, exist_ok=True)

    print("Checks")
    print("  Profile   : OK")
    print("  SDR2      : OK")
    print("  Output dir: OK")
    print()

    _print_record_data(data)


def service_is_active(service_name):
    result = subprocess.run(
        ["systemctl", "is-active", service_name],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "active"


def service_state(service_name):
    active = service_is_active(service_name)
    return {
        "service": service_name,
        "active": active,
        "state": "active" if active else "inactive",
    }


def set_service_state(action, service_name):
    return subprocess.run(
        ["sudo", "-n", "systemctl", action, service_name],
        capture_output=True,
        text=True,
    )


def wait_for_service(service_name, expected_state, timeout=15):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        active = service_is_active(service_name)
        if (expected_state == "active" and active) or (
            expected_state == "inactive" and not active
        ):
            return True

        time.sleep(0.5)

    return False


def record_now():
    data = build_record_command()

    print("SatDump recording")
    print("-----------------------------")

    if data is None:
        print("Geen geschikte passage gevonden.")
        event_bus.publish_satdump(
            "WARNING",
            "SatDump-opname geweigerd",
            "Geen geschikte passage gevonden",
        )
        return False

    if not data["allowed"]:
        print("Opname niet toegestaan.")
        print()
        print(data["reason"])
        event_bus.publish_satdump(
            "WARNING",
            "SatDump-opname geweigerd",
            data["reason"],
        )
        return False

    data["output_path"].mkdir(parents=True, exist_ok=True)

    conflict_services = get_conflicting_services(
        data["device"]["id"], exclude_role="weather"
    )
    active_context = _active_mission_context()
    mission_id = active_context.get("mission_id")
    mission_key = "record_now:" + str(
        mission_id or datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    )
    previous_profile = state.get_sdr2_state().get("profile")
    handover_started = False

    print("Preparing Weather receiver...")
    print("-----------------------------")
    print("Recorder     :", data["device"]["name"])
    print("Serial       :", data["device"]["serial"])
    print("Conflicts    :", ", ".join(conflict_services) or "geen")
    event_bus.publish_receiver(
        "INFO",
        "Weather-receiver voorbereid",
        f"{data['device']['number']} ({data['device']['serial']})",
        data={
            **build_event_context(data),
            "conflicting_services": conflict_services,
            "handover_authority": "receiver_manager",
        },
    )

    try:
        manager_status = receiver_manager.begin_handover(
            data["device"]["id"],
            mission_key=mission_key,
            mission_id=mission_id,
            reason="Record NOW Weather mission",
            services=conflict_services,
            service_state=service_state,
            service_action=set_service_state,
            wait_for_service=wait_for_service,
            previous_profile=previous_profile,
        )
        handover_started = True
        reservation = (manager_status.get("reservations") or {}).get(
            data["device"]["id"], {}
        )
        stopped = [
            item.get("service")
            for item in (reservation.get("handover") or {}).get("services") or []
            if item.get("stopped_by_sdrcc")
        ]
        print("Stopped      :", ", ".join(stopped) or "geen")

        state.set_sdr2_state(
            status="recording",
            profile="weather",
            locked=True,
            process="satdump",
        )
        receiver_manager.activate(mission_key=mission_key, mission_id=mission_id)

        print()
        print("Starting SatDump...")
        _print_record_data(data)

        event_bus.publish_satdump(
            "INFO",
            "SatDump-opname gestart",
            f"{data['pass']['name']} via {data['device']['number']}",
            data={
                **build_event_context(data),
                "command": list(data["command"]),
            },
        )

        result = subprocess.run(data["command"])
        success = result.returncode == 0

        event_bus.publish_satdump(
            "SUCCESS" if success else "ERROR",
            "SatDump-opname afgerond" if success else "SatDump-opname mislukt",
            f"Returncode {result.returncode}",
            data={
                **build_event_context(data),
                "returncode": result.returncode,
            },
        )

        print()
        print("SatDump finished")
        print("-----------------------------")
        print("Result :", "OK" if success else "FAILED")
        print("Code   :", result.returncode)

        return success

    finally:
        print()
        print("Restoring receiver services...")
        print("-----------------------------")

        if handover_started:
            restored = receiver_manager.restore_handover(
                mission_key=mission_key,
                service_state=service_state,
                service_action=set_service_state,
                wait_for_service=wait_for_service,
                detail="Record NOW receiver context restored",
            )
            if not restored.get("ok"):
                errors = "; ".join(restored.get("errors") or [])
                print("ATTENTION   :", errors)
                raise RuntimeError(
                    "Record NOW receiverherstel vereist aandacht: " + errors
                )


def _print_record_data(data):
    pass_data = data["pass"]

    print("Satellite  :", pass_data["name"])
    print("Frequency  :", f"{pass_data['frequency'] / 1e6:.3f} MHz")
    print("Mode       :", pass_data["mode"])
    print("Pipeline   :", pass_data["pipeline"])
    print("SampleRate :", pass_data["sample_rate"])
    print("Recorder   :", data["device"]["name"])
    print("Serial     :", data["device"]["serial"])
    print("Output     :", data["output_path"])

    if "timeout_seconds" in data:
        print("Timeout    :", f"{data['timeout_seconds']} seconds")

    print()
    print("Command:")
    print(" ".join(data["command"]))


def analyze_satdump_result(
    returncode,
    stdout="",
    stderr="",
    output_path=None,
    context=None,
):
    """Classificeer SatDump centraal via core.mission_result."""
    result = mission_result.classify(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        output_path=output_path,
    )

    level = "SUCCESS" if result["success"] else (
        "ERROR" if result["result"] == "FAILED" else "WARNING"
    )
    event_bus.publish_satdump(
        level,
        f"SatDump-resultaat: {result['result']}",
        result["detail"],
        data={
            **dict(context or _active_mission_context()),
            "returncode": returncode,
            "output_path": str(output_path) if output_path else None,
            **result,
        },
    )
    return result


def find_cadu_input(output_path):
    """Return the largest non-empty CADU file from a mission directory."""

    output_dir = Path(output_path)
    candidates = [
        item
        for item in output_dir.rglob("*.cadu")
        if item.is_file() and item.stat().st_size > 0
    ]
    return max(candidates, key=lambda item: item.stat().st_size) if candidates else None


def build_cadu_decode_command(output_path, pipeline):
    """Build the offline product-decoding command for a completed live capture."""

    output_dir = Path(output_path)
    cadu_file = find_cadu_input(output_dir)
    if cadu_file is None:
        return None

    products_dir = output_dir / "decoded"
    return {
        "cadu_file": cadu_file,
        "products_dir": products_dir,
        "log_file": output_dir / "satdump-decode.log",
        "command": [
            "satdump",
            str(pipeline),
            "cadu",
            str(cadu_file),
            str(products_dir),
        ],
    }


def decode_cadu_products(
    output_path,
    pipeline,
    line_callback=None,
    process_callback=None,
):
    """Decode a live-created CADU into image products and preserve the full log.

    SatDump 1.2.x may return a non-zero code after producing valid products when
    an optional enhancement or plugin fails. The caller must therefore evaluate
    the actual output inventory, not the return code alone.
    """

    data = build_cadu_decode_command(output_path, pipeline)
    if data is None:
        return {
            "attempted": False,
            "returncode": None,
            "stdout": "",
            "command": None,
            "cadu_file": None,
            "products_dir": None,
            "log_file": None,
        }

    data["products_dir"].mkdir(parents=True, exist_ok=True)
    lines = []

    with data["log_file"].open("w", encoding="utf-8") as log_handle:
        process = subprocess.Popen(
            data["command"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
        )
        if process_callback is not None:
            process_callback(process)

        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\r\n")
                lines.append(line)
                log_handle.write(line + "\n")
                log_handle.flush()
                if line_callback is not None:
                    line_callback(line)

        process.wait()
        if process_callback is not None:
            process_callback(None)

    return {
        "attempted": True,
        "returncode": process.returncode,
        "stdout": "\n".join(lines),
        "command": list(data["command"]),
        "cadu_file": str(data["cadu_file"]),
        "products_dir": str(data["products_dir"]),
        "log_file": str(data["log_file"]),
    }
