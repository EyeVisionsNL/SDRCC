#!/usr/bin/env python3
from pathlib import Path
import py_compile
import sys

root = Path(__file__).resolve().parent.parent
for rel in ("dashboard/app.py", "core/iss_voice_executor.py"):
    try:
        py_compile.compile(str(root / rel), doraise=True)
    except Exception as exc:
        print(f"FAIL syntax {rel}: {exc}")
        sys.exit(1)

app = (root / "dashboard/app.py").read_text(encoding="utf-8")
executor = (root / "core/iss_voice_executor.py").read_text(encoding="utf-8")
required_app = (
    "run_iss_voice_preflight",
    "prepare_iss_voice_receiver",
    "lock_iss_voice_receiver",
    "ISS Voice preflight passed",
    "mission_key=autopilot_runtime.get(\"pass_key\")",
    "and autopilot_runtime[\"locked\"]",
)
for token in required_app:
    if token not in app:
        print(f"FAIL app token: {token}")
        sys.exit(1)
if "mission_key: str | None = None" not in executor:
    print("FAIL executor mission_key handoff")
    sys.exit(1)
if 'mission_key = str(mission_key or f"iss_voice:{mission_id}")' not in executor:
    print("FAIL executor reservation reuse")
    sys.exit(1)
print("VALIDATION PASS: v0.48.0a-r2 Unified Mission Preflight")
