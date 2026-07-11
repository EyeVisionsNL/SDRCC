from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Optional
import json

from core import event_bus


class MissionState(str, Enum):
    READY = "READY"
    WAIT_FOR_PASS = "WAIT FOR PASS"
    LOCK_RECEIVER = "LOCK RECEIVER"
    RECORDING = "RECORDING"
    DECODING = "DECODING"
    PROCESSING = "PROCESSING"
    ARCHIVING = "ARCHIVING"


class MissionResult(str, Enum):
    SUCCESS = "SUCCESS"
    NO_SYNC = "NO SYNC"
    NO_SIGNAL = "NO SIGNAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


STATE_ORDER = [
    MissionState.READY,
    MissionState.WAIT_FOR_PASS,
    MissionState.LOCK_RECEIVER,
    MissionState.RECORDING,
    MissionState.DECODING,
    MissionState.PROCESSING,
    MissionState.ARCHIVING,
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "state"
HISTORY_FILE = STATE_DIR / "mission_history.json"
HISTORY_LIMIT = 50


def format_datetime(value: Optional[datetime]):
    if value is None:
        return None
    return value.strftime("%Y-%m-%d %H:%M:%S")


def calculate_progress(state: MissionState):
    current_index = STATE_ORDER.index(state)
    return int((current_index / (len(STATE_ORDER) - 1)) * 100)


def _load_history():
    try:
        if not HISTORY_FILE.exists():
            return []
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_history(history):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = HISTORY_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(history[:HISTORY_LIMIT], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(HISTORY_FILE)


@dataclass
class MissionJob:
    mission_id: str
    satellite: str
    frequency: Optional[int]
    mode: str
    pipeline: str
    output_path: str
    receiver: Optional[str]
    receiver_id: Optional[str]
    receiver_serial: Optional[str]
    status: str
    progress: int
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    success: Optional[bool] = None
    result: Optional[str] = None
    detail: Optional[str] = None
    error: Optional[str] = None
    duration_seconds: Optional[int] = None
    peak_snr_db: Optional[float] = None
    frames: Optional[int] = None
    cadu_bytes: Optional[int] = None
    image_count: Optional[int] = None

    def to_dict(self):
        data = asdict(self)
        data["created_at"] = format_datetime(self.created_at)
        data["started_at"] = format_datetime(self.started_at)
        data["ended_at"] = format_datetime(self.ended_at)
        data["frequency_mhz"] = (
            round(self.frequency / 1_000_000, 3)
            if self.frequency is not None
            else None
        )
        return data


class MissionEngine:
    def __init__(self):
        self.state = MissionState.READY
        self.started_at = datetime.now()
        self.updated_at = datetime.now()
        self.log = []
        self.active_job: Optional[MissionJob] = None
        self.history = _load_history()
        self._lock = Lock()
        self._log("Mission Engine initialized")

    def _now(self):
        return datetime.now()

    def _timestamp(self):
        return self._now().strftime("%Y-%m-%d %H:%M:%S")

    def _log(self, message):
        self.log.insert(0, {
            "time": self._timestamp(),
            "state": self.state.value,
            "message": message,
        })
        self.log = self.log[:100]

    def _generate_mission_id(self):
        return self._now().strftime("%Y%m%d-%H%M%S-%f")

    def create_job(
        self,
        satellite="-",
        frequency=None,
        mode="-",
        pipeline="-",
        output_path="-",
        receiver=None,
        receiver_id=None,
        receiver_serial=None,
    ):
        with self._lock:
            if self.active_job is not None:
                raise RuntimeError(
                    f"Mission {self.active_job.mission_id} is nog actief."
                )

            now = self._now()
            self.active_job = MissionJob(
                mission_id=self._generate_mission_id(),
                satellite=str(satellite or "-"),
                frequency=frequency,
                mode=str(mode or "-"),
                pipeline=str(pipeline or "-"),
                output_path=str(output_path or "-"),
                receiver=str(receiver) if receiver else None,
                receiver_id=str(receiver_id) if receiver_id else None,
                receiver_serial=(
                    str(receiver_serial) if receiver_serial else None
                ),
                status=self.state.value,
                progress=calculate_progress(self.state),
                created_at=now,
            )
            self._log(
                f"Mission Job aangemaakt: {self.active_job.mission_id} "
                f"({self.active_job.satellite})"
            )
            job = self.active_job.to_dict()

        event_bus.publish_mission(
            "INFO",
            "Mission Job aangemaakt",
            f"{job['satellite']} / {job['mission_id']}",
            data=job,
        )
        return job

    def set_state(self, new_state):
        if isinstance(new_state, str):
            new_state = MissionState(new_state)

        with self._lock:
            old_state = self.state
            self.state = new_state
            self.updated_at = self._now()

            if new_state == MissionState.LOCK_RECEIVER:
                self.started_at = self.updated_at
                if self.active_job is not None and self.active_job.started_at is None:
                    self.active_job.started_at = self.updated_at

            if self.active_job is not None:
                self.active_job.status = new_state.value
                self.active_job.progress = calculate_progress(new_state)

            self._log(f"State changed: {old_state.value} -> {new_state.value}")
            job = self.active_job.to_dict() if self.active_job else None

        if old_state != new_state:
            event_bus.publish_mission(
                "SYSTEM",
                "Mission-status gewijzigd",
                f"{old_state.value} → {new_state.value}",
                data={
                    "from": old_state.value,
                    "to": new_state.value,
                    "mission_id": job.get("mission_id") if job else None,
                    "satellite": job.get("satellite") if job else None,
                    "receiver": job.get("receiver") if job else None,
                    "receiver_id": job.get("receiver_id") if job else None,
                    "receiver_serial": (
                        job.get("receiver_serial") if job else None
                    ),
                    "frequency": job.get("frequency") if job else None,
                    "frequency_mhz": (
                        job.get("frequency_mhz") if job else None
                    ),
                    "mode": job.get("mode") if job else None,
                    "pipeline": job.get("pipeline") if job else None,
                    "output_path": job.get("output_path") if job else None,
                    "progress": calculate_progress(new_state),
                },
            )

    def next_state(self):
        index = STATE_ORDER.index(self.state)
        if self.state == MissionState.ARCHIVING:
            self.set_state(MissionState.READY)
            return
        self.set_state(STATE_ORDER[index + 1])

    def finish_job(
        self,
        success=True,
        error=None,
        result=None,
        detail=None,
        metrics=None,
    ):
        with self._lock:
            if self.active_job is None:
                return None

            if result is None:
                result = MissionResult.SUCCESS.value if success else MissionResult.FAILED.value
            elif isinstance(result, MissionResult):
                result = result.value

            now = self._now()
            self.active_job.ended_at = now
            self.active_job.success = bool(success)
            self.active_job.result = str(result)
            self.active_job.detail = str(detail) if detail else None
            self.active_job.error = str(error) if error else None
            self.active_job.status = str(result)
            self.active_job.progress = 100

            metrics = metrics or {}
            started_at = self.active_job.started_at or self.active_job.created_at
            measured_duration = max(0, int((now - started_at).total_seconds()))
            self.active_job.duration_seconds = int(
                metrics.get("duration_seconds", measured_duration)
            )
            peak_snr = metrics.get("peak_snr_db")
            self.active_job.peak_snr_db = (
                round(float(peak_snr), 2) if peak_snr is not None else None
            )
            frames = metrics.get("frames")
            self.active_job.frames = int(frames) if frames is not None else None
            cadu_bytes = metrics.get("cadu_bytes")
            self.active_job.cadu_bytes = (
                int(cadu_bytes) if cadu_bytes is not None else None
            )
            image_count = metrics.get("image_count")
            self.active_job.image_count = (
                int(image_count) if image_count is not None else None
            )

            completed_job = self.active_job.to_dict()
            self.history.insert(0, completed_job)
            self.history = self.history[:HISTORY_LIMIT]
            _save_history(self.history)

            self._log(
                f"Mission Job {self.active_job.mission_id} afgerond: {result}"
            )
            self.active_job = None

        event_bus.publish_mission(
            "SUCCESS" if success else "WARNING",
            "Mission Job afgerond",
            f"{completed_job['satellite']} - {completed_job['result']}",
            data=completed_job,
        )
        return completed_job

    def reset(self):
        cancelled_job = None
        with self._lock:
            old_state = self.state
            if self.active_job is not None:
                now = self._now()
                self.active_job.ended_at = now
                self.active_job.success = False
                self.active_job.result = MissionResult.CANCELLED.value
                self.active_job.detail = "Mission handmatig gereset"
                self.active_job.error = None
                self.active_job.status = MissionResult.CANCELLED.value
                self.active_job.progress = 100
                cancelled_job = self.active_job.to_dict()
                self.history.insert(0, cancelled_job)
                self.history = self.history[:HISTORY_LIMIT]
                _save_history(self.history)
                self.active_job = None

            self.state = MissionState.READY
            self.started_at = self._now()
            self.updated_at = self.started_at
            self._log("Mission reset to READY")

        event_bus.publish_mission(
            "WARNING" if cancelled_job else "SYSTEM",
            "Mission Engine gereset",
            (
                f"Mission {cancelled_job['mission_id']} is geannuleerd"
                if cancelled_job
                else f"{old_state.value} → READY"
            ),
            data={
                "from": old_state.value,
                "to": MissionState.READY.value,
                "cancelled_job": cancelled_job,
            },
        )

    def status(self):
        with self._lock:
            return {
                "state": self.state.value,
                "started_at": format_datetime(self.started_at),
                "updated_at": format_datetime(self.updated_at),
                "log": list(self.log),
                "states": [state.value for state in STATE_ORDER],
                "active_job": self.active_job.to_dict() if self.active_job else None,
                "history": list(self.history),
            }


mission_engine = MissionEngine()


def get_mission_status():
    status = mission_engine.status()
    current_state = mission_engine.state
    last_result = status["history"][0] if status["history"] else None
    detail = f"Mission Engine status: {status['state']}"
    if status["state"] == MissionState.READY.value and last_result:
        detail += (
            f" | Laatste missie: {last_result.get('satellite', '-')} "
            f"- {last_result.get('result', '-')}"
        )

    return {
        "phase": status["state"],
        "state": status["state"],
        "detail": detail,
        "progress": calculate_progress(current_state),
        "started_at": status["started_at"],
        "updated_at": status["updated_at"],
        "steps": [{"name": state} for state in status["states"]],
        "log": status["log"],
        "active_job": status["active_job"],
        "history": status["history"],
        "last_result": last_result,
    }


def mission_create_job(
    satellite="-",
    frequency=None,
    mode="-",
    pipeline="-",
    output_path="-",
    receiver=None,
    receiver_id=None,
    receiver_serial=None,
):
    mission_engine.create_job(
        satellite=satellite,
        frequency=frequency,
        mode=mode,
        pipeline=pipeline,
        output_path=output_path,
        receiver=receiver,
        receiver_id=receiver_id,
        receiver_serial=receiver_serial,
    )
    return get_mission_status()


def mission_finish_job(
    success=True,
    error=None,
    result=None,
    detail=None,
    metrics=None,
):
    mission_engine.finish_job(
        success=success,
        error=error,
        result=result,
        detail=detail,
        metrics=metrics,
    )
    return get_mission_status()


def mission_next_state():
    mission_engine.next_state()
    return get_mission_status()


def mission_reset():
    mission_engine.reset()
    return get_mission_status()


def mission_set_state(state):
    mission_engine.set_state(state)
    return get_mission_status()
