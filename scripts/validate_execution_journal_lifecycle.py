#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from core import execution_factory, execution_journal, execution_plan_consumer


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def main() -> None:
    execution_journal.reset_journal()
    execution_plan_consumer.reset_history()

    weather = execution_plan_consumer.consume_weather_mission({
        "satellite": "METEOR-M2-4",
        "validator_test": True,
    })
    execution_id = weather["execution_id"]
    entry = execution_journal.get_entry(execution_id)
    require(entry is not None, "consumer record correleert met journal-entry")
    events = [item["event"] for item in entry["events"]]
    require(events == ["PLAN_CREATED", "VALIDATED", "CONSUMED"],
            "weather lifecycle-volgorde geldig")
    require(entry["status"] == "CONSUMED", "laatste weather-status is CONSUMED")

    service = execution_plan_consumer.delegate_service_action("ais", "restart")
    service_entry = execution_journal.get_entry(service["execution_id"])
    service_events = [item["event"] for item in service_entry["events"]]
    require(service_events == ["PLAN_CREATED", "VALIDATED", "CONSUMED", "DELEGATED"],
            "service delegation lifecycle-volgorde geldig")
    require(service_entry["status"] == "DELEGATED", "laatste service-status is DELEGATED")
    require(service_entry["authority"] == "observer_only", "journal blijft observer-only")
    require(service_entry["behavior_changed"] is False, "operationeel gedrag blijft ongewijzigd")

    plan = execution_factory.build_plan("adsb")
    require(plan["plugin_id"] == "adsb", "bestaand build_plan-contract behouden")

    source = Path("core/execution_journal.py").read_text(encoding="utf-8")
    forbidden = ("subprocess", "systemctl", "mission_engine", "receiver_manager", "core.satdump")
    require(not any(item in source for item in forbidden),
            "journal bevat geen operationele authority call-sites")

    snapshot = execution_journal.get_snapshot(limit=20)
    print(json.dumps({
        "status": "ok",
        "journal_version": snapshot["journal_version"],
        "entry_count": snapshot["count"],
        "weather_events": events,
        "service_events": service_events,
        "observer_only": snapshot["authority"] == "observer_only",
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
