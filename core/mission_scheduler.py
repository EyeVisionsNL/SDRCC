#!/usr/bin/env python3

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo
import json

from core import event_bus
from core import mission_preflight
from core import passes
from core.config import get_scheduler_config


LOCAL_TZ = ZoneInfo("Europe/Amsterdam")

STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

SCHEDULER_STATE_FILE = STATE_DIR / "mission_scheduler.json"

VALID_MODES = {"MANUAL", "AUTO", "PAUSED"}

DEFAULT_STATE = {
    "mode": "MANUAL",
    "observer_only": True,
    "updated": None,
}


def _now_local():
    return datetime.now(LOCAL_TZ)


def _format_local(value):
    if value is None:
        return None

    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _load_state():
    if not SCHEDULER_STATE_FILE.exists():
        return DEFAULT_STATE.copy()

    try:
        data = json.loads(
            SCHEDULER_STATE_FILE.read_text(encoding="utf-8")
        )

        state = DEFAULT_STATE.copy()
        state.update(data)
        return state

    except Exception:
        return DEFAULT_STATE.copy()


def _save_state(state):
    SCHEDULER_STATE_FILE.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


def _serialize_pass(pass_data):
    now_utc = datetime.now(timezone.utc)

    start = pass_data["start"]
    maximum = pass_data["maximum"]
    end = pass_data["end"]

    seconds_until_start = int(
        (start - now_utc).total_seconds()
    )

    duration_seconds = int(
        (end - start).total_seconds()
    )

    frequency = pass_data.get("frequency")

    return {
        "name": pass_data.get("name"),
        "start": _format_local(start),
        "maximum": _format_local(maximum),
        "end": _format_local(end),
        "start_epoch": int(start.timestamp()),
        "maximum_epoch": int(maximum.timestamp()),
        "end_epoch": int(end.timestamp()),
        "seconds_until_start": seconds_until_start,
        "duration_seconds": duration_seconds,
        "max_elevation": pass_data.get("max_elevation"),
        "azimuth": pass_data.get("azimuth"),
        "frequency": frequency,
        "frequency_mhz": (
            round(frequency / 1_000_000, 3)
            if frequency is not None
            else None
        ),
        "sample_rate": pass_data.get("sample_rate"),
        "pipeline": pass_data.get("pipeline"),
        "mode": pass_data.get("mode"),
        "decoder": pass_data.get("decoder"),
        "min_elevation": pass_data.get("min_elevation"),
    }


def _format_countdown(total_seconds):
    total_seconds = max(0, int(total_seconds))

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    if days:
        return f"T-{days}d {hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"T-{hours:02d}:{minutes:02d}:{seconds:02d}"


def _build_observer(next_pass):
    config = get_scheduler_config()

    preflight_seconds = config["preflight_seconds"]
    prepare_seconds = config["prepare_seconds"]
    lock_seconds = config["lock_seconds"]

    if next_pass is None:
        return {
            "phase": "NO MISSION",
            "detail": "Geen geschikte passage gepland",
            "countdown": None,
            "countdown_seconds": None,
            "preflight_at": None,
            "preflight_at_epoch": None,
            "prepare_at": None,
            "prepare_at_epoch": None,
            "lock_at": None,
            "lock_at_epoch": None,
            "pass_active": False,
            "config": config,
        }

    now_epoch = int(datetime.now(timezone.utc).timestamp())
    start_epoch = int(next_pass["start_epoch"])
    end_epoch = int(next_pass["end_epoch"])

    preflight_at_epoch = start_epoch - preflight_seconds
    prepare_at_epoch = start_epoch - prepare_seconds
    lock_at_epoch = start_epoch - lock_seconds
    seconds_until_start = start_epoch - now_epoch

    if now_epoch >= end_epoch:
        phase = "PASS ENDED"
        detail = "Passage is beëindigd"
        pass_active = False

    elif now_epoch >= start_epoch:
        phase = "PASS ACTIVE"
        detail = "Satellietpassage is actief"
        pass_active = True

    elif now_epoch >= lock_at_epoch:
        phase = "FINAL APPROACH"
        detail = "Receiver lock en laatste controles"
        pass_active = False

    elif now_epoch >= prepare_at_epoch:
        phase = "PREPARE RECEIVER"
        detail = "Weather-profiel activeren en ontvangers vrijgeven"
        pass_active = False

    elif now_epoch >= preflight_at_epoch:
        phase = "PREFLIGHT"
        detail = "Preflight-checks uitvoeren"
        pass_active = False

    else:
        phase = "WAIT FOR PASS"
        detail = "Wachten op volgende METEOR-passage"
        pass_active = False

    def format_epoch(epoch):
        return datetime.fromtimestamp(
            epoch,
            tz=timezone.utc,
        ).astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "phase": phase,
        "detail": detail,
        "countdown": (
            _format_countdown(seconds_until_start)
            if seconds_until_start > 0
            else "T+00:00:00"
        ),
        "countdown_seconds": seconds_until_start,
        "preflight_at": format_epoch(preflight_at_epoch),
        "preflight_at_epoch": preflight_at_epoch,
        "prepare_at": format_epoch(prepare_at_epoch),
        "prepare_at_epoch": prepare_at_epoch,
        "lock_at": format_epoch(lock_at_epoch),
        "lock_at_epoch": lock_at_epoch,
        "pass_active": pass_active,
        "config": config,
    }


