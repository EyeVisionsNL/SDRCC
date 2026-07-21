#!/usr/bin/env python3
"""CLI client for the SDRCC Mission Simulator API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "http://127.0.0.1:8080"


def request_json(path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic SDRCC mission simulation")
    parser.add_argument("--scenario", default="success", choices=[
        "success", "no_sync", "satdump_returncode_1", "receiver_lock_fail", "cancel"
    ])
    parser.add_argument("--receiver", default="sdr2", choices=["sdr1", "sdr2"])
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    try:
        result = request_json("/api/mission-simulator/start", {
            "scenario": args.scenario,
            "receiver_id": args.receiver,
            "duration_seconds": args.duration,
        })
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.no_wait or not result.get("ok", False):
            return 0 if result.get("ok", False) else 1

        while True:
            time.sleep(1)
            status = request_json("/api/mission-simulator")
            simulator = status.get("simulator") or {}
            print(
                f"active={simulator.get('active')} "
                f"scenario={simulator.get('scenario')} "
                f"result={simulator.get('last_result')}"
            )
            if not simulator.get("active"):
                print(json.dumps(status, indent=2, ensure_ascii=False))
                return 0 if simulator.get("last_result") in {"SUCCESS", "NO SYNC", "CANCELLED", "FAILED"} else 1
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Simulator API-fout: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
