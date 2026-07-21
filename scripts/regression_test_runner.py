#!/usr/bin/env python3
"""SDRCC deterministic mission regression test runner.

Runs all Mission Simulator scenarios through the public SDRCC HTTP API and
validates mission cleanup, receiver cleanup and scenario-specific results.
No SDR hardware, external services or SatDump processes are touched by the
simulator.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_RECEIVER = "sdr2"
DEFAULT_DURATION = 4
DEFAULT_TIMEOUT = 30
POLL_INTERVAL = 0.5


@dataclass(frozen=True)
class Scenario:
    name: str
    expected_result: str
    expected_error: str | None = None


@dataclass
class TestResult:
    scenario: str
    passed: bool
    expected_result: str
    actual_result: str | None = None
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0


SCENARIOS = (
    Scenario("success", "SUCCESS"),
    Scenario("no_sync", "NO SYNC"),
    Scenario("satdump_returncode_1", "FAILED", "satdump returncode 1"),
    Scenario("receiver_lock_fail", "FAILED", "receiver lock failed"),
    Scenario("cancel", "CANCELLED"),
    Scenario("receiver_disconnect", "FAILED", "receiver disconnected during recording"),
    Scenario("satdump_process_crash", "FAILED", "satdump process crashed"),
    Scenario("decoder_timeout", "FAILED", "decoder timeout"),
    Scenario("disk_full", "FAILED", "disk full"),
    Scenario("output_not_writable", "FAILED", "output directory not writable"),
    Scenario("api_timeout", "FAILED", "control api timeout"),
)


def request_json(base_url: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        base_url.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} voor {path}: {body or error.reason}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"API niet bereikbaar voor {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Ongeldige JSON ontvangen van {path}: {error}") from error


def add_check(result: TestResult, name: str, passed: bool, detail: str) -> None:
    result.checks.append((name, passed, detail))
    if not passed:
        result.passed = False


def validate_idle(status: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    simulator = status.get("simulator") or {}
    mission = status.get("mission") or {}
    receiver_manager = status.get("receiver_manager") or {}

    if simulator.get("active"):
        problems.append("Mission Simulator is actief")
    if mission.get("active_job") is not None:
        problems.append("Mission Engine heeft een actieve job")
    if mission.get("state") != "READY" or mission.get("phase") != "READY":
        problems.append(
            f"Mission Engine is niet READY (state={mission.get('state')}, phase={mission.get('phase')})"
        )
    if receiver_manager.get("reservations"):
        problems.append(f"Er bestaan receiver-reserveringen: {receiver_manager.get('reservations')}")
    return problems


def run_scenario(
    base_url: str,
    scenario: Scenario,
    receiver_id: str,
    duration_seconds: int,
    timeout_seconds: int,
) -> TestResult:
    started = time.monotonic()
    result = TestResult(
        scenario=scenario.name,
        passed=True,
        expected_result=scenario.expected_result,
    )

    try:
        before = request_json(base_url, "/api/mission-simulator")
        idle_problems = validate_idle(before)
        add_check(
            result,
            "preflight_idle",
            not idle_problems,
            "OK" if not idle_problems else "; ".join(idle_problems),
        )
        if idle_problems:
            result.error = "Preflight geweigerd: SDRCC is niet idle"
            return result

        start_response = request_json(
            base_url,
            "/api/mission-simulator/start",
            {
                "scenario": scenario.name,
                "receiver_id": receiver_id,
                "duration_seconds": duration_seconds,
            },
        )
        add_check(
            result,
            "start_api",
            bool(start_response.get("ok")),
            f"ok={start_response.get('ok')}",
        )
        if not start_response.get("ok"):
            result.error = start_response.get("error") or "Scenario kon niet worden gestart"
            return result

        deadline = time.monotonic() + timeout_seconds
        status = start_response
        while (status.get("simulator") or {}).get("active"):
            if time.monotonic() >= deadline:
                try:
                    request_json(base_url, "/api/mission-simulator/stop", {})
                except Exception:
                    pass
                result.passed = False
                result.error = f"Timeout na {timeout_seconds} seconden"
                return result
            time.sleep(POLL_INTERVAL)
            status = request_json(base_url, "/api/mission-simulator")

        simulator = status.get("simulator") or {}
        mission = status.get("mission") or {}
        receiver_manager = status.get("receiver_manager") or {}
        last = mission.get("last_result") or {}

        actual_result = simulator.get("last_result") or last.get("result")
        result.actual_result = actual_result

        add_check(
            result,
            "scenario_result",
            actual_result == scenario.expected_result,
            f"expected={scenario.expected_result}, actual={actual_result}",
        )
        add_check(
            result,
            "mission_history_result",
            last.get("result") == scenario.expected_result and last.get("status") == scenario.expected_result,
            f"result={last.get('result')}, status={last.get('status')}",
        )
        add_check(
            result,
            "mission_ready",
            mission.get("state") == "READY" and mission.get("phase") == "READY",
            f"state={mission.get('state')}, phase={mission.get('phase')}",
        )
        add_check(
            result,
            "active_job_cleanup",
            mission.get("active_job") is None,
            f"active_job={mission.get('active_job')}",
        )
        reservations = receiver_manager.get("reservations") or {}
        add_check(
            result,
            "receiver_cleanup",
            reservations == {},
            f"reservations={reservations}",
        )
        available = receiver_manager.get("available_receivers") or []
        add_check(
            result,
            "receiver_available",
            receiver_id in available,
            f"available_receivers={available}",
        )
        add_check(
            result,
            "simulator_inactive",
            simulator.get("active") is False,
            f"active={simulator.get('active')}",
        )
        add_check(
            result,
            "correct_scenario",
            simulator.get("scenario") == scenario.name,
            f"scenario={simulator.get('scenario')}",
        )

        if scenario.expected_error is not None:
            last_error = simulator.get("last_error") or last.get("error")
            add_check(
                result,
                "expected_error",
                last_error == scenario.expected_error,
                f"expected={scenario.expected_error}, actual={last_error}",
            )
            add_check(
                result,
                "fault_stage_recorded",
                bool(simulator.get("last_fault_stage")),
                f"last_fault_stage={simulator.get('last_fault_stage')}",
            )
        else:
            add_check(
                result,
                "unexpected_error",
                not simulator.get("last_error"),
                f"last_error={simulator.get('last_error')}",
            )

    except Exception as error:
        result.passed = False
        result.error = str(error)
    finally:
        result.elapsed_seconds = time.monotonic() - started

    return result


def print_result(index: int, total: int, result: TestResult, verbose: bool) -> None:
    label = result.scenario.upper()
    state = "PASS" if result.passed else "FAIL"
    print(f"[{index}/{total}] {label:<25} {state:<4}  ({result.elapsed_seconds:.1f}s)")
    if verbose or not result.passed:
        for name, passed, detail in result.checks:
            marker = "PASS" if passed else "FAIL"
            print(f"      {name:<24} {marker:<4}  {detail}")
        if result.error:
            print(f"      error                    {result.error}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run all SDRCC Mission Simulator regression scenarios")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--receiver", choices=("sdr1", "sdr2"), default=DEFAULT_RECEIVER)
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--scenario", choices=[item.name for item in SCENARIOS])
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not 3 <= args.duration <= 300:
        parser.error("--duration moet tussen 3 en 300 liggen")
    if args.timeout < args.duration + 5:
        parser.error("--timeout moet minimaal --duration + 5 seconden zijn")

    selected = [item for item in SCENARIOS if not args.scenario or item.name == args.scenario]

    print("=" * 62)
    print("SDRCC Regression Test Runner v0.32.0a")
    print("=" * 62)
    print(f"API       : {args.base_url}")
    print(f"Receiver  : {args.receiver}")
    print(f"Duration  : {args.duration}s")
    print(f"Scenarios : {len(selected)}")
    print("-" * 62)

    try:
        initial = request_json(args.base_url, "/api/mission-simulator")
    except Exception as error:
        print(f"API PREFLIGHT              FAIL")
        print(f"  {error}")
        return 1

    available_scenarios = set(initial.get("scenarios") or [])
    missing = [item.name for item in selected if item.name not in available_scenarios]
    if missing:
        print("API PREFLIGHT              FAIL")
        print(f"  Simulator mist scenario(s): {', '.join(missing)}")
        return 1

    idle_problems = validate_idle(initial)
    if idle_problems:
        print("IDLE PREFLIGHT             FAIL")
        for problem in idle_problems:
            print(f"  - {problem}")
        return 1

    results: list[TestResult] = []
    for index, scenario in enumerate(selected, start=1):
        result = run_scenario(
            args.base_url,
            scenario,
            args.receiver,
            args.duration,
            args.timeout,
        )
        results.append(result)
        print_result(index, len(selected), result, args.verbose)
        if not result.passed:
            print("      Volgende scenario's worden niet gestart om de installatie veilig te houden.")
            break

    passed = sum(1 for item in results if item.passed)
    failed = len(results) - passed
    skipped = len(selected) - len(results)

    print("-" * 62)
    print(f"Passed : {passed}")
    print(f"Failed : {failed}")
    print(f"Skipped: {skipped}")
    print("=" * 62)

    if failed == 0 and skipped == 0:
        print("ALL TESTS PASSED")
        return 0

    print("REGRESSION TESTS FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
