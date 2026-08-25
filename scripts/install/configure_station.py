#!/usr/bin/env python3
"""Apply initial station identity/location and receiver serial mapping.

This changes only config/station.yaml and config/receivers.yaml. It does not
start services and does not edit readsb/AIS-catcher configuration.
"""
from __future__ import annotations
import argparse, os, tempfile
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[2]
STATION=ROOT/'config/station.yaml'; RECEIVERS=ROOT/'config/receivers.yaml'

def atomic_yaml(path:Path,payload:dict):
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            yaml.safe_dump(payload,f,sort_keys=False,allow_unicode=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--station-name',default='SDRCC')
    p.add_argument('--location',required=True)
    p.add_argument('--latitude',type=float,required=True)
    p.add_argument('--longitude',type=float,required=True)
    p.add_argument('--altitude-m',type=float,default=0.0)
    p.add_argument('--sdr1-serial',required=True)
    p.add_argument('--sdr2-serial',required=True)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if a.sdr1_serial==a.sdr2_serial: p.error('SDR1 and SDR2 must have different serials')
    if not (-90<=a.latitude<=90 and -180<=a.longitude<=180): p.error('invalid latitude/longitude')
    station=yaml.safe_load(STATION.read_text()) or {}; receivers=yaml.safe_load(RECEIVERS.read_text()) or {}
    st=station.setdefault('station',{}); st.update({'name':a.station_name,'location':a.location,'latitude':a.latitude,'longitude':a.longitude,'altitude_m':a.altitude_m})
    rs=receivers.setdefault('receivers',{})
    for key,serial in [('receiver01',a.sdr1_serial),('receiver02',a.sdr2_serial)]:
        if key not in rs: raise SystemExit(f'{key} missing from receivers.yaml')
        rs[key].setdefault('hardware',{})['serial']=str(serial)
    print(f"Station: {a.location} ({a.latitude}, {a.longitude}) altitude={a.altitude_m}m")
    print(f"SDR1 serial: {a.sdr1_serial}")
    print(f"SDR2 serial: {a.sdr2_serial}")
    if not a.apply:
        print('Dry run only; pass --apply to write configuration.')
        return 0
    atomic_yaml(STATION,station); atomic_yaml(RECEIVERS,receivers)
    print('Initial SDRCC station configuration written. External AIS/readsb roles are unchanged.')
    return 0
if __name__=='__main__': raise SystemExit(main())
