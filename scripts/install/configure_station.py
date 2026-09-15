#!/usr/bin/env python3
"""Apply initial station identity/location and optional receiver serial mapping.

config/station.yaml remains the Home Position authority. Latitude/longitude are
mirrored to readsb DECODER_OPTIONS through the bounded privileged helper.
AIS-catcher configuration and receiver-role policy are not changed here.
"""
from __future__ import annotations
import argparse, copy, os, subprocess, tempfile
from pathlib import Path
import sys
import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from core.config import normalize_home_position

STATION=ROOT/'config/station.yaml'; RECEIVERS=ROOT/'config/receivers.yaml'
READSB_POSITION_HELPER=Path('/usr/local/sbin/sdrcc-sync-readsb-position')

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
    p.add_argument('--sdr1-serial',default=None)
    p.add_argument('--sdr2-serial',default=None)
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if a.sdr1_serial and a.sdr1_serial==a.sdr2_serial: p.error('SDR1 and SDR2 must have different serials')
    station_name=a.station_name.strip()
    if not station_name: p.error('station name must not be empty')
    if len(station_name)>80: p.error('station name must be 80 characters or fewer')
    try:
        position=normalize_home_position({
            'location':a.location,
            'latitude':a.latitude,
            'longitude':a.longitude,
            'altitude_m':a.altitude_m,
        })
    except ValueError as error:
        p.error(str(error))
    station=yaml.safe_load(STATION.read_text()) or {}; receivers=yaml.safe_load(RECEIVERS.read_text()) or {}
    station_before=copy.deepcopy(station)
    st=station.setdefault('station',{}); st.update({'name':station_name,**position})
    rs=receivers.setdefault('receivers',{})
    for key,serial in [('receiver01',a.sdr1_serial),('receiver02',a.sdr2_serial)]:
        if serial is None: continue
        if key not in rs: raise SystemExit(f'{key} missing from receivers.yaml')
        rs[key].setdefault('hardware',{})['serial']=str(serial)
    print(f"Station name: {station_name}")
    print(f"Home Position: {position['location']} ({position['latitude']}, {position['longitude']}) altitude={position['altitude_m']}m ASL")
    print(f"SDR1 serial: {a.sdr1_serial}")
    print(f"SDR2 serial: {a.sdr2_serial}")
    if not a.apply:
        print('Dry run only; pass --apply to write configuration.')
        return 0
    atomic_yaml(STATION,station)
    try:
        result=subprocess.run(
            [
                'sudo','-n',str(READSB_POSITION_HELPER),
                f"{position['latitude']:.6f}",
                f"{position['longitude']:.6f}",
            ],
            text=True,capture_output=True,timeout=60,check=False,
        )
        if result.returncode:
            raise RuntimeError(
                (result.stderr or result.stdout or 'readsb position sync failed').strip()
            )
    except Exception as error:
        atomic_yaml(STATION,station_before)
        raise SystemExit(f'Home Position readsb sync failed: {error}') from error

    atomic_yaml(RECEIVERS,receivers)
    print(f'Station configuration saved to {STATION}. readsb Home Position synchronized; receiver roles unchanged.')
    return 0
if __name__=='__main__': raise SystemExit(main())
