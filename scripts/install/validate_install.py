#!/usr/bin/env python3
"""Post-install validation for the v1.0 installer foundation."""
from __future__ import annotations
import argparse, json, os, shutil, subprocess
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[2]

def service_exists(name):
    d=subprocess.run(['systemctl','show',name,'--property=LoadState','--value'],text=True,capture_output=True,check=False)
    return d.returncode==0 and d.stdout.strip() not in ('','not-found')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--json',action='store_true'); args=ap.parse_args()
    checks={
      'version': (ROOT/'VERSION').exists(),
      'venv_python': (ROOT/'venv/bin/python').exists(),
      'station_yaml': (ROOT/'config/station.yaml').exists(),
      'receivers_yaml': (ROOT/'config/receivers.yaml').exists(),
      'sdrcc_service': service_exists('sdrcc.service'),
      'receiver_helper': Path('/usr/local/sbin/sdrcc-apply-receiver-roles').exists(),
    }
    try:
      r=yaml.safe_load((ROOT/'config/receivers.yaml').read_text())['receivers']
      serials=[str(v.get('hardware',{}).get('serial','')).strip() for v in r.values() if v.get('enabled',True)]
      checks['receiver_serials']=len(serials)>=1 and len(serials)==len(set(serials)) and all(serials)
    except Exception: checks['receiver_serials']=False
    payload={'ok':all(checks.values()),'checks':checks}
    if args.json: print(json.dumps(payload,indent=2))
    else:
      for k,v in checks.items(): print(f"{'PASS' if v else 'FAIL'}: {k}")
    return 0 if payload['ok'] else 1
if __name__=='__main__': raise SystemExit(main())
