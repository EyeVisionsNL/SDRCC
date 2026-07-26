#!/usr/bin/env python3
from pathlib import Path
import py_compile, sys, yaml
root=Path(__file__).resolve().parent.parent
checks=[]
for rel in ["core/iss_voice_executor.py","core/mission_recordings.py","core/receiver_contexts.py","dashboard/app.py"]:
    try: py_compile.compile(str(root/rel), doraise=True); checks.append((rel,True))
    except Exception as e: print("FAIL",rel,e); sys.exit(1)
cfg=yaml.safe_load((root/"config/iss_voice.yaml").read_text())["iss_voice"]
for key in ("execution_enabled","receiver_claim_enabled","planner_enabled"):
    if not cfg.get(key): print("FAIL config",key); sys.exit(1)
html=(root/"dashboard/templates/index.html").read_text()
for token in ("Mission Recordings","mission-recordings-audio","mission-recordings-list"):
    if token not in html: print("FAIL UI",token); sys.exit(1)
app=(root/"dashboard/app.py").read_text()
for token in ("/api/mission-recordings","iss_voice_executor.execute_pass","mission_type"):
    if token not in app: print("FAIL app",token); sys.exit(1)
print("VALIDATION PASS: v0.48.0a Flexible Mission Execution & Mission Recordings")
