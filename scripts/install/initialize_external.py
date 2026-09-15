#!/usr/bin/env python3
"""Prepare clean-install readsb placeholder while receiver services are stopped.

AIS-catcher is deliberately left untouched here. Its initial receiver and output
configuration is owned by the upstream AIS-catcher wizard at the end of install.
Never used by the update path.
"""
from pathlib import Path
import re, os, tempfile, shutil

def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_name(path.name + '.before-flexground-initialization')
        if not backup.exists(): shutil.copy2(path, backup)
    fd, temp = tempfile.mkstemp(dir=path.parent)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text); handle.flush(); os.fsync(handle.fileno())
    os.chmod(temp, path.stat().st_mode & 0o777 if path.exists() else 0o644)
    if path.exists():
        previous = path.stat()
        os.chown(temp, previous.st_uid, previous.st_gid)
    os.replace(temp, path)

def initialize(readsb=Path('/etc/default/readsb')):
    text = readsb.read_text() if readsb.exists() else ''
    if not any('--device ' in line or '--device=' in line for line in text.splitlines() if not line.lstrip().startswith('#')):
        match = re.search(r'(?m)^RECEIVER_OPTIONS="([^"\n]*)"[ \t]*$', text)
        if match:
            text = text[:match.start()] + 'RECEIVER_OPTIONS="' + match[1] + ' --device UNBOUND_ADSB"' + text[match.end():]
        elif re.search(r'(?m)^RECEIVER_OPTIONS=', text):
            raise RuntimeError('Unrecognised readsb RECEIVER_OPTIONS; preserve configuration and review it')
        else:
            text += '\nRECEIVER_OPTIONS="--device-type rtlsdr --device UNBOUND_ADSB --gain auto"\n'
        atomic(readsb, text)

if __name__ == '__main__': initialize()
