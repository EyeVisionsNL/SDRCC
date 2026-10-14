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
# The Mobile ATIS bridge lives outside the project tree. Its rollback state
# is backed up only when the managed update actually replaced or created it.
ais_previous=backup/'ais-mobile-plugin-previous.pjs'
ais_created=backup/'ais-mobile-plugin-created'
ais_plugin=Path('/etc/AIS-catcher/plugins/sdrcc-mobile-atis.pjs')
restore_ais=ais_previous.is_file() or ais_created.is_file()
if restore_ais:
    if os.geteuid()!=0:
        raise SystemExit('Rollback includes AIS-Catcher plugin. Run this rollback script with sudo.')
    if ais_plugin.is_symlink():
        raise SystemExit('AIS mobile plugin path is a symlink; refusing rollback')
    if ais_plugin.exists() and b'SDRCC-ATIS-MOBILE-BRIDGE' not in ais_plugin.read_bytes():
        raise SystemExit('AIS mobile plugin was replaced externally; refusing rollback')
subprocess.run(['sudo','systemctl','stop','sdrcc.service'],check=True)
for src in (backup/'files').rglob('*'):
    if src.is_file():
        dst=project/src.relative_to(backup/'files');dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
for relative in json.loads((backup/'created.json').read_text()):
    dst=project/relative
    if dst.is_file():dst.unlink()
if restore_ais:
    if ais_previous.is_file():
        if not ais_plugin.parent.is_dir() or ais_plugin.parent.is_symlink():
            raise SystemExit('AIS plugin directory unavailable for restoration')
        subprocess.run(['/usr/bin/install','-o','root','-g','root','-m','0644',str(ais_previous),str(ais_plugin)],check=True)
    elif ais_created.is_file() and ais_plugin.is_file():
        ais_plugin.unlink()

subprocess.run(['sudo','systemctl','start','sdrcc.service'],check=True)
print('Source restored. Current receiver bindings and local settings retained.')
if restore_ais:
    print('AIS plugin restored; restart AIS-Catcher when the receiver is idle to reload it.')
