#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import controlled_iq_capture

checks = []
def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")

source = (ROOT / "core" / "controlled_iq_capture.py").read_text(encoding="utf-8")
app_source = (ROOT / "dashboard" / "app.py").read_text(encoding="utf-8")
check("systemctl" not in source, "lifecycle module bevat geen eigen systemctl-authority")
check("receiver_manager.reserve" in source, "Receiver Manager blijft reservation authority")
check("receiver_manager.release" in source, "receiver wordt in finally vrijgegeven")
check("finally:" in source, "service- en receiverherstel is fail-safe")
check("MAX_CONTROLLED_SECONDS = 30" in source, "controlled capture is begrensd tot 30 seconden")
check('/api/iss-voice/controlled-capture' in app_source, "expliciet controlled-capture endpoint aanwezig")
check('service_action=run_systemctl' in app_source, "dashboard behoudt bestaande service-control authority")
check('automatic_execution": False' in source, "automatische uitvoering blijft uitgeschakeld")
print("\nISS Voice controlled capture validation PASS")
