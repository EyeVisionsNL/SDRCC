#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import execution_journal


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


execution_journal.reset_journal()
base_plan = {
    "plugin_id": "weather",
    "adapter_type": "satdump",
    "executor_type": "satdump",
    "read_only": True,
    "executable": False,
}
first = execution_journal.create_entry(base_plan)
execution_journal.append_event(first["execution_id"], "VALIDATED", source="validator")
execution_journal.append_event(first["execution_id"], "CONSUMED", source="validator")
execution_journal.append_event(first["execution_id"], "ACCEPTED", source="validator")
execution_journal.append_event(first["execution_id"], "STARTED", source="validator")
execution_journal.append_event(first["execution_id"], "FINISHED", source="validator")

second_plan = dict(base_plan, plugin_id="ais", adapter_type="service", executor_type="service")
second = execution_journal.create_entry(second_plan)
execution_journal.append_event(second["execution_id"], "FAILED", source="validator")

snapshot = execution_journal.get_snapshot(limit=1, offset=0)
check(snapshot["journal_version"] == "0.43.0c4", "Journal-versie is v0.43.0c4")
check(snapshot["count"] == 1 and snapshot["filtered_count"] == 2, "limit en filtered_count zijn gescheiden")
check(snapshot["has_more"] is True, "paginering meldt vervolgresultaten")
check(snapshot["summary"]["finished"] == 1, "FINISHED-statistiek geldig")
check(snapshot["summary"]["failed"] == 1, "FAILED-statistiek geldig")
check(snapshot["summary"]["active"] == 0, "actieve statistiek geldig")

by_id = execution_journal.get_snapshot(execution_id=first["execution_id"])
check(by_id["filtered_count"] == 1, "execution_id-filter geldig")
check(by_id["entries"][0]["status"] == "FINISHED", "execution_id-filter retourneert juiste entry")

by_plugin = execution_journal.get_snapshot(plugin_id="ais")
check(by_plugin["filtered_count"] == 1, "pluginfilter geldig")
by_status = execution_journal.get_snapshot(status="FAILED")
check(by_status["filtered_count"] == 1, "statusfilter geldig")

html = (ROOT / "dashboard/templates/index.html").read_text()
js = (ROOT / "dashboard/static/js/execution_journal.js").read_text()
css = (ROOT / "dashboard/static/css/execution_journal.css").read_text()
check('id="execution-journal-list"' in html, "Mission Operations bevat Journal-paneel")
check("/api/execution-journal?limit=12&offset=0" in js, "Journal UI gebruikt read-only API")
check("fetch(" in js and "method:" not in js, "Journal UI bevat geen write request")
check("execution-journal-panel-v043" in css, "Journal-styling aanwezig")

print(json.dumps({
    "status": "ok",
    "journal_version": snapshot["journal_version"],
    "filtered_count": snapshot["filtered_count"],
    "summary": snapshot["summary"],
    "read_only": snapshot["read_only"],
    "authority": snapshot["authority"],
}, indent=2))
