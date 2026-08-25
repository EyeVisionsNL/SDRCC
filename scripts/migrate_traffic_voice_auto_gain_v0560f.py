#!/usr/bin/env python3
from pathlib import Path
import os
import yaml

ROOT = Path('/home/eyevisions/SDRCC')
path = ROOT / 'config' / 'traffic_voice.yaml'
data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
settings = data.setdefault('traffic_voice', {})
backend = settings.setdefault('backend', {})
mode = str(backend.get('gain_mode') or '').strip().lower()
if mode not in {'auto', 'manual'}:
    backend['gain_mode'] = 'auto'
    tmp = path.with_suffix('.yaml.tmp')
    tmp.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    try:
        os.chmod(tmp, path.stat().st_mode & 0o777)
    except OSError:
        pass
    tmp.replace(path)
    print('Traffic Voice gain_mode initialized to auto')
else:
    print(f'Traffic Voice gain_mode retained: {mode}')