class MissionScheduler:
    def __init__(self):
        self._lock = Lock()

    def set_mode(self, mode):
        mode = str(mode).upper()

        if mode not in VALID_MODES:
            raise ValueError(
                f"Onbekende scheduler-modus: {mode}"
            )

        with self._lock:
            state = _load_state()
            state["mode"] = mode
            state["updated"] = _now_local().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            _save_state(state)

        event_bus.publish_scheduler(
            "INFO",
            "Scheduler-modus gewijzigd",
            f"Scheduler staat nu op {mode}",
            data={
                "mode": mode,
                "observer_only": bool(state.get("observer_only", True)),
                "updated": state.get("updated"),
            },
        )

        return self.status()

    def status(self, queue_limit=5, hours_ahead=48):
        with self._lock:
            state = _load_state()

        upcoming = passes.get_passes(hours_ahead)
        queue = [
            _serialize_pass(item)
            for item in upcoming[:queue_limit]
        ]

        next_pass = queue[0] if queue else None
        observer = _build_observer(next_pass)

        preflight = {
            "executed": False,
            "passed": None,
            "status": "PENDING",
            "detail": "Preflight start op T-5:00",
            "checks": [],
        }

        countdown_seconds = observer.get("countdown_seconds")
        preflight_seconds = observer.get(
            "config",
            {},
        ).get("preflight_seconds", 300)

        if (
            countdown_seconds is not None
            and countdown_seconds <= preflight_seconds
            and countdown_seconds > 0
        ):
            result = mission_preflight.run_preflight()
            preflight = {
                "executed": True,
                **result,
            }

            observer["detail"] = (
                "Preflight OK"
                if result["passed"]
                else result["detail"]
            )

        if state["mode"] == "PAUSED":
            next_action = "Scheduler gepauzeerd"

        elif next_pass is None:
            next_action = "Geen passage gepland"

        elif state["mode"] == "AUTO":
            next_action = (
                "Observer: profiel Weather voorbereiden"
            )

        else:
            next_action = (
                "Observer: wachten op handmatige opdracht"
            )

        return {
            "mode": state["mode"],
            "observer_only": bool(
                state.get("observer_only", True)
            ),
            "updated": state.get("updated"),
            "queue_limit": queue_limit,
            "queue_count": len(queue),
            "queue": queue,
            "next_pass": next_pass,
            "next_action": next_action,
            "observer": observer,
            "preflight": preflight,
        }


mission_scheduler = MissionScheduler()


def get_scheduler_status(queue_limit=5, hours_ahead=48):
    return mission_scheduler.status(
        queue_limit=queue_limit,
        hours_ahead=hours_ahead,
    )


def set_scheduler_mode(mode):
    return mission_scheduler.set_mode(mode)
