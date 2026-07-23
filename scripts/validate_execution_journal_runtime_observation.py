#!/usr/bin/env python3
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core import execution_journal, execution_plan_consumer, mission_engine


def require(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def events(execution_id):
    entry = execution_journal.get_entry(execution_id)
    require(entry is not None, "journal-entry bestaat")
    return [item["event"] for item in entry["events"]]


def main():
    execution_journal.reset_journal()
    execution_plan_consumer.reset_history()
    mission_engine._save_history = lambda history: None

    engine = mission_engine.MissionEngine()
    created = engine.create_job(satellite="METEOR-M2-4", receiver="sdr1")
    execution_id = created["execution_plan"]["execution_id"]
    require(events(execution_id) == [
        "PLAN_CREATED", "VALIDATED", "CONSUMED", "ACCEPTED"
    ], "mission acceptance lifecycle geldig")

    engine.set_state(mission_engine.MissionState.LOCK_RECEIVER)
    engine.set_state(mission_engine.MissionState.LOCK_RECEIVER)
    observed = events(execution_id)
    require(observed.count("STARTED") == 1, "STARTED wordt maximaal eenmaal geregistreerd")

    engine.finish_job(success=True, result=mission_engine.MissionResult.SUCCESS)
    require(events(execution_id)[-1] == "FINISHED", "succes wordt als FINISHED waargenomen")

    failed = engine.create_job(satellite="METEOR-M2-3", receiver="sdr1")
    failed_id = failed["execution_plan"]["execution_id"]
    engine.set_state(mission_engine.MissionState.LOCK_RECEIVER)
    engine.finish_job(success=False, result=mission_engine.MissionResult.NO_SYNC)
    require(events(failed_id)[-1] == "FAILED", "niet-succesresultaat wordt als FAILED waargenomen")

    cancelled = engine.create_job(satellite="METEOR-M2-4", receiver="sdr1")
    cancelled_id = cancelled["execution_plan"]["execution_id"]
    engine.reset(detail="validator cancellation")
    require(events(cancelled_id)[-1] == "CANCELLED", "reset met actieve missie wordt als CANCELLED waargenomen")

    snapshot = execution_journal.get_snapshot(limit=20)
    require(snapshot["authority"] == "observer_only", "journal blijft observer-only")
    require(snapshot["behavior_changed"] is False, "operationeel gedrag blijft ongewijzigd")

    source = (PROJECT_ROOT / "core" / "mission_engine.py").read_text(encoding="utf-8")
    require("append_event_once" in source, "Mission Engine gebruikt idempotente observer-hook")
    require("run_systemctl" not in source, "Mission Engine krijgt geen service-authority")

    print({
        "status": "ok",
        "journal_version": snapshot["journal_version"],
        "entry_count": snapshot["count"],
        "terminal_events": ["FINISHED", "FAILED", "CANCELLED"],
        "observer_only": True,
    })


if __name__ == "__main__":
    main()
