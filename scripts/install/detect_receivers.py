#!/usr/bin/env python3
"""Detect RTL-SDR identity for installer use. USB index is presentation-only."""
from __future__ import annotations
import argparse, json, re, shutil, subprocess

LINE_RE=re.compile(r"^\s*(?P<index>\d+):\s*(?P<body>.+?),\s*SN:\s*(?P<serial>\S+)\s*$")

def detect():
    exe=shutil.which('rtl_test')
    if not exe: raise RuntimeError('rtl_test is not installed')
    try:
        done=subprocess.run([exe,'-t'],text=True,capture_output=True,timeout=4,check=False)
    except subprocess.TimeoutExpired as e:
        text=(e.stdout or '')+(e.stderr or '')
    else:
        text=(done.stdout or '')+'\n'+(done.stderr or '')
    rows=[]
    for line in text.splitlines():
        m=LINE_RE.match(line)
        if m:
            rows.append({'index':int(m.group('index')), 'serial':m.group('serial'), 'description':m.group('body').strip()})
    # Serial is canonical; index is never persisted.
    unique={r['serial']:r for r in rows}
    return list(unique.values())

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--json',action='store_true'); args=ap.parse_args()
    rows=detect()
    if args.json: print(json.dumps({'receivers':rows},indent=2))
    else:
        if not rows: print('No RTL-SDR receivers detected.')
        for i,row in enumerate(rows,1): print(f"{i}. {row['description']}  serial={row['serial']}")
    return 0 if rows else 1
if __name__=='__main__': raise SystemExit(main())
