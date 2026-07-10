from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Optional


class MissionState(str, Enum):
    READY = "READY"
    WAIT_FOR_PASS = "WAIT FOR PASS"
    LOCK_RECEIVER = "LOCK RECEIVER"
    RECORDING = "RECORDING"
    DECODING = "DECODING"
    PROCESSING = "PROCESSING"
    ARCHIVING = "ARCHIVING"


STATE_ORDER = [
    MissionState.READY,
    MissionState.WAIT_FOR_PASS,
    MissionState.LOCK_RECEIVER,
    MissionState.RECORDING,
    MissionState.DECODING,
    MissionState.PROCESSING,
    MissionState.ARCHIVING,
]


def format_datetime(value: Optional[datetime]):
    if value is None:
        return None

    return value.strftime("%Y-%m-%d %H:%M:%S")


def calculate_progress(state: MissionState):
    current_index = STATE_ORDER.index(state)
    return int((current_index / (len(STATE_ORDER) - 1)) * 100)


@dataclass
class MissionJob:
    mission_id: str
    satellite: str
    frequency: Optional[int]
    mode: str
    pipeline: str
    output_path: str
    status: str
    progress: int
    created_at: datetime
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    success: Optional[bool] = None
    error: Optional[str] = None

    def to_dict(self):
        data = asdict(self)

        data["created_at"] = format_datetime(self.created_at)
        data["started_at"] = format_datetime(self.started_at)
        data["ended_at"] = format_datetime(self.ended_at)

        if self.frequency is not None:
            data["frequency_mhz"] = round(self.frequency / 1_000_000, 3)
        else:
            data["frequency_mhz"] = None

        return data


class MissionEngine:
    def __init__(self):
        self.state = MissionState.READY
        self.started_at = datetime.now()
        self.updated_at = datetime.now()

        self.log = []
        self.active_job: Optional[MissionJob] = None
        self.history = []

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
                status=self.state.value,
                progress=calculate_progress(self.state),
                created_at=now,
            )

            self._log(
                f"Mission Job aangemaakt: {self.active_job.mission_id} "
                f"({self.active_job.satellite})"
            )

            return self.active_job.to_dict()

    def set_state(self, new_state):
        if isinstance(new_state, str):
            new_state = MissionState(new_state)

        with self._lock:
            old_state = self.state
            self.state = new_state
            self.updated_at = self._now()

            if new_state == MissionState.LOCK_RECEIVER:
                self.started_at = self.updated_at

                if (
                    self.active_job is not None
                    and self.active_job.started_at is None
                ):
                    self.active_job.started_at = self.updated_at

            if self.active_job is not None:
                self.active_job.status = new_state.value
                self.active_job.progress = calculate_progress(new_state)

            self._log(
                f"State changed: {old_state.value} -> {new_state.value}"
            )

    def next_state(self):
        index = STATE_ORDER.index(self.state)

        if self.state == MissionState.ARCHIVING:
            self.set_state(MissionState.READY)
            return

        self.set_state(STATE_ORDER[index + 1])

    def finish_job(self, success=True, error=None):
        with self._lock:
            if self.active_job is None:
                return None

            now = self._now()

            self.active_job.ended_at = now
            self.active_job.success = bool(success)
            self.active_job.error = str(error) if error else None
            self.active_job.status = (
                "COMPLETED" if success else "FAILED"
            )
            self.active_job.progress = 100 if success else self.active_job.progress

            completed_job = self.active_job.to_dict()

            self.history.insert(0, completed_job)
            self.history = self.history[:50]

            result_text = "succesvol" if success else "met fout"
            self._log(
                f"Mission Job {self.active_job.mission_id} "
                f"afgerond {result_text}"
            )

            self.active_job = None

            return completed_job

    def reset(self):
        with self._lock:
            if self.active_job is not None:
                now = self._now()

                self.active_job.ended_at = now
                self.active_job.success = False
                self.active_job.error = "Mission handmatig gereset"
                self.active_job.status = "RESET"

                self.history.insert(0, self.active_job.to_dict())
                self.history = self.history[:50]
                self.active_job = None

            self.state = MissionState.READY
            self.started_at = self._now()
            self.updated_at = self.started_at
            self._log("Mission reset to READY")

    def status(self):
        with self._lock:
            return {
                "state": self.state.value,
                "started_at": format_datetime(self.started_at),
                "updated_at": format_datetime(self.updated_at),
                "log": list(self.log),
                "states": [state.value for state in STATE_ORDER],
                "active_job": (
                    self.active_job.to_dict()
                    if self.active_job is not None
                    else None
                ),
                "history": list(self.history),
            }


mission_engine = MissionEngine()


def get_mission_status():
    status = mission_engine.status()
    current_state = mission_engine.state
    progress = calculate_progress(current_state)

    return {
        "phase": status["state"],
        "state": status["state"],
        "detail": f"Mission Engine status: {status['state']}",
        "progress": progress,
        "started_at": status["started_at"],
        "updated_at": status["updated_at"],
        "steps": [
            {"name": state}
            for state in status["states"]
        ],
        "log": status["log"],
        "active_job": status["active_job"],
        "history": status["history"],
    }


def mission_create_job(
    satellite="-",
    frequency=None,
    mode="-",
    pipeline="-",
    output_path="-",
):
    mission_engine.create_job(
        satellite=satellite,
        frequency=frequency,
        mode=mode,
        pipeline=pipeline,
        output_path=output_path,
    )

    return get_mission_status()


def mission_finish_job(success=True, error=None):
    mission_engine.finish_job(
        success=success,
        error=error,
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
