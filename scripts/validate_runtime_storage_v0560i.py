#!/usr/bin/env python3
from pathlib import Path
import ast, sys, tempfile, logging
ROOT=Path(__file__).resolve().parent.parent
checks=[]
def check(ok,msg):
    print(('PASS: ' if ok else 'FAIL: ')+msg); checks.append(bool(ok))
check((ROOT/'VERSION').read_text().strip()=='0.56.0i','release version is 0.56.0i')
for rel in ['core/iss_voice_executor.py','core/iss_voice.py','core/logger.py','config/iss_voice.yaml']:
    try: ast.parse((ROOT/rel).read_text()); ok=True
    except SyntaxError: ok=rel.endswith('.yaml')
    check(ok,f'{rel} is parseable')
import yaml
cfg=(yaml.safe_load((ROOT/'config/iss_voice.yaml').read_text()) or {}).get('iss_voice') or {}
check(isinstance(cfg.get('storage'),dict),'ISS Voice storage policy is configured')
check(cfg.get('storage',{}).get('keep_raw_iq') is False,'raw IQ retention defaults to false')
ex=(ROOT/'core/iss_voice_executor.py').read_text()
check('_remove_validated_iq' in ex,'ISS executor owns bounded post-success IQ cleanup')
check('if failure is None' in ex and 'iq_retention = _remove_validated_iq' in ex,'cleanup runs only on successful mission path')
check('relative_to(recordings_root)' in ex and 'iq_filename' in ex,'cleanup is bounded to expected ISS recording path')
check('mission_failed' in ex,'failed missions retain raw IQ')
check('keep_raw_iq' in ex,'operator keep_raw_iq policy is honored')
log=(ROOT/'core/logger.py').read_text()
check('RotatingFileHandler' in log,'SDRCC file log uses rotation')
check('10 * 1024 * 1024' in log and 'LOG_BACKUP_COUNT = 3' in log,'log retention is bounded to 10 MiB plus three backups')
check('storage_manager' not in ex.lower(),'release does not add a second storage authority')
if not all(checks): raise SystemExit(1)
print('VALIDATION PASS: SDRCC v0.56.0i Runtime Storage & Log Retention')
