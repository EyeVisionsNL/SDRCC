#!/usr/bin/env python3
"""Validate the observer-only multi-source Logs viewer for SDRCC v0.54.0t."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import os
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import log_sources  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate_static_contract() -> None:
    template = read("dashboard/templates/index.html")
    stylesheet = read("dashboard/static/css/log.css")
    frontend = read("dashboard/static/js/logs.js")
    dashboard = read("dashboard/static/js/dashboard.js")
    dashboard_loader = read("dashboard/static/dashboard.js")
    api_javascript = read("dashboard/static/js/api.js")
    app_source = read("dashboard/app.py")
    backend = read("core/log_sources.py")

    ids = re.findall(r'\bid="([^"]+)"', template)
    duplicates = sorted(name for name, count in Counter(ids).items() if count > 1)
    check(not duplicates, f"dashboard element IDs remain unique ({duplicates or 'none'})")

    for element_id in (
        "tab-logs",
        "log-live-state",
        "log-search",
        "log-refresh",
        "log-count",
        "log-updated",
        "live-log",
    ):
        check(f'id="{element_id}"' in template, f"Logs UI hook is present: {element_id}")

    check(
        template.count('data-log-source="sdrcc"') == 1
        and template.count('data-log-source="ais"') == 1
        and template.count('data-log-source="adsb"') == 1,
        "exactly three separate log sources are presented",
    )
    check("ais-catcher-control.service" not in backend, "maintenance Control journal is not a normal log source")
    check(
        '"ais-catcher.service"' in backend
        and '"readsb.service"' in backend
        and '"sdrcc": {' in backend,
        "SDRCC, AIS and ADS-B retain their existing authoritative sources",
    )
    check("systemctl" not in backend and "sudo" not in backend, "log backend has no service-control authority")
    check(
        '@app.route("/api/logs")' in app_source
        and "log_sources.read_source(" in app_source
        and 'request.args.get("source", "sdrcc")' in app_source,
        "fixed read-only log projection is exposed through one endpoint",
    )
    check(
        'request.args.get("include_logs", "1")' in app_source
        and 'fetch("/api/status?include_logs=0"' in api_javascript,
        "legacy status payload remains compatible while dashboard polling skips closed-tab logs",
    )
    check(
        "logsTabIsActive()" in frontend
        and "document.hidden" in frontend
        and "window.setInterval(refreshLogs, LOG_REFRESH_MS)" in frontend
        and "window.clearInterval(refreshTimer)" in frontend,
        "automatic refresh runs only while Logs is visible",
    )
    check(
        "latestLines.filter" in frontend
        and "toLocaleLowerCase().includes(query)" in frontend
        and "output.textContent" in frontend,
        "search is client-side and log text is rendered without HTML injection",
    )
    check(
        'import {setupLogs} from "./logs.js?v=0.54.0t-r1";' in dashboard
        and "setupLogs();" in dashboard
        and "updateLiveLog" not in dashboard,
        "Logs owns its refresh lifecycle independently from global status polling",
    )
    check(
        '/static/css/log.css?v=0.54.0t-r1' in template
        and '/static/dashboard.js?v=0.54.0t-r1' in template
        and '/static/js/dashboard.js?v=0.54.0t-r1' in dashboard_loader,
        "complete Logs asset chain is cache-busted",
    )
    for selector in (
        ".log-workspace",
        ".log-source-switcher",
        '.log-source-button[data-log-source="ais"].active',
        '.log-source-button[data-log-source="adsb"].active',
        ".log-search-field input:focus",
        "#live-log",
    ):
        check(selector in stylesheet, f"Logs presentation selector is defined: {selector}")


def validate_backend_contract() -> None:
    check(
        log_sources.available_sources() == [
            {"id": "sdrcc", "label": "FlexGround SDR"},
            {"id": "ais", "label": "AIS"},
            {"id": "adsb", "label": "ADS-B"},
        ],
        "public source catalog is fixed and ordered",
    )

    original_run = log_sources.subprocess.run
    journal_calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        journal_calls.append(list(command))
        unit = command[command.index("-u") + 1]
        return SimpleNamespace(
            returncode=0,
            stdout=f"2026-08-09 service line from {unit}\n",
            stderr="",
        )

    log_sources.subprocess.run = fake_run
    try:
        unknown = log_sources.read_source("not-a-service", 240)
        check(not unknown["ok"] and not journal_calls, "unknown sources are rejected before command execution")

        ais = log_sources.read_source("ais", 9999)
        adsb = log_sources.read_source("adsb", 1)
        check(ais["ok"] and adsb["ok"], "both receiver journals are readable through the projection")
        check(ais["limit"] == 500 and adsb["limit"] == 20, "requested line count is clamped safely")
        check(
            journal_calls[0] == [
                "journalctl",
                "-u",
                "ais-catcher.service",
                "-n",
                "500",
                "--no-pager",
                "-o",
                "short-iso",
            ]
            and journal_calls[1][2] == "readsb.service",
            "journalctl receives only allowlisted unit names and fixed arguments",
        )
    finally:
        log_sources.subprocess.run = original_run

    original_path = log_sources.SOURCE_DEFINITIONS["sdrcc"]["path"]
    try:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "sdrcc.log"
            path.write_text("\n".join(f"line {index}" for index in range(30)) + "\n", encoding="utf-8")
            log_sources.SOURCE_DEFINITIONS["sdrcc"]["path"] = path
            payload = log_sources.read_source("sdrcc", 20)
            check(
                payload["ok"]
                and payload["count"] == 20
                and payload["lines"][0] == "line 10"
                and payload["lines"][-1] == "line 29",
                "SDRCC source returns the requested newest lines in chronological order",
            )
    finally:
        log_sources.SOURCE_DEFINITIONS["sdrcc"]["path"] = original_path


def main() -> None:
    validate_static_contract()
    validate_backend_contract()
    check(os.environ.get("FAKE_LOGS_FAIL") != "1", "injected Logs failure is absent")
    print("PASS: v0.54.0t Multi-source Logs Viewer validation complete")


if __name__ == "__main__":
    main()
