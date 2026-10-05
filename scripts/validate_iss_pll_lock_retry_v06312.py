#!/usr/bin/env python3
"""Hardware-free validation for ISS IQ capture PLL-lock retry handling."""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import wideband_iq_recorder  # noqa: E402


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print("PASS:", label)


class FakeRtlSdrProcess:
    def __init__(self, command, *, stderr, warning: bool, byte_count: int) -> None:
        self.returncode = None
        self.pid = id(self) & 0x7FFFFFFF
        self.iq_path = Path(command[-1])
        if warning:
            stderr.write(
                b"Found Rafael Micro R820T tuner\n"
                b"[R82XX] PLL not locked!\n"
                b"Tuned to 437550000 Hz.\n"
            )
            stderr.flush()
        self.iq_path.write_bytes(b"\x80" * byte_count)

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.returncode = -9


def run_capture(warnings: list[bool], *, retry_count: int):
    processes: list[FakeRtlSdrProcess] = []

    def fake_popen(command, *, stderr, **_kwargs):
        warning = warnings[len(processes)]
        process = FakeRtlSdrProcess(
            command,
            stderr=stderr,
            warning=warning,
            byte_count=spec.sample_count * 2,
        )
        processes.append(process)
        return process

    with TemporaryDirectory(prefix="sdrcc-pll-retry-") as temporary:
        spec = wideband_iq_recorder.CaptureSpec(
            mission_id="pll_retry_test",
            receiver_serial="TEST24006572",
            frequency_hz=437_550_000,
            sample_rate_hz=100_000,
            duration_seconds=1,
            output_directory=Path(temporary) / "capture",
            gain_db=12.5,
        )
        with patch.object(wideband_iq_recorder, "validate_runtime", return_value={"ok": True}), \
             patch.object(wideband_iq_recorder.subprocess, "Popen", side_effect=fake_popen), \
             patch.object(wideband_iq_recorder.time, "sleep", return_value=None):
            result = wideband_iq_recorder.execute_capture(
                spec,
                services_confirmed_stopped=True,
                retry_count=retry_count,
                retry_delay_seconds=0,
            )
    return result, processes


recovered, recovered_processes = run_capture([True, False], retry_count=1)
check(
    recovered["complete"]
    and recovered["attempt_count"] == 2
    and recovered["attempts"][0]["failure_reason"] == "tuner_pll_lock_not_confirmed"
    and recovered["pll_lock_warning_attempts"] == 1
    and recovered["pll_lock_recovered"],
    "capture aborts the unlocked startup and succeeds on the existing retry",
)
check(
    recovered_processes[0].returncode == -15 and recovered_processes[1].returncode == 0,
    "the failed tuner process is stopped before the retry starts",
)

still_unlocked, failed_processes = run_capture([True, True], retry_count=1)
check(
    not still_unlocked["complete"]
    and still_unlocked["failure_reason"] == "tuner_pll_lock_not_confirmed"
    and still_unlocked["attempt_count"] == 2
    and still_unlocked["pll_lock_warning_attempts"] == 2,
    "capture remains failed with a clear reason when PLL lock fails on every retry",
)
check(
    all(process.returncode == -15 for process in failed_processes),
    "each unconfirmed tuner process is stopped promptly",
)

print("VALIDATION PASS: ISS PLL lock retry handling")
