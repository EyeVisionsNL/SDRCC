#!/usr/bin/env python3
"""Post-install validation for the SDRCC v1.0 installer path."""
from __future__ import annotations
import argparse, json, shutil, subprocess
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
      'readsb_service': service_exists('readsb.service'),
      'ais_service': service_exists('ais-catcher.service'),
      'traffic_voice_service': service_exists('sdrcc-traffic-voice.service'),
      'receiver_helper': Path('/usr/local/sbin/sdrcc-apply-receiver-roles').exists(),
      'satdump': shutil.which('satdump') is not None,
      'readsb': shutil.which('readsb') is not None,
      'ais_catcher': shutil.which('AIS-catcher') is not None,
      'airband': Path('/opt/sdrcc/traffic_voice/bin/rtl_airband').exists(),
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
