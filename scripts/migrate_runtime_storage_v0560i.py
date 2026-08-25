#!/usr/bin/env python3
from pathlib import Path
import os, sys, yaml
ROOT = Path(__file__).resolve().parent.parent
path = ROOT / 'config' / 'iss_voice.yaml'
doc = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
cfg = doc.get('iss_voice')
if not isinstance(cfg, dict):
    raise SystemExit('invalid config/iss_voice.yaml')
storage = cfg.get('storage')
if storage is None:
    storage = {}
    cfg['storage'] = storage
if not isinstance(storage, dict):
    raise SystemExit('iss_voice.storage must be a mapping')
storage.setdefault('keep_raw_iq', False)
tmp = path.with_suffix('.yaml.tmp')
with tmp.open('w', encoding='utf-8') as h:
    yaml.safe_dump(doc, h, sort_keys=False)
    h.flush(); os.fsync(h.fileno())
os.chmod(tmp, path.stat().st_mode & 0o777)
tmp.replace(path)
print(f"keep_raw_iq={str(storage['keep_raw_iq']).lower()}")
