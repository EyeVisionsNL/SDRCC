#!/usr/bin/env python3
"""Compatibility entry point for the v0.54.0d per-profile planning contract."""

from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).with_name("validate_pass_window_correctness_v0540d.py")),
    run_name="__main__",
)
