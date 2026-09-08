#!/usr/bin/env python3
"""Read-only compatibility/ownership checks; configuration is excluded from updates."""
from pathlib import Path
import hashlib,json,sys
source,project=map(Path,sys.argv[1:3])
manifest=json.loads((source/'scripts/install/update_manifest.json').read_text())
for name,allowed in manifest.items():
    if name == "scripts/install/update_manifest.json": continue
    target=project/name
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() not in allowed:
        raise SystemExit(f'FAIL: locally modified source {name}; review before updating')
state=project/'data/state/receiver_manager.json'
if state.exists():
    data=json.loads(state.read_text())
    if data.get('reservations') or data.get('reservation'):
        raise SystemExit('FAIL: active receiver reservation. Stop the mission/HF session in the dashboard and retry.')
print('PASS: source compatibility; no receiver reservation; local config excluded from update')
