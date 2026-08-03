#!/usr/bin/env python3
"""Deterministic offline validation for v0.54.0c Mission History Integrity.

All behavioural tests use a temporary state directory. The validator never
changes the live Mission History, recordings, receiver state or services.
"""

from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def configure_history_paths(state_directory: Path) -> None:
    from core import mission_history

    mission_history.STATE_DIR = state_directory
    mission_history.HISTORY_FILE = state_directory / "mission_history.json"
    mission_history.LOCK_FILE = state_directory / "mission_history.lock"
    mission_history.RECORDINGS_DIR = state_directory / "recordings"


def concurrent_writer(state_directory: str, index: int) -> None:
    configure_history_paths(Path(state_directory))
    from core import mission_history

    mission_history.record_mission({
        "mission_id": f"concurrent_{index:03d}",
        "mission_type": "weather" if index % 2 == 0 else "iss_voice",
        "satellite": "METEOR-M2 4" if index % 2 == 0 else "ISS (ZARYA)",
        "result": "SUCCESS",
        "success": True,
        "detail": f"concurrent writer {index}",
    })


def main() -> None:
    from core import mission_history, mission_recordings, mission_result

    original_paths = {
        "state": mission_history.STATE_DIR,
        "history": mission_history.HISTORY_FILE,
        "lock": mission_history.LOCK_FILE,
        "recordings": mission_history.RECORDINGS_DIR,
        "inventory": mission_recordings.ROOT,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="sdrcc-v0540c-") as temporary:
            state_directory = Path(temporary) / "state"
            configure_history_paths(state_directory)

            weather = {
                "mission_id": "weather_existing",
                "mission_type": "weather",
                "satellite": "METEOR-M2 3",
                "result": "NO SYNC",
                "success": False,
                "detail": "stored weather result",
            }
            iss = {
                "mission_id": "iss_existing",
                "mission_type": "iss_voice",
                "plugin_id": "iss_voice",
                "satellite": "ISS (ZARYA)",
                "pipeline": "wideband_iq_offline_fm",
                "result": "SUCCESS",
                "success": True,
                "detail": "ISS Voice WAV recording created",
                "audio_content_assessment": "UNASSESSED",
                "image_count": 0,
            }
            mission_history.record_mission(weather)
            mission_history.record_mission(iss)

            loaded = mission_history.load_history()
            check("stored ISS result remains SUCCESS", loaded[0]["result"] == "SUCCESS")
            check("stored Weather result remains NO SYNC", loaded[1]["result"] == "NO SYNC")
            check(
                "history reader adds no reclassification fields",
                all(
                    "stored_result" not in item and "result_reclassified" not in item
                    for item in loaded
                ),
            )
            check(
                "compatibility normalizer preserves producer result",
                mission_result.normalize_history_mission(iss) == iss,
            )

            processes = []
            context = multiprocessing.get_context("spawn")
            for index in range(16):
                process = context.Process(
                    target=concurrent_writer,
                    args=(str(state_directory), index),
                )
                process.start()
                processes.append(process)
            for process in processes:
                process.join(20)
            check(
                "all concurrent writers exit cleanly",
                all(process.exitcode == 0 for process in processes),
            )

            concurrent_history = mission_history.load_history()
            concurrent_ids = {
                item.get("mission_id") for item in concurrent_history
                if str(item.get("mission_id") or "").startswith("concurrent_")
            }
            check("all concurrent records are retained", len(concurrent_ids) == 16)
            check(
                "pre-existing Weather and ISS records survive concurrency",
                {"weather_existing", "iss_existing"}.issubset(
                    {item.get("mission_id") for item in concurrent_history}
                ),
            )

            before_retry_count = len(concurrent_history)
            retry = dict(iss)
            retry["detail"] = "idempotent retry"
            mission_history.record_mission(retry)
            after_retry = mission_history.load_history()
            check("retry does not duplicate mission-ID", len(after_retry) == before_retry_count)
            check("retry replaces the matching record", after_retry[0]["detail"] == "idempotent retry")

            valid_bytes = mission_history.HISTORY_FILE.read_bytes()
            mission_history.HISTORY_FILE.write_text("{broken json\n", encoding="utf-8")
            corrupt_before = mission_history.HISTORY_FILE.read_bytes()
            try:
                mission_history.record_mission({
                    "mission_id": "must_not_overwrite_corrupt_history",
                    "result": "SUCCESS",
                })
            except mission_history.MissionHistoryError:
                corruption_rejected = True
            else:
                corruption_rejected = False
            check("corrupt History rejects a new write", corruption_rejected)
            check(
                "corrupt History bytes are not overwritten",
                mission_history.HISTORY_FILE.read_bytes() == corrupt_before,
            )
            mission_history.HISTORY_FILE.write_bytes(valid_bytes)

            before_delete = {
                item["mission_id"]: dict(item)
                for item in mission_history.load_history()
            }
            mission_history.delete_mission("concurrent_000")
            after_delete = {
                item["mission_id"]: dict(item)
                for item in mission_history.load_history()
            }
            check("delete removes exactly one record", "concurrent_000" not in after_delete)
            check(
                "delete preserves all remaining records byte-for-byte as objects",
                all(after_delete[key] == value for key, value in before_delete.items() if key != "concurrent_000"),
            )

            real_load_history = mission_history.load_history
            load_calls = []

            def counted_load_history():
                load_calls.append(True)
                return real_load_history()

            mission_history.load_history = counted_load_history
            try:
                payload = mission_history.get_history_payload(limit=500)
            finally:
                mission_history.load_history = real_load_history
            check("History payload uses one storage snapshot", len(load_calls) == 1)
            check("ISS technical success is counted as SUCCESS", payload["statistics"]["success"] >= 1)
            iss_filtered = mission_history.get_missions(result="SUCCESS", satellite="ISS")
            check("ISS success survives result and satellite filters", any(
                item.get("mission_id") == "iss_existing" for item in iss_filtered
            ))

            mission_recordings.ROOT = Path(temporary) / "recordings"
            recordings = mission_recordings.inventory(limit="500")
            check("Mission Recordings accepts a string limit", recordings["ok"] is True)

    finally:
        mission_history.STATE_DIR = original_paths["state"]
        mission_history.HISTORY_FILE = original_paths["history"]
        mission_history.LOCK_FILE = original_paths["lock"]
        mission_history.RECORDINGS_DIR = original_paths["recordings"]
        mission_recordings.ROOT = original_paths["inventory"]

    engine_source = (ROOT / "core" / "mission_engine.py").read_text(encoding="utf-8")
    iss_source = (ROOT / "core" / "iss_voice_executor.py").read_text(encoding="utf-8")
    history_source = (ROOT / "core" / "mission_history.py").read_text(encoding="utf-8")
    operations_source = (ROOT / "core" / "mission_operations.py").read_text(encoding="utf-8")
    app_source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
    history_js = (ROOT / "dashboard" / "static" / "js" / "history.js").read_text(encoding="utf-8")
    history_css = (ROOT / "dashboard" / "static" / "css" / "history.css").read_text(encoding="utf-8")

    check("Mission Engine has no History cache", "self.history" not in engine_source)
    check("Mission Engine delegates one record to History", "mission_history.record_mission(mission)" in engine_source)
    check("ISS Voice delegates one record to History", "mission_history.record_mission(history)" in iss_source)
    check("ISS Voice has no direct History file writer", "HISTORY_FILE" not in iss_source and "os.replace" not in iss_source)
    check("central writer owns exclusive lock", "fcntl.LOCK_EX" in history_source)
    check("central writer uses atomic replace", "os.replace(temporary, HISTORY_FILE)" in history_source)
    check("Mission Operations does not reclassify History", "normalize_history_mission" not in operations_source)
    check("dashboard does not reclassify History", "normalize_history_mission" not in app_source)
    check("ISS quality marks LRPT fields not applicable", '"decoder_applicable": False' in app_source)
    check("History UI renders not-applicable quality fields", "decoderApplicable" in history_js)
    check("History UI styles not-applicable quality fields", ".history-quality-mark.not-applicable" in history_css)

    print("\nv0.54.0c Mission History Integrity validation PASS")


if __name__ == "__main__":
    main()
