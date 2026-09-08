#!/usr/bin/env python3
"""Restore source from an update backup; retain current station/hardware settings."""
from pathlib import Path
import json,os,shutil,subprocess,sys
project=Path(sys.argv[1]).resolve();backup=Path(sys.argv[2]).resolve()
if backup.parent != project/'.rollback' or not (backup/'files/VERSION').is_file():
    raise SystemExit('Invalid backup path')
state_path=project/'data/state/receiver_manager.json'
data=json.loads(state_path.read_text()) if state_path.exists() else {}
if any(data.get(k) for k in ('reservations','reservation','binding_transaction','hardware_recovery')):
    raise SystemExit('Stop/resolve receiver activity and hardware recovery before code rollback')
subprocess.run(['sudo','systemctl','stop','sdrcc.service'],check=True)
for src in (backup/'files').rglob('*'):
    if src.is_file():
        dst=project/src.relative_to(backup/'files');dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
for relative in json.loads((backup/'created.json').read_text()):
    dst=project/relative
    if dst.is_file():dst.unlink()
subprocess.run(['sudo','systemctl','start','sdrcc.service'],check=True)
print('Source restored. Current receiver bindings and local settings retained.')
